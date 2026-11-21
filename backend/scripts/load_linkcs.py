"""CLI script to validate, inspect, or load a LinkCS dataset (.json or .csv) into Postgres."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import networkx as nx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.db.repository import PostgresAlumniRepository
from app.db.session import create_db_engine, create_session_factory, run_sql_migrations
from app.services.graph_engine import GraphEngine
from app.services.linkcs_loader import load_linkcs_dataset
from app.services.llm import VertexLLMService


def _print_dry_run_stats(input_path: str, include_demo_student: bool, max_group_size: int) -> None:
    profiles, edges = load_linkcs_dataset(
        input_path,
        include_demo_student=include_demo_student,
        compute_embeddings=False,
        max_group_size=max_group_size,
    )
    engine = GraphEngine()
    engine.reload(profiles, edges)
    stats = engine.stats()

    unique_assos = {a for p in profiles for a in p.associations}
    with_assos = sum(1 for p in profiles if p.associations)
    with_bio = sum(1 for p in profiles if p.bio)

    g = nx.Graph()
    for p in profiles:
        g.add_node(p.id)
    for e in edges:
        g.add_edge(e.source_id, e.target_id)
    components = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    largest_cc = components[0] if components else 0

    print(
        f"[DRY-RUN LinkCS] {len(profiles)} profils ({with_assos} avec assos/clubs, {with_bio} avec bio), "
        f"{len(unique_assos)} associations/clubs distincts, {stats['edges']} arêtes uniques "
        f"(plus grande composante connexe : {largest_cc} nœuds, {len(components)} composantes)."
    )

    if include_demo_student:
        demo_id = "11111111-1111-4111-8111-111111111111"
        reachable = sum(1 for p in profiles if p.id != demo_id and engine.find_connection_paths(demo_id, p.id, max_hops=4, k_paths=1))
        print(f"Depuis l'étudiant démo, {reachable} profils sont joignables en <= 4 sauts.")


async def _load_into_postgres(
    *,
    input_path: str,
    include_demo_student: bool,
    apply_migrations: bool,
    skip_embeddings: bool,
    max_group_size: int,
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

    profiles, edges = load_linkcs_dataset(
        input_path,
        include_demo_student=include_demo_student,
        compute_embeddings=skip_embeddings,
        embedding_dim=settings.embedding_dim,
        max_group_size=max_group_size,
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
    print(f"Import LinkCS Postgres terminé : {len(profiles)} profils et {len(edges)} arêtes.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Charger un export LinkCS (.json/.csv) dans Abelink.")
    parser.add_argument("--input", required=True, help="Chemin vers linkcs_amis.json ou linkcs_amis.csv.")
    parser.add_argument("--dry-run", action="store_true", help="Analyse le dataset sans écrire en base.")
    parser.add_argument("--apply-migrations", action="store_true", help="Exécute 001_init.sql avant l'import.")
    parser.add_argument("--skip-embeddings", action="store_true", help="Utilise les embeddings déterministes hors-ligne.")
    parser.add_argument("--no-demo-student", action="store_true", help="N'ajoute pas l'étudiant démo Léo Bernard.")
    parser.add_argument("--max-group-size", type=int, default=80, help="Taille max d'une asso pour inférer des arêtes.")
    args = parser.parse_args()

    include_demo = not args.no_demo_student
    if args.dry_run:
        _print_dry_run_stats(args.input, include_demo, args.max_group_size)
        return

    asyncio.run(
        _load_into_postgres(
            input_path=args.input,
            include_demo_student=include_demo,
            apply_migrations=args.apply_migrations,
            skip_embeddings=args.skip_embeddings,
            max_group_size=args.max_group_size,
        )
    )


if __name__ == "__main__":
    main()
