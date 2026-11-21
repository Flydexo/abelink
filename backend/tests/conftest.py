"""Shared pytest fixtures with seeded in-memory repository, fake LLM, and fake Tavily."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.repository import EdgeRecord, InMemoryAlumniRepository, ProfileRecord
from app.main import create_app
from app.services.graph_engine import GraphEngine
from app.services.llm import DeterministicLLMService, deterministic_text_embedding


class SpyTavilyClient:
    """Fake Tavily search client tracking queries for cache & trigger assertions."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def search(self, query: str, max_results: int = 4) -> list[dict]:
        self.calls.append(query)
        if "Marc Petit" in query:
            return [
                {
                    "title": "Marc Petit - VP Engineering chez GreenTech Energy",
                    "url": "https://example.com/marc-petit",
                    "content": (
                        "Marc Petit est VP Engineering chez GreenTech Energy (2021-Present). "
                        "Ancien du Club Énergie à CentraleSupélec. Passions: énergie décarbonée, trail."
                    ),
                }
            ]
        return []


def build_test_repository() -> InMemoryAlumniRepository:
    now = datetime.now(timezone.utc)
    repo = InMemoryAlumniRepository()

    profiles = [
        ProfileRecord(
            id="11111111-1111-4111-8111-111111111111",
            full_name="Léo Bernard",
            email="leo@student-cs.fr",
            linkedin_url="https://www.linkedin.com/in/leo-bernard",
            promo_year=2026,
            current_role="Élève-ingénieur 2A",
            current_company="CentraleSupélec",
            sector="Étudiant",
            experiences=[{"company": "Ekimetrics", "role": "Stagiaire Data", "start_date": "2025-06", "end_date": "2025-09"}],
            associations=["BDS", "CentraleSupélec Runner", "Club Énergie"],
            passions=["trail", "IA générative"],
            is_student=True,
            has_imported_linkedin=True,
            enrichment_source="LINKEDIN_ARCHIVE",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id="22222222-2222-4222-8222-222222222222",
            full_name="Alice Martin",
            email="alice@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/alice-martin",
            promo_year=2020,
            current_role="Lead ML Engineer",
            current_company="Mistral AI",
            sector="Intelligence Artificielle",
            bio="Lead ML Engineer chez Mistral AI, ex-Doctolib.",
            experiences=[
                {"company": "Mistral AI", "role": "Lead ML Engineer", "start_date": "2023-05", "end_date": "Present"},
                {"company": "Doctolib", "role": "ML Engineer", "start_date": "2020-06", "end_date": "2023-04"},
            ],
            associations=["Junior CentraleSupélec", "BDS"],
            passions=["course en montagne", "modèles de langage", "trail"],
            last_enriched_at=now,
        ),
        ProfileRecord(
            id="33333333-3333-4333-8333-333333333333",
            full_name="Thomas Leroy",
            email="thomas@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/thomas-leroy",
            promo_year=2023,
            current_role="Data Scientist",
            current_company="Ekimetrics",
            sector="Conseil Data",
            bio="Data Scientist chez Ekimetrics.",
            experiences=[
                {"company": "Ekimetrics", "role": "Data Scientist", "start_date": "2023-09", "end_date": "Present"},
            ],
            associations=["BDS"],
            passions=["football", "finance"],
            last_enriched_at=now,
        ),
        ProfileRecord(
            id="44444444-4444-4444-8444-444444444444",
            full_name="Claire Moreau",
            email="claire@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/claire-moreau",
            promo_year=2019,
            current_role="Product Manager",
            current_company="Doctolib",
            sector="Santé / Tech",
            bio="Product Manager chez Doctolib.",
            experiences=[
                {"company": "Doctolib", "role": "Product Manager", "start_date": "2019-10", "end_date": "Present"},
            ],
            associations=["BDS"],
            passions=["natation", "santé numérique"],
            last_enriched_at=now,
        ),
        ProfileRecord(
            id="55555555-5555-4555-8555-555555555555",
            full_name="Sarah Cohen",
            email="sarah@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/sarah-cohen",
            promo_year=2021,
            current_role="Investment Associate",
            current_company="Partech",
            sector="Venture Capital",
            bio="Investment Associate chez Partech.",
            experiences=[
                {"company": "Partech", "role": "Investment Associate", "start_date": "2022-01", "end_date": "Present"},
            ],
            associations=["Junior CentraleSupélec"],
            passions=["startups", "tennis"],
            last_enriched_at=now,
        ),
        # Deliberately sparse / unenriched profile (last_enriched_at=None, has_imported_linkedin=False)
        ProfileRecord(
            id="66666666-6666-4666-8666-666666666666",
            full_name="Marc Petit",
            email="marc@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/marc-petit",
            promo_year=2018,
            current_role="VP Engineering",
            current_company="GreenTech Energy",
            sector="Énergie / Climat",
            bio=None,
            experiences=[
                {"company": "GreenTech Energy", "role": "VP Engineering", "start_date": "2021-01", "end_date": "Present"},
            ],
            associations=[],
            passions=[],
            has_imported_linkedin=False,
            last_enriched_at=None,
        ),
        # LinkedIn imported profile with last_enriched_at=None -> must NOT trigger Tavily
        ProfileRecord(
            id="77777777-7777-4777-8777-777777777777",
            full_name="Benoît Garnier",
            email="benoit@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/benoit-garnier",
            promo_year=2017,
            current_role="Directeur Solaire",
            current_company="Engie",
            sector="Énergie / Climat",
            bio="Directeur Solaire chez Engie.",
            experiences=[
                {"company": "Engie", "role": "Directeur Solaire", "start_date": "2020-01", "end_date": "Present"},
            ],
            associations=["Club Énergie"],
            passions=["solaire"],
            has_imported_linkedin=True,
            enrichment_source="LINKEDIN_ARCHIVE",
            last_enriched_at=None,
        ),
    ]

    for p in profiles:
        p.embedding = deterministic_text_embedding(p.searchable_text(), dim=768)
        repo.profiles[p.id] = p

    edges = [
        EdgeRecord(
            source_id="11111111-1111-4111-8111-111111111111",
            target_id="33333333-3333-4333-8333-333333333333",
            edge_type="EXPLICIT_LINKEDIN",
            probability=0.95,
            reason="Connexion LinkedIn directe (Stage Ekimetrics 2025)",
        ),
        EdgeRecord(
            source_id="33333333-3333-4333-8333-333333333333",
            target_id="44444444-4444-4444-8444-444444444444",
            edge_type="INFERRED_ASSO",
            probability=0.55,
            reason="Même asso BDS à CentraleSupélec",
        ),
        EdgeRecord(
            source_id="22222222-2222-4222-8222-222222222222",
            target_id="44444444-4444-4444-8444-444444444444",
            edge_type="INFERRED_COMPANY",
            probability=0.72,
            reason="Chevauchement chez Doctolib (2020-2023)",
        ),
        EdgeRecord(
            source_id="11111111-1111-4111-8111-111111111111",
            target_id="55555555-5555-4555-8555-555555555555",
            edge_type="INFERRED_SCHOOL",
            probability=0.35,
            reason="Réseau CentraleSupélec (promo proche)",
        ),
        EdgeRecord(
            source_id="22222222-2222-4222-8222-222222222222",
            target_id="55555555-5555-4555-8555-555555555555",
            edge_type="INFERRED_ASSO",
            probability=0.60,
            reason="Même asso Junior CentraleSupélec",
        ),
        EdgeRecord(
            source_id="11111111-1111-4111-8111-111111111111",
            target_id="77777777-7777-4777-8777-777777777777",
            edge_type="INFERRED_ASSO",
            probability=0.65,
            reason="Même asso Club Énergie à CentraleSupélec",
        ),
    ]
    for e in edges:
        repo.edges[(e.source_id, e.target_id, e.edge_type)] = e

    return repo


@pytest.fixture()
def test_repo() -> InMemoryAlumniRepository:
    return build_test_repository()


@pytest.fixture()
def fake_llm() -> DeterministicLLMService:
    return DeterministicLLMService(embedding_dim=768)


@pytest.fixture()
def spy_tavily() -> SpyTavilyClient:
    return SpyTavilyClient()


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url=None,
        auth_secret="test-secret-key-minimum-32-bytes-long",
        allow_demo_auth=True,
        demo_mode=True,
        public_api_url="http://testserver",
    )


@pytest.fixture()
def test_app(
    test_settings: Settings,
    test_repo: InMemoryAlumniRepository,
    fake_llm: DeterministicLLMService,
    spy_tavily: SpyTavilyClient,
):
    return create_app(
        settings=test_settings,
        repository=test_repo,
        llm_service=fake_llm,
        web_client=spy_tavily,
        graph_engine=GraphEngine(),
    )


@pytest.fixture()
def client(test_app):
    with TestClient(test_app) as c:
        yield c
