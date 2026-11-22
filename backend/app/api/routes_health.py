"""Healthcheck endpoint."""

from fastapi import APIRouter, Request

from app.services.enrichment import NullWebSearchClient, TavilyWebSearchClient
from app.services.llm import VertexLLMService
from app.services.web_scraper import FreeFirstWebSearchClient

router = APIRouter(tags=["health"])


def _resolve_search_provider(web_client: object) -> str:
    if isinstance(web_client, FreeFirstWebSearchClient):
        return web_client.provider_label
    if isinstance(web_client, NullWebSearchClient):
        return "disabled"
    if isinstance(web_client, TavilyWebSearchClient):
        return "tavily"
    return "custom"


@router.get(
    "/health",
    summary="Vérifier l'état du backend, de la base de données et du graphe NetworkX",
    operation_id="health_check",
)
async def health(request: Request) -> dict:
    container = request.app.state.container
    db_status = await container.repository.health_check()
    graph_stats = container.graph_engine.stats()
    enriched_profiles = await container.repository.count_enriched_profiles()
    return {
        "status": "ok" if db_status.get("ok") else "degraded",
        "database": db_status,
        "graph": graph_stats,
        "demo_mode": container.settings.demo_mode,
        "public_access": container.settings.allow_public_access,
        "llm_backend": "vertex" if isinstance(container.llm_service, VertexLLMService) else "deterministic",
        "tavily_enabled": container.enrichment_service.is_web_enabled(),
        "search_provider": _resolve_search_provider(container.enrichment_service.web_client),
        "enriched_profiles": enriched_profiles,
    }
