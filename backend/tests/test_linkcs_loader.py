"""Synthetic unit & integration tests for the LinkCS dataset loader (zero real personal data)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.repository import InMemoryAlumniRepository
from app.main import create_app
from app.services.enrichment import EnrichmentService
from app.services.graph_engine import GraphEngine
from app.services.linkcs_loader import extract_asso_name, load_linkcs_dataset
from app.services.llm import DeterministicLLMService


def _write_synthetic_json(tmp_path: Path) -> Path:
    data = [
        {
            "login": "2020fictif_a",
            "prenom": "Camille",
            "nom": "Fictive",
            "nom_complet": "Camille Fictive",
            "promotion": 2020,
            "email_etudiant": "camille.fictive@student.ecp.fr",
            "tous_les_emails": ["camille.fictive@student.ecp.fr"],
            "associations": [
                "Raid CentraleSupélec [GPA Concs (Edition 2018)]",
                "Club Tech [Présidente (2019)]",
            ],
            "clubs_et_groupes": [
                "Cercle Aérospatial [Membre (2018)]",
                "MegaClub [Membre]",
            ],
            "categories_assos": ["Sports et plein air", "Sciences et techniques"],
            "biographie": "Passionnée de spatial et de course en montagne.",
            "reseaux_sociaux": ["https://www.linkedin.com/in/camille-fictive/?trk=x"],
        },
        {
            "login": "2020fictif_b",
            "prenom": "Bastien",
            "nom": "Exemple",
            "nom_complet": "Bastien Exemple",
            "promotion": 2020,
            "email_etudiant": "bastien.exemple@student.ecp.fr",
            "tous_les_emails": ["bastien.exemple@student.ecp.fr"],
            "associations": ["Club Tech [VP Events (2019)]"],
            "clubs_et_groupes": [
                "Cercle Aérospatial [Trésorier (2018)]",
                "Club Aviron [Skipper (2019)]",
                "MegaClub [Membre]",
            ],
            "categories_assos": ["Sciences et techniques", "Sports et plein air"],
            "biographie": "",
            "reseaux_sociaux": [],
        },
        {
            "login": "2020fictif_c",
            "prenom": "Noémie",
            "nom": "Test",
            "nom_complet": "Noémie Test",
            "promotion": 2020,
            "email_etudiant": "noemie.test@student.ecp.fr",
            "tous_les_emails": ["noemie.test@student.ecp.fr"],
            "associations": [],
            "clubs_et_groupes": ["Club Aviron [Membre (2019)]"],
            "categories_assos": ["Sports et plein air"],
            "biographie": "",
            "reseaux_sociaux": [],
        },
        {
            "login": "2020fictif_d",
            "prenom": "Dorian",
            "nom": "Sample",
            "nom_complet": "Dorian Sample",
            "promotion": 2020,
            "email_etudiant": "dorian.sample@student.ecp.fr",
            "tous_les_emails": ["dorian.sample@student.ecp.fr"],
            "associations": [],
            "clubs_et_groupes": ["MegaClub [Membre]"],
            "categories_assos": ["Communautés"],
            "biographie": "",
            "reseaux_sociaux": [],
        },
    ]
    json_path = tmp_path / "synthetic_linkcs.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return json_path


def _write_synthetic_csv(tmp_path: Path) -> Path:
    csv_content = (
        "nom_complet,prenom,nom,login,promotion,email_etudiant,emails_perso,tous_les_emails,"
        "associations,clubs_et_groupes,abonnements,categories_assos,biographie,points_d_interets\n"
        "Camille Fictive,Camille,Fictive,2020fictif_a,2020,camille.fictive@student.ecp.fr,,camille.fictive@student.ecp.fr,"
        "Raid CentraleSupélec [GPA Concs (2018)] ; Club Tech [Présidente (2019)],"
        "Cercle Aérospatial [Membre (2018)],,Sports et plein air ; Sciences et techniques,Bio spatiale,\n"
        "Bastien Exemple,Bastien,Exemple,2020fictif_b,2020,bastien.exemple@student.ecp.fr,,bastien.exemple@student.ecp.fr,"
        "Club Tech [VP Events (2019)],,,Sciences et techniques,,\n"
    )
    csv_path = tmp_path / "synthetic_linkcs.csv"
    csv_path.write_text(csv_content, encoding="utf-8")
    return csv_path


def test_extract_asso_name_strips_role_brackets():
    assert extract_asso_name("Raid CentraleSupélec [GPA Concs (Edition 2018)]") == "Raid CentraleSupélec"
    assert extract_asso_name("ViaRézo [Core Team (2018)]") == "ViaRézo"
    assert extract_asso_name("BDS") == "BDS"


def test_load_linkcs_json_edges_and_max_group_size(tmp_path: Path):
    json_path = _write_synthetic_json(tmp_path)
    # max_group_size=2 forces MegaClub (3 members) to be skipped while pairs of 2 are linked!
    profiles, edges = load_linkcs_dataset(
        json_path,
        include_demo_student=False,
        compute_embeddings=True,
        max_group_size=2,
    )
    assert len(profiles) == 4

    camille = next(p for p in profiles if p.full_name == "Camille Fictive")
    assert camille.linkedin_url == "https://www.linkedin.com/in/camille-fictive"
    assert camille.last_enriched_at is None
    assert camille.enrichment_source == "LINKCS_DB"
    assert "Raid CentraleSupélec" in camille.associations
    assert "Club Tech" in camille.associations
    assert "Cercle Aérospatial" in camille.associations
    assert camille.embedding is not None and len(camille.embedding) == 768

    # Camille & Bastien share official Club Tech (0.70) AND Cercle Aérospatial (0.60) -> keeps 0.70!
    bastien = next(p for p in profiles if p.full_name == "Bastien Exemple")
    noemie = next(p for p in profiles if p.full_name == "Noémie Test")
    dorian = next(p for p in profiles if p.full_name == "Dorian Sample")
    by_pair = {(e.source_id, e.target_id): e for e in edges}

    pair_cb = (camille.id, bastien.id) if camille.id < bastien.id else (bastien.id, camille.id)
    assert pair_cb in by_pair
    assert by_pair[pair_cb].probability == 0.70

    # Bastien & Noémie share club Club Aviron -> 0.60
    pair_bn = (bastien.id, noemie.id) if bastien.id < noemie.id else (noemie.id, bastien.id)
    assert pair_bn in by_pair
    assert by_pair[pair_bn].probability == 0.60

    # Camille & Dorian share ONLY MegaClub (size 3 > max_group_size=2) -> must NOT be directly linked
    pair_cd = (camille.id, dorian.id) if camille.id < dorian.id else (dorian.id, camille.id)
    assert pair_cd not in by_pair


def test_load_linkcs_csv_semicolon_fields(tmp_path: Path):
    csv_path = _write_synthetic_csv(tmp_path)
    profiles, edges = load_linkcs_dataset(csv_path, include_demo_student=False)
    assert len(profiles) == 2
    assert len(edges) == 1
    assert edges[0].probability == 0.70
    assert "Club Tech" in edges[0].reason


def test_app_boots_with_linkcs_data_path_and_supports_real_member_query(tmp_path: Path):
    json_path = _write_synthetic_json(tmp_path)
    settings = Settings(
        database_url=None,
        demo_mode=True,
        allow_demo_auth=True,
        linkcs_data_path=str(json_path),
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["status"] == "ok"
        assert health["graph"]["nodes"] == 5  # 4 LinkCS profiles + Léo Bernard

        # Search as demo student Léo Bernard -> finds multi-hop path to Noémie via Bastien or Camille
        res = client.post(
            "/api/v1/search/action-plan",
            json={"query": "Je cherche quelqu'un du Cercle Aérospatial", "limit": 3},
        )
        assert res.status_code == 200
        body = res.json()
        assert len(body["solutions"]) >= 1
        assert body["solutions"][0]["target"]["full_name"] == "Camille Fictive"

        # Query directly on behalf of a LinkCS member by email or full name
        res_member = client.post(
            "/api/v1/search/action-plan",
            json={
                "user_id": "Camille Fictive",
                "query": "Je veux contacter un membre du Club Aviron",
                "limit": 2,
            },
        )
        assert res_member.status_code == 200
        member_data = res_member.json()
        # Camille -> Bastien -> Noémie
        noemie_sol = next(s for s in member_data["solutions"] if s["target"]["full_name"] == "Noémie Test")
        assert noemie_sol["primary_path"] is not None
        assert noemie_sol["primary_path"]["hop_count"] == 2
        assert noemie_sol["primary_path"]["hops"][0]["to_name"] == "Bastien Exemple"


@pytest.mark.asyncio
async def test_enrichment_backfills_company_and_role_on_linkcs_profile(tmp_path: Path):
    json_path = _write_synthetic_json(tmp_path)
    profiles, edges = load_linkcs_dataset(json_path, include_demo_student=False)
    repo = InMemoryAlumniRepository()
    for p in profiles:
        await repo.upsert_profile(p)
    await repo.upsert_edges(edges)

    class FakeLinkCSTavily:
        async def search(self, query: str, max_results: int = 4) -> list[dict]:
            if "Camille Fictive" in query:
                return [
                    {
                        "title": "Camille Fictive - ArianeGroup",
                        "url": "https://example.com/camille",
                        "content": "Camille Fictive travaille comme Ingénieure Propulsion chez ArianeGroup (2021-Present).",
                    }
                ]
            return []

    graph = GraphEngine()
    graph.reload(await repo.list_profiles(), await repo.list_edges())
    llm = DeterministicLLMService(embedding_dim=768)
    enrichment = EnrichmentService(repo, llm, graph, web_client=FakeLinkCSTavily())

    camille = next(p for p in profiles if p.full_name == "Camille Fictive")
    assert camille.current_company is None and camille.current_role is None

    updated = await enrichment.enrich_candidates([camille])
    assert len(updated) == 1
    assert updated[0].current_company == "ArianeGroup"
    assert updated[0].current_role is not None and "Propulsion" in updated[0].current_role
