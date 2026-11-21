"""Seed script generating 500+ realistic CentraleSupélec alumni profiles, embeddings, and inferred edges."""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure backend root is importable when running `python scripts/seed_mock_alumni.py`
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.db.repository import EdgeRecord, PostgresAlumniRepository, ProfileRecord
from app.db.session import create_db_engine, create_session_factory, run_sql_migrations
from app.services.graph_engine import GraphEngine
from app.services.llm import VertexLLMService, deterministic_text_embedding

FIRST_NAMES = [
    "Camille", "Lucas", "Léa", "Hugo", "Chloé", "Nathan", "Manon", "Antoine",
    "Emma", "Théo", "Inès", "Maxime", "Sarah", "Alexandre", "Zoé", "Baptiste",
    "Juliette", "Thomas", "Clara", "Nicolas", "Margaux", "Romain", "Louise", "Clément",
    "Anaïs", "Yanis", "Jade", "Adrien", "Sofia", "Paul", "Élodie", "Quentin",
    "Alice", "Julien", "Mathilde", "Gabriel", "Océane", "Valentin", "Victoire", "Arthur",
]

LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit", "Durand",
    "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David",
    "Bertrand", "Roux", "Vincent", "Fournier", "Morel", "Girard", "Andre", "Mercier",
    "Dupont", "Lambert", "Bonnet", "Francois", "Martinez", "Legrand", "Garnier", "Faure",
    "Rousseau", "Blanc", "Guerin", "Muller", "Henry", "Roussel", "Nicolas", "Perrin",
]

SECTORS_DATA = [
    (
        "Intelligence Artificielle",
        ["Mistral AI", "Ekimetrics", "Hugging Face", "Dataiku", "Owkin", "Dust"],
        ["Lead ML Engineer", "Data Scientist", "AI Research Engineer", "Applied AI Lead", "Head of Data"],
    ),
    (
        "Énergie / Climat",
        ["Engie", "EDF", "TotalEnergies", "Schneider Electric", "Qair", "GreenTech Energy", "Sweetch Energy"],
        ["Responsable développement", "Ingénieur projets renouvelables", "VP Engineering", "Chef de projet hydrogène", "Directeur transition énergétique"],
    ),
    (
        "Santé / Tech",
        ["Doctolib", "Alan", "Withings", "Qare", "Owkin", "Nabla"],
        ["Product Manager", "Senior Product Manager", "Engineering Manager", "Data Engineer", "VP Product"],
    ),
    (
        "Finance",
        ["BNP Paribas", "Société Générale", "Natixis", "Amundi", "AXA Investment Managers"],
        ["Quantitative Analyst", "Structurer", "Risk Analyst", "Portfolio Manager", "Quant Researcher"],
    ),
    (
        "Fintech",
        ["Qonto", "Lydia", "Swile", "Pennylane", "Alma", "PayFit"],
        ["Cofondateur", "Head of Product", "Staff Backend Engineer", "Growth Lead", "VP Engineering"],
    ),
    (
        "Venture Capital",
        ["Partech", "Elaia", "Daphni", "Kima Ventures", "Serena"],
        ["Investment Associate", "Principal", "Analyst VC", "Partner"],
    ),
]

ASSOCIATIONS = [
    "BDS",
    "BDE",
    "Junior CentraleSupélec",
    "Club Énergie",
    "Data Club",
    "Club Finance",
    "Incubateur",
    "CentraleSupélec Runner",
    "Club Voile",
]

PASSIONS = [
    "trail",
    "course en montagne",
    "IA générative",
    "modèles de langage",
    "énergie décarbonée",
    "randonnée alpine",
    "santé numérique",
    "natation",
    "voile",
    "tennis",
    "football",
    "startups",
    "finance quantitative",
    "escalade",
    "photographie",
]

LOCATIONS = ["Paris", "La Défense", "Lyon", "Gif-sur-Yvette", "Bordeaux", "Toulouse", "Londres"]


def _uuid_from_seed(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"abelink.{key}"))


