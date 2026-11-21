"""Live integration tests against real Google Vertex AI (Gemma 4 + gemini-embedding-2) and Tavily."""

import os

import pytest

from app.db.repository import EdgeRecord, InMemoryAlumniRepository, ProfileRecord
from app.schemas.search import ActionPlanRequest
from app.services.enrichment import EnrichmentService, TavilyWebSearchClient
from app.services.graph_engine import GraphEngine
from app.services.llm import VertexLLMService
from app.services.search_agent import SearchAgentService


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_vertex_and_tavily_pipeline():
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        pytest.skip("TAVILY_API_KEY non défini pour les tests live.")

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "751082713943")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    gemma_model = os.getenv("GEMMA_MODEL", "google/gemma-4-26b-a4b-it-maas")
    embedding_model = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")

    llm = VertexLLMService(
        project=project,
        location=location,
        gemma_model=gemma_model,
        embedding_model=embedding_model,
        embedding_dim=768,
    )
    tavily = TavilyWebSearchClient(api_key=tavily_key)
    repo = InMemoryAlumniRepository()
    graph = GraphEngine()

    student = ProfileRecord(
        id="student_leo",
        full_name="Léo Bernard",
        promo_year=2026,
        associations=["BDS"],
        passions=["trail", "IA générative"],
        is_student=True,
        has_imported_linkedin=True,
    )
    target = ProfileRecord(
        id="arthur_mensch",
        full_name="Arthur Mensch",
        current_role="CEO",
        current_company="Mistral AI",
        sector="Intelligence Artificielle",
        last_enriched_at=None,
    )
    vectors = await llm.embed_texts([student.searchable_text(), target.searchable_text()])
    assert len(vectors[0]) == 768
    student.embedding, target.embedding = vectors[0], vectors[1]

    await repo.upsert_profile(student)
    await repo.upsert_profile(target)
    await repo.upsert_edges(
        [EdgeRecord(student.id, target.id, "INFERRED_SCHOOL", 0.35, "Réseau CentraleSupélec / Polytechnique")]
    )
    graph.reload(await repo.list_profiles(), await repo.list_edges())

    enrichment = EnrichmentService(repo, llm, graph, web_client=tavily)
    agent = SearchAgentService(repo, llm, enrichment, graph)

    res = await agent.run_action_plan(
        student.id,
        ActionPlanRequest(query="Je cherche un alumni fondateur dans l'IA générative chez Mistral AI", limit=1),
    )
    assert len(res.solutions) == 1
    assert res.solutions[0].target.full_name == "Arthur Mensch"
    assert res.solutions[0].outreach_message
