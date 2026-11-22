"""FastAPI entrypoint with lifespan, CORS, OpenAPI metadata, REST routes, and mounted FastMCP server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.routing import Route

from app.api.routes_bundle import BundleUploads, router as bundle_router
from app.api.routes_chat import router as chat_router
from app.api.routes_health import router as health_router
from app.api.routes_import import router as import_router
from app.api.routes_linkcs import router as linkcs_router
from app.api.routes_profiles import router as profiles_router
from app.api.routes_search import router as search_router
from app.api.routes_tokens import router as tokens_router
from app.auth import MCPBearerMiddleware, PUBLIC_VISITOR_ID
from app.config import Settings, get_settings
from app.db.enrichment_cache import EnrichmentCache
from app.db.repository import AbstractAlumniRepository, InMemoryAlumniRepository, PostgresAlumniRepository, ProfileRecord
from app.db.session import create_db_engine, create_session_factory, run_sql_migrations
from app.services.chat_agent import ChatAgentService
from app.services.enrichment import (
    EnrichmentService,
    NullWebSearchClient,
    TavilyWebSearchClient,
    WebSearchClientProtocol,
)
from app.services.graph_engine import GraphEngine
from app.services.llm import DeterministicLLMService, LLMServiceProtocol, VertexLLMService
from app.services.search_agent import SearchAgentService
from app.services.web_scraper import FreeFirstWebSearchClient


@dataclass
class AppContainer:
    settings: Settings
    repository: AbstractAlumniRepository
    graph_engine: GraphEngine
    llm_service: LLMServiceProtocol
    enrichment_service: EnrichmentService
    search_agent: SearchAgentService
    chat_agent: ChatAgentService
    db_engine: Optional[AsyncEngine] = None


def _build_default_llm(settings: Settings) -> LLMServiceProtocol:
    if settings.demo_mode or not settings.google_cloud_project:
        return DeterministicLLMService(embedding_dim=settings.embedding_dim)
    try:
        return VertexLLMService(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            gemma_model=settings.gemma_model,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
        )
    except Exception:
        return DeterministicLLMService(embedding_dim=settings.embedding_dim)


def _build_default_web_client(settings: Settings) -> WebSearchClientProtocol:
    if settings.demo_mode:
        return NullWebSearchClient()
    tavily_fallback: Optional[WebSearchClientProtocol] = (
        TavilyWebSearchClient(api_key=settings.tavily_api_key)
        if settings.tavily_api_key
        else None
    )
    if settings.prefer_free_search:
        return FreeFirstWebSearchClient(tavily_fallback=tavily_fallback)
    if tavily_fallback is not None:
        return tavily_fallback
    return NullWebSearchClient()


def _seed_demo_repository_sync(
    repo: InMemoryAlumniRepository,
    settings: Settings,
) -> None:
    """Populate an in-memory repository from LINKCS_DATA_PATH if configured, else mock alumni."""
    if settings.linkcs_data_path:
        from app.services.linkcs_loader import load_linkcs_dataset

        profiles, edges = load_linkcs_dataset(
            settings.linkcs_data_path,
            include_demo_student=True,
            compute_embeddings=True,
            embedding_dim=settings.embedding_dim,
        )
    else:
        from scripts.seed_mock_alumni import generate_mock_dataset

        profiles, edges = generate_mock_dataset(count=60, seed=42, use_deterministic_embeddings=True)

    for prof in profiles:
        repo.profiles[prof.id] = prof
    for edge in edges:
        repo.edges[(edge.source_id, edge.target_id, edge.edge_type)] = edge


def create_app(
    *,
    settings: Optional[Settings] = None,
    repository: Optional[AbstractAlumniRepository] = None,
    llm_service: Optional[LLMServiceProtocol] = None,
    web_client: Optional[WebSearchClientProtocol] = None,
    graph_engine: Optional[GraphEngine] = None,
) -> FastAPI:
    cfg = settings or get_settings()

    # Deferred container populated in lifespan so /mcp and REST routes share the exact same live services
    holder: dict[str, AppContainer] = {}

    def get_container() -> AppContainer:
        return holder["container"]

    from app.mcp_server import create_mcp_server

    mcp = create_mcp_server(get_container)
    mcp_starlette_app = mcp.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    mcp_asgi_app = MCPBearerMiddleware(mcp_starlette_app)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_engine: Optional[AsyncEngine] = None
        repo = repository
        if repo is None:
            if cfg.normalized_database_url and not cfg.demo_mode:
                db_engine = create_db_engine(cfg.normalized_database_url)
                await run_sql_migrations(db_engine)
                session_factory = create_session_factory(db_engine)
                repo = PostgresAlumniRepository(db_engine, session_factory)
            else:
                cache: Optional[EnrichmentCache] = None
                if cfg.enrichment_cache_path and (cfg.linkcs_data_path or not cfg.demo_mode):
                    try:
                        cache = EnrichmentCache(cfg.enrichment_cache_path)
                    except OSError:
                        if not cfg.demo_mode:
                            raise
                        cache = None
                in_mem = InMemoryAlumniRepository(enrichment_cache=cache)
                _seed_demo_repository_sync(in_mem, cfg)
                if cache is not None:
                    in_mem.apply_cached_enrichment(cache)
                repo = in_mem

        if cfg.allow_public_access and await repo.get_profile(PUBLIC_VISITOR_ID) is None:
            await repo.upsert_profile(ProfileRecord(
                id=PUBLIC_VISITOR_ID, full_name="Visiteur public", is_student=True,
                enrichment_source="PUBLIC_VISITOR",
            ))

        llm = llm_service or _build_default_llm(cfg)
        web = web_client or _build_default_web_client(cfg)
        engine = graph_engine or GraphEngine()

        await engine.reload_from_repository(repo)

        enrichment = EnrichmentService(
            repository=repo,
            llm_service=llm,
            graph_engine=engine,
            web_client=web,
        )
        search_agent = SearchAgentService(
            repository=repo,
            llm_service=llm,
            enrichment_service=enrichment,
            graph_engine=engine,
        )
        chat_agent = ChatAgentService(
            repository=repo,
            llm_service=llm,
            enrichment_service=enrichment,
            graph_engine=engine,
            search_agent=search_agent,
        )

        container = AppContainer(
            settings=cfg,
            repository=repo,
            graph_engine=engine,
            llm_service=llm,
            enrichment_service=enrichment,
            search_agent=search_agent,
            chat_agent=chat_agent,
            db_engine=db_engine,
        )
        holder["container"] = container
        app.state.container = container

        app.state.bundle_uploads = BundleUploads()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await app.state.bundle_uploads.close()

        if db_engine is not None:
            await db_engine.dispose()

    app = FastAPI(
        title="Abelink Alumni Graph API",
        version="0.1.0",
        description=(
            "API du moteur de recherche relationnel alumni Abelink (CentraleSupélec). "
            "Pour ChatGPT Actions, appeler en priorité l'opération `recommend_alumni_action_plan` "
            "(POST /api/v1/search/action-plan) qui exécute toute la chaîne en une seule requête."
        ),
        servers=[{"url": cfg.public_api_url, "description": "Serveur principal Abelink"}],
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(import_router)
    app.include_router(linkcs_router)
    app.include_router(bundle_router)
    app.include_router(search_router)
    app.include_router(chat_router)
    app.include_router(profiles_router)
    if not cfg.allow_public_access:
        app.include_router(tokens_router)

    # Route both /mcp and /mcp/ directly to avoid 307 redirects on POST Streamable HTTP
    app.router.routes.append(Route("/mcp", endpoint=mcp_asgi_app, include_in_schema=False))
    app.router.routes.append(Route("/mcp/", endpoint=mcp_asgi_app, include_in_schema=False))
    app.state.mcp = mcp
    return app


app = create_app()