def _build_anchor_profiles(now: datetime) -> list[ProfileRecord]:
    """Fixed flagship student + anchor alumni matching test_pipeline.py and Demo.jsx."""
    return [
        ProfileRecord(
            id="11111111-1111-4111-8111-111111111111",
            full_name="Léo Bernard",
            email="leo.bernard@student-cs.fr",
            linkedin_url="https://www.linkedin.com/in/leo-bernard-cs",
            promo_year=2026,
            current_role="Élève-ingénieur 2A",
            current_company="CentraleSupélec",
            sector="Étudiant",
            location="Gif-sur-Yvette",
            bio="Étudiant en 2A à CentraleSupélec, passionné de trail, d'énergie et d'IA générative.",
            experiences=[{"company": "Ekimetrics", "role": "Stagiaire Data", "start_date": "2025-06", "end_date": "2025-09", "period": "2025"}],
            education=[{"school": "CentraleSupélec", "degree": "Diplôme d'ingénieur", "start_year": 2024, "end_year": 2026}],
            associations=["BDS", "CentraleSupélec Runner", "Club Énergie", "Data Club"],
            passions=["trail", "IA générative"],
            is_student=True,
            has_imported_linkedin=True,
            enrichment_source="LINKEDIN_ARCHIVE",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("alice_martin"),
            full_name="Alice Martin",
            email="alice.martin@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/alice-martin-ml",
            promo_year=2020,
            current_role="Lead ML Engineer",
            current_company="Mistral AI",
            sector="Intelligence Artificielle",
            location="Paris",
            bio="Lead ML Engineer chez Mistral AI, ex-Doctolib. CentraleSupélec promo 2020.",
            experiences=[
                {"company": "Mistral AI", "role": "Lead ML Engineer", "start_date": "2023-05", "end_date": "Present", "period": "2023-Present"},
                {"company": "Doctolib", "role": "ML Engineer", "start_date": "2020-09", "end_date": "2023-04", "period": "2020-2023"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2017, "end_year": 2020}],
            associations=["Junior CentraleSupélec", "BDS"],
            passions=["course en montagne", "modèles de langage", "trail"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("thomas_leroy"),
            full_name="Thomas Leroy",
            email="thomas.leroy@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/thomas-leroy-ekimetrics",
            promo_year=2023,
            current_role="Data Scientist",
            current_company="Ekimetrics",
            sector="Intelligence Artificielle",
            location="Paris",
            bio="Data Scientist chez Ekimetrics, promo 2023.",
            experiences=[
                {"company": "Ekimetrics", "role": "Data Scientist", "start_date": "2023-09", "end_date": "Present", "period": "2023-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2020, "end_year": 2023}],
            associations=["BDS"],
            passions=["football", "finance"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("claire_moreau"),
            full_name="Claire Moreau",
            email="claire.moreau@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/claire-moreau-doctolib",
            promo_year=2019,
            current_role="Product Manager",
            current_company="Doctolib",
            sector="Santé / Tech",
            location="Paris",
            bio="Product Manager chez Doctolib (Santé). CentraleSupélec promo 2019.",
            experiences=[
                {"company": "Doctolib", "role": "Product Manager", "start_date": "2019-10", "end_date": "Present", "period": "2019-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2016, "end_year": 2019}],
            associations=["BDS"],
            passions=["natation", "santé numérique"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("julien_morel"),
            full_name="Julien Morel",
            email="julien.morel@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/julien-morel-engie",
            promo_year=2014,
            current_role="Responsable développement",
            current_company="Engie",
            sector="Énergie / Climat",
            location="La Défense",
            bio="Responsable développement solaire et renouvelables chez Engie. A déjà encadré deux césures.",
            experiences=[
                {"company": "Engie", "role": "Responsable développement", "start_date": "2018-01", "end_date": "Present", "period": "2018-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2011, "end_year": 2014}],
            associations=["Club Énergie"],
            passions=["énergie décarbonée", "randonnée alpine"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("hugo_marchand"),
            full_name="Hugo Marchand",
            email="hugo.marchand@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/hugo-marchand-edf",
            promo_year=2023,
            current_role="Ingénieur projets",
            current_company="EDF",
            sector="Énergie / Climat",
            location="Paris",
            bio="Ingénieur projets énergie chez EDF. Ancien du Club Énergie et Data Club.",
            experiences=[
                {"company": "EDF", "role": "Ingénieur projets", "start_date": "2023-09", "end_date": "Present", "period": "2023-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2020, "end_year": 2023}],
            associations=["Club Énergie", "Data Club"],
            passions=["énergie décarbonée"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("lea_benoit"),
            full_name="Léa Benoit",
            email="lea.benoit@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/lea-benoit-engie",
            promo_year=2020,
            current_role="Chargée de projet",
            current_company="Engie",
            sector="Énergie / Climat",
            location="Paris",
            bio="Chargée de projet chez Engie, ex-présidente du Club Énergie.",
            experiences=[
                {"company": "Engie", "role": "Chargée de projet", "start_date": "2020-09", "end_date": "Present", "period": "2020-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2017, "end_year": 2020}],
            associations=["Club Énergie", "Data Club"],
            passions=["énergie décarbonée", "voile"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("sofia_lambert"),
            full_name="Sofia Lambert",
            email="sofia.lambert@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/sofia-lambert-quant",
            promo_year=2015,
            current_role="Quantitative Analyst",
            current_company="BNP Paribas",
            sector="Finance",
            location="Paris",
            bio="Quantitative Analyst sur le desk dérivés chez BNP Paribas.",
            experiences=[
                {"company": "BNP Paribas", "role": "Quantitative Analyst", "start_date": "2016-03", "end_date": "Present", "period": "2016-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2012, "end_year": 2015}],
            associations=["Club Finance"],
            passions=["finance quantitative", "tennis"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("thomas_aubry"),
            full_name="Thomas Aubry",
            email="thomas.aubry@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/thomas-aubry-fintech",
            promo_year=2012,
            current_role="Cofondateur",
            current_company="Qonto",
            sector="Fintech",
            location="Paris",
            bio="Cofondateur fintech et mentor auprès de l'Incubateur CentraleSupélec.",
            experiences=[
                {"company": "Qonto", "role": "Cofondateur", "start_date": "2017-01", "end_date": "Present", "period": "2017-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2009, "end_year": 2012}],
            associations=["Incubateur"],
            passions=["startups", "fintech"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("sarah_cohen"),
            full_name="Sarah Cohen",
            email="sarah.cohen@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/sarah-cohen-vc",
            promo_year=2021,
            current_role="Investment Associate",
            current_company="Partech",
            sector="Venture Capital",
            location="Paris",
            bio="Investment Associate chez Partech (VC), ex Junior CentraleSupélec.",
            experiences=[
                {"company": "Partech", "role": "Investment Associate", "start_date": "2022-01", "end_date": "Present", "period": "2022-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2018, "end_year": 2021}],
            associations=["Junior CentraleSupélec"],
            passions=["startups", "tennis"],
            enrichment_source="BASE_DB",
            last_enriched_at=now,
        ),
        ProfileRecord(
            id=_uuid_from_seed("marc_petit"),
            full_name="Marc Petit",
            email="marc.petit@alumni-cs.fr",
            linkedin_url="https://www.linkedin.com/in/marc-petit-greentech",
            promo_year=2018,
            current_role="VP Engineering",
            current_company="GreenTech Energy",
            sector="Énergie / Climat",
            location="Lyon",
            bio=None,
            experiences=[
                {"company": "GreenTech Energy", "role": "VP Engineering", "start_date": "2021-01", "end_date": "Present", "period": "2021-Present"},
            ],
            education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": 2015, "end_year": 2018}],
            associations=[],
            passions=[],
            # Deliberately incomplete to showcase JIT enrichment
            enrichment_source="BASE_DB",
            last_enriched_at=None,
        ),
    ]


def generate_mock_dataset(
    *,
    count: int = 500,
    seed: int = 42,
    use_deterministic_embeddings: bool = True,
) -> tuple[list[ProfileRecord], list[EdgeRecord]]:
    """Generate anchor profiles + `count` realistic CentraleSupélec alumni + inferred edges."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    profiles: list[ProfileRecord] = _build_anchor_profiles(now)
    used_slugs: set[str] = {p.linkedin_url or "" for p in profiles}

    for idx in range(count):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        full_name = f"{first} {last}"
        slug_base = f"{first.lower()}-{last.lower()}-{idx + 1}"
        linkedin_url = f"https://www.linkedin.com/in/{slug_base}"
        while linkedin_url in used_slugs:
            slug_base += "x"
            linkedin_url = f"https://www.linkedin.com/in/{slug_base}"
        used_slugs.add(linkedin_url)

        promo_year = rng.randint(2008, 2025)
        sector, companies, roles = rng.choice(SECTORS_DATA)
        company = rng.choice(companies)
        role = rng.choice(roles)
        location = rng.choice(LOCATIONS)

        start_year = min(2025, max(promo_year, promo_year + rng.randint(0, 3)))
        exps = [
            {
                "company": company,
                "role": role,
                "start_date": f"{start_year}-09",
                "end_date": "Present",
                "period": f"{start_year}-Present",
            }
        ]
        if promo_year <= 2023 and rng.random() < 0.55:
            prev_sector = rng.choice(SECTORS_DATA)
            prev_comp = rng.choice(prev_sector[1])
            if prev_comp != company and start_year > promo_year:
                exps.append(
                    {
                        "company": prev_comp,
                        "role": rng.choice(prev_sector[2]),
                        "start_date": f"{promo_year}-09",
                        "end_date": f"{start_year}-06",
                        "period": f"{promo_year}-{start_year}",
                    }
                )

        # Keep ~13% of generated profiles incomplete to demonstrate JIT Tavily enrichment
        is_incomplete = (idx % 8 == 0)
        assos = [] if is_incomplete else rng.sample(ASSOCIATIONS, k=rng.randint(1, 2))
        passions = [] if is_incomplete else rng.sample(PASSIONS, k=rng.randint(1, 3))
        bio = (
            None
            if is_incomplete
            else f"{full_name}, {role} chez {company} ({sector}). CentraleSupélec promo {promo_year}."
        )

        profiles.append(
            ProfileRecord(
                id=_uuid_from_seed(f"alumni_{idx}_{slug_base}"),
                full_name=full_name,
                email=f"{slug_base}@alumni-cs.fr",
                linkedin_url=linkedin_url,
                promo_year=promo_year,
                current_role=role,
                current_company=company,
                sector=sector,
                location=location,
                bio=bio,
                experiences=exps,
                education=[{"school": "CentraleSupélec", "degree": "Ingénieur", "start_year": promo_year - 3, "end_year": promo_year}],
                associations=assos,
                passions=passions,
                is_student=False,
                has_imported_linkedin=False,
                enrichment_source="BASE_DB",
                last_enriched_at=None if is_incomplete else now,
            )
        )

    if use_deterministic_embeddings:
        for prof in profiles:
            prof.embedding = deterministic_text_embedding(prof.searchable_text(), dim=768)

    # Infer edges efficiently via inverted buckets (company, association, promo) instead of O(N^2) all-pairs
    edges_map: dict[tuple[str, str, str], EdgeRecord] = {}
    engine = GraphEngine()

    by_id = {p.id: p for p in profiles}
    leo = by_id["11111111-1111-4111-8111-111111111111"]
    thomas = by_id[_uuid_from_seed("thomas_leroy")]
    hugo = by_id[_uuid_from_seed("hugo_marchand")]
    lea = by_id[_uuid_from_seed("lea_benoit")]
    julien = by_id[_uuid_from_seed("julien_morel")]
    alice = by_id[_uuid_from_seed("alice_martin")]
    claire = by_id[_uuid_from_seed("claire_moreau")]

    # Explicit LinkedIn links for Léo Bernard + anchor edges
    explicit_pairs = [
        (leo, thomas, "EXPLICIT_LINKEDIN", 0.95, "Connexion LinkedIn directe (Stage Ekimetrics 2025)"),
        (leo, hugo, "EXPLICIT_LINKEDIN", 0.95, "Connexion LinkedIn directe (Club Énergie)"),
        (hugo, lea, "INFERRED_ASSO", 0.72, "Ancienne présidente du Club Énergie"),
        (lea, julien, "INFERRED_COMPANY", 0.75, "Chevauchement chez Engie (2020-2026)"),
        (thomas, claire, "INFERRED_ASSO", 0.65, "Même asso BDS à CentraleSupélec"),
        (claire, alice, "INFERRED_COMPANY", 0.72, "Chevauchement chez Doctolib (2020-2023)"),
    ]
    for u, v, etype, prob, reason in explicit_pairs:
        src, dst = (u.id, v.id) if u.id < v.id else (v.id, u.id)
        edges_map[(src, dst, etype)] = EdgeRecord(
            source_id=src,
            target_id=dst,
            edge_type=etype,
            probability=prob,
            reason=reason,
        )

    # Bucketed candidate pairing for fast, deterministic edge inference across 500+ profiles
    company_buckets: dict[str, list[ProfileRecord]] = {}
    asso_buckets: dict[str, list[ProfileRecord]] = {}
    promo_buckets: dict[int, list[ProfileRecord]] = {}

    for p in profiles:
        for exp in p.experiences:
            c_key = (exp.get("company") or "").strip().lower()
            if c_key:
                company_buckets.setdefault(c_key, []).append(p)
        for asso in p.associations:
            a_key = asso.strip().lower()
            if a_key:
                asso_buckets.setdefault(a_key, []).append(p)
        if p.promo_year:
            promo_buckets.setdefault(p.promo_year, []).append(p)

    candidate_pairs: dict[str, set[str]] = {p.id: set() for p in profiles}
    for bucket in list(company_buckets.values()) + list(asso_buckets.values()) + list(promo_buckets.values()):
        limited = bucket[:30]
        for i, p1 in enumerate(limited):
            for p2 in limited[i + 1 :]:
                candidate_pairs[p1.id].add(p2.id)

    for p1 in profiles:
        peers = [by_id[pid] for pid in candidate_pairs.get(p1.id, set())]
        for edge in engine.infer_edges_for_profile(p1, peers):
            key = (edge.source_id, edge.target_id, edge.edge_type)
            edges_map.setdefault(key, edge)

    return profiles, list(edges_map.values())


async def _seed_postgres(
    *,
    count: int,
    skip_embeddings: bool,
    apply_migrations: bool,
) -> None:
    settings = get_settings()
    db_url = settings.normalized_database_url
    if not db_url:
        raise RuntimeError("DATABASE_URL manquant dans .env ou les variables d'environnement.")

    engine = create_db_engine(db_url)
    if apply_migrations:
        await run_sql_migrations(engine)
    session_factory = create_session_factory(engine)
    repo = PostgresAlumniRepository(engine, session_factory)

    profiles, edges = generate_mock_dataset(
        count=count,
        seed=42,
        use_deterministic_embeddings=True,
    )

    if not skip_embeddings:
        llm = VertexLLMService(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            gemma_model=settings.gemma_model,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
        )
        batch_size = 50
        for start in range(0, len(profiles), batch_size):
            batch = profiles[start : start + batch_size]
            vectors = await llm.embed_texts([p.searchable_text() for p in batch])
            for p, vec in zip(batch, vectors):
                p.embedding = vec

    for prof in profiles:
        await repo.upsert_profile(prof)
    await repo.upsert_edges(edges)
    await engine.dispose()
    print(f"Seed Postgres terminé : {len(profiles)} profils et {len(edges)} arêtes insérés/mis à jour.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed realistic CentraleSupélec alumni profiles & graph edges.")
    parser.add_argument("--count", type=int, default=500, help="Nombre d'alumni générés (en plus des profils phares).")
    parser.add_argument("--skip-embeddings", action="store_true", help="Utilise les embeddings déterministes hors-ligne.")
    parser.add_argument("--dry-run", action="store_true", help="Génère le jeu de données sans écrire en base Postgres.")
    parser.add_argument("--apply-migrations", action="store_true", help="Exécute 001_init.sql avant l'insertion.")
    args = parser.parse_args()

    if args.dry_run:
        profiles, edges = generate_mock_dataset(
            count=args.count,
            seed=42,
            use_deterministic_embeddings=True,
        )
        incomplete = sum(1 for p in profiles if p.last_enriched_at is None)
        print(
            f"[DRY-RUN] {len(profiles)} profils générés (dont {incomplete} incomplets pour JIT Tavily), "
            f"{len(edges)} arêtes créées."
        )
        return

    asyncio.run(
        _seed_postgres(
            count=args.count,
            skip_embeddings=args.skip_embeddings,
            apply_migrations=args.apply_migrations,
        )
    )


if __name__ == "__main__":
    main()
