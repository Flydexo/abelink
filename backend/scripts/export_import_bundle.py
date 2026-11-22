"""Export and import Abelink profiles + edges as a single portable JSON bundle.

Usage:
    cd backend
    uv run python -m scripts.export_import_bundle export --output data/abelink_bundle.json
    uv run python -m scripts.export_import_bundle import --input data/abelink_bundle.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from app.config import get_settings
from app.db.enrichment_cache import EnrichmentCache
from app.db.repository import (
    EdgeRecord,
    InMemoryAlumniRepository,
    PostgresAlumniRepository,
    ProfileRecord,
)
from app.db.session import create_db_engine, create_session_factory
from app.main import _seed_demo_repository_sync
from app.services.graph_engine import GraphEngine


async def _open_repo() -> tuple[PostgresAlumniRepository | InMemoryAlumniRepository, object | None]:
    settings = get_settings()
    if settings.normalized_database_url and not settings.demo_mode:
        db_engine = create_db_engine(settings.normalized_database_url)
        session_factory = create_session_factory(db_engine)
        repo = PostgresAlumniRepository(db_engine, session_factory)
        return repo, db_engine
    cache = EnrichmentCache(settings.enrichment_cache_path) if settings.enrichment_cache_path else None
    repo = InMemoryAlumniRepository(enrichment_cache=cache)
    _seed_demo_repository_sync(repo, settings)
    if cache is not None:
        repo.apply_cached_enrichment(cache)
    return repo, None


async def export_bundle(output_path: Path) -> tuple[int, int]:
    """Export all profiles and edges from the configured DB into a JSON bundle."""
    repo, db_engine = await _open_repo()
    try:
        profiles = await repo.list_profiles()
        edges = await repo.list_edges()
    finally:
        if db_engine is not None:
            await db_engine.dispose()

    payload = {
        "version": 1,
        "profiles": [asdict(p) for p in profiles],
        "edges": [asdict(e) for e in edges],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return len(profiles), len(edges)


async def import_bundle(input_path: Path) -> tuple[int, int, int]:
    """Import profiles and edges from a JSON bundle, infer missing edges, and build the graph cache."""
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    profiles = [ProfileRecord(**p) for p in payload.get("profiles", [])]
    explicit_edges = [EdgeRecord(**e) for e in payload.get("edges", [])]

    repo, db_engine = await _open_repo()
    try:
        for profile in profiles:
            await repo.upsert_profile(profile)
        if explicit_edges:
            await repo.upsert_edges(explicit_edges)

        engine = GraphEngine()
        inferred_edges: list[EdgeRecord] = []
        for idx, profile in enumerate(profiles):
            inferred_edges.extend(engine.infer_edges_for_profile(profile, profiles[idx + 1 :]))
        if inferred_edges:
            await repo.upsert_edges(inferred_edges)

        all_edges = await repo.list_edges()
        engine.reload(profiles, all_edges)
    finally:
        if db_engine is not None:
            await db_engine.dispose()

    return len(profiles), len(explicit_edges), len(inferred_edges)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or import Abelink JSON bundle.")
    sub = parser.add_subparsers(dest="command", required=True)

    exp_p = sub.add_parser("export", help="Export DB profiles and edges to JSON.")
    exp_p.add_argument("--output", type=Path, default=Path("data/abelink_bundle.json"))

    imp_p = sub.add_parser("import", help="Import JSON bundle into DB and rebuild graph cache.")
    imp_p.add_argument("--input", type=Path, default=Path("data/abelink_bundle.json"))

    args = parser.parse_args()
    if args.command == "export":
        n_prof, n_edges = asyncio.run(export_bundle(args.output))
        print(f"Exported {n_prof} profiles and {n_edges} edges to {args.output}")
    elif args.command == "import":
        n_prof, n_exp, n_inf = asyncio.run(import_bundle(args.input))
        print(f"Imported {n_prof} profiles, {n_exp} bundle edges, and {n_inf} inferred edges from {args.input}")


if __name__ == "__main__":
    main()
