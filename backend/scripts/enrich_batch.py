"""Resumable CLI script to batch-enrich LinkCS alumni profiles into local SQLite cache."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.db.enrichment_cache import EnrichmentCache
from app.db.repository import InMemoryAlumniRepository
from app.services.enrichment import EnrichmentService, TavilyWebSearchClient, WebSearchClientProtocol
from app.services.graph_engine import GraphEngine
from app.services.linkcs_loader import load_linkcs_dataset
from app.services.llm import DeterministicLLMService, LLMServiceProtocol, VertexLLMService
from app.services.web_scraper import FreeFirstWebSearchClient


def _build_batch_llm() -> LLMServiceProtocol:
    settings = get_settings()
    if settings.google_cloud_project:
        try:
            return VertexLLMService(
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
                gemma_model=settings.gemma_model,
                embedding_model=settings.embedding_model,
                embedding_dim=settings.embedding_dim,
            )
        except Exception:
            pass
    return DeterministicLLMService(embedding_dim=settings.embedding_dim)


async def run_batch_enrichment(
    *,
    input_path: Optional[str] = None,
    limit: int = 200,
    cache_path: Optional[str] = None,
    concurrency: int = 3,
    no_tavily_fallback: bool = False,
    tavily_only: bool = False,
    llm_service: Optional[LLMServiceProtocol] = None,
    web_client: Optional[WebSearchClientProtocol] = None,
) -> dict[str, Any]:
    """Load LinkCS profiles, apply cache, enrich top uncached profiles by association count, and return aggregate stats."""
    t0 = time.monotonic()
    settings = get_settings()
    resolved_input = input_path or settings.linkcs_data_path
    if not resolved_input:
        raise ValueError("Chemin dataset requis via --input ou LINKCS_DATA_PATH.")

    resolved_cache_path = cache_path or settings.enrichment_cache_path
    cache = EnrichmentCache(resolved_cache_path)

    profiles, edges = load_linkcs_dataset(
        resolved_input,
        include_demo_student=False,
        compute_embeddings=False,
        embedding_dim=settings.embedding_dim,
    )
    repo = InMemoryAlumniRepository(enrichment_cache=cache)
    for prof in profiles:
        repo.profiles[prof.id] = prof
    for edge in edges:
        repo.edges[(edge.source_id, edge.target_id, edge.edge_type)] = edge

    repo.apply_cached_enrichment(cache)

    engine = GraphEngine()
    engine.reload(await repo.list_profiles(), await repo.list_edges())

    uncached = [p for p in repo.profiles.values() if EnrichmentService.needs_enrichment(p)]
    uncached.sort(key=lambda p: (-len(p.associations), p.id))
    targets = uncached[: max(0, limit)]

    llm = llm_service or _build_batch_llm()
    if web_client is None:
        if tavily_only:
            if not settings.tavily_api_key:
                raise ValueError("TAVILY_API_KEY requis avec --tavily-only.")
            search_client: WebSearchClientProtocol = TavilyWebSearchClient(api_key=settings.tavily_api_key)
        else:
            tavily_fb: Optional[WebSearchClientProtocol] = (
                TavilyWebSearchClient(api_key=settings.tavily_api_key)
                if (not no_tavily_fallback and settings.tavily_api_key)
                else None
            )
            search_client = FreeFirstWebSearchClient(
                tavily_fallback=tavily_fb,
                disable_tavily_fallback=no_tavily_fallback,
            )
    else:
        search_client = web_client

    enrichment = EnrichmentService(
        repository=repo,
        llm_service=llm,
        graph_engine=engine,
        web_client=search_client,
    )

    processed = 0
    enriched_count = 0
    chunk_size = 20
    for start in range(0, len(targets), chunk_size):
        chunk = targets[start : start + chunk_size]
        updated = await enrichment.enrich_candidates(
            chunk,
            max_concurrency=max(1, concurrency),
            max_profiles=len(chunk),
            timeout_seconds=18.0,
        )
        processed += len(chunk)
        enriched_count += len(updated)

    elapsed_s = round(time.monotonic() - t0, 2)
    stats = {
        "processed": processed,
        "enriched_count": enriched_count,
        "free_hits": int(getattr(search_client, "free_hits", 0)),
        "tavily_fallbacks": int(getattr(search_client, "tavily_fallbacks", 0)),
        "cached_total": cache.count_enriched(),
        "elapsed_s": elapsed_s,
    }
    return stats


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Enrichissement batch résumable des profils LinkCS vers le cache SQLite local."
    )
    parser.add_argument(
        "--input",
        default=settings.linkcs_data_path,
        help="Chemin vers linkcs_amis.json ou linkcs_amis.csv (défaut: LINKCS_DATA_PATH).",
    )
    parser.add_argument("--limit", type=int, default=200, help="Nombre max de profils non enrichis à traiter.")
    parser.add_argument(
        "--cache-path",
        default=settings.enrichment_cache_path,
        help="Chemin du cache SQLite local (hors Git).",
    )
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrence max d'enrichissement.")
    parser.add_argument(
        "--no-tavily-fallback",
        action="store_true",
        help="Désactive le fallback Tavily et utilise uniquement la recherche gratuite.",
    )
    parser.add_argument(
        "--tavily-only",
        action="store_true",
        help="Utilise directement Tavily (avec include_images) sans passer par DuckDuckGo.",
    )
    args = parser.parse_args()

    stats = asyncio.run(
        run_batch_enrichment(
            input_path=args.input,
            limit=args.limit,
            cache_path=args.cache_path,
            concurrency=args.concurrency,
            no_tavily_fallback=args.no_tavily_fallback,
            tavily_only=args.tavily_only,
        )
    )
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
