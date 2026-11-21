"""Unit tests for the 4-step deterministic search pipeline, JIT enrichment, scoring, and anti-hallucination."""

import re

import pytest

from app.schemas.search import ActionPlanRequest
from app.services.enrichment import EnrichmentService
from app.services.graph_engine import GraphEngine
from app.services.llm import DeterministicLLMService
from app.services.search_agent import SearchAgentService
from tests.conftest import SpyTavilyClient, build_test_repository


@pytest.mark.asyncio
async def test_phase2_keeps_sparse_profiles_and_phase3_enriches_once_and_caches():
    repo = build_test_repository()
    llm = DeterministicLLMService(embedding_dim=768)
    tavily = SpyTavilyClient()
    graph = GraphEngine()
    graph.reload(await repo.list_profiles(), await repo.list_edges())

    enrichment = EnrichmentService(repo, llm, graph, web_client=tavily)
    agent = SearchAgentService(repo, llm, enrichment, graph)

    # First search for energy/trail: Marc Petit starts with empty passions/associations and last_enriched_at=None
    req = ActionPlanRequest(
        query="Je cherche un alumni dans l'énergie qui aime le trail",
        limit=5,
    )
    res1 = await agent.run_action_plan("11111111-1111-4111-8111-111111111111", req)

    # Marc Petit MUST have been selected in Phase 2 (not filtered out!) and enriched via Tavily
    assert res1.candidates_enriched == 1
    assert len(tavily.calls) == 1
    assert "Marc Petit" in tavily.calls[0]
    # Benoît Garnier has has_imported_linkedin=True -> must NEVER trigger Tavily even if last_enriched_at is None
    assert all("Benoît Garnier" not in q for q in tavily.calls)

    marc = await repo.get_profile("66666666-6666-4666-8666-666666666666")
    assert marc is not None
    assert marc.last_enriched_at is not None
    assert marc.enrichment_source == "WEB_TAVILY"
    assert "Club Énergie" in marc.associations
    assert "trail" in marc.passions
    # Enrichment must have inferred Club Énergie edge between Léo Bernard and Marc Petit
    paths_to_marc = graph.find_connection_paths("11111111-1111-4111-8111-111111111111", marc.id)
    assert len(paths_to_marc) >= 1

    # Second search must hit cache and NOT re-call Tavily
    res2 = await agent.run_action_plan("11111111-1111-4111-8111-111111111111", req)
    assert res2.candidates_enriched == 0
    assert len(tavily.calls) == 1


@pytest.mark.asyncio
async def test_composite_scoring_pagination_and_anti_hallucination():
    repo = build_test_repository()
    llm = DeterministicLLMService(embedding_dim=768)
    tavily = SpyTavilyClient()
    graph = GraphEngine()
    graph.reload(await repo.list_profiles(), await repo.list_edges())

    enrichment = EnrichmentService(repo, llm, graph, web_client=tavily)
    agent = SearchAgentService(repo, llm, enrichment, graph)

    # Query targeting Alice Martin (Mistral AI + trail)
    res_page1 = await agent.run_action_plan(
        "11111111-1111-4111-8111-111111111111",
        ActionPlanRequest(
            query="Je cherche un alumni dans l'IA générative chez Mistral AI qui fait du trail",
            limit=2,
            offset=0,
        ),
    )
    assert len(res_page1.solutions) == 2
    top = res_page1.solutions[0]
    assert top.target.full_name == "Alice Martin"
    assert top.primary_path is not None
    # Optimal Dijkstra path passes through Thomas Leroy -> Claire Moreau -> Alice Martin (0.95*0.55*0.72)
    assert [h.to_name for h in top.primary_path.hops] == ["Thomas Leroy", "Claire Moreau", "Alice Martin"]
    assert top.first_hop is not None and top.first_hop.full_name == "Thomas Leroy"

    # Verify composite formula 0.50*rel + 0.35*prob + 0.15*common
    sb = top.score_breakdown
    expected = round(0.50 * sb.profile_relevance + 0.35 * sb.path_probability + 0.15 * sb.common_points_score, 4)
    assert abs(sb.total_score - expected) < 1e-3

    # Anti-hallucination: Thomas Leroy does NOT have "trail" as a passion -> must NOT attribute trail to Thomas
    msg = top.outreach_message
    assert "Thomas" in msg
    assert "trail" not in msg.lower()
    assert not re.search(r"\[[^\]]+\]", msg)
    assert len(top.action_plan) == 3

    # Pagination offset
    res_page2 = await agent.run_action_plan(
        "11111111-1111-4111-8111-111111111111",
        ActionPlanRequest(
            query="Je cherche un alumni dans l'IA générative chez Mistral AI qui fait du trail",
            limit=2,
            offset=2,
        ),
    )
    page1_ids = {s.target.id for s in res_page1.solutions}
    page2_ids = {s.target.id for s in res_page2.solutions}
    assert page1_ids.isdisjoint(page2_ids)


@pytest.mark.asyncio
async def test_web_discovery_finds_sparse_linkcs_alumni_and_ranks_above_unrelated_hop():
    from app.db.repository import EdgeRecord, InMemoryAlumniRepository, ProfileRecord
    from app.services.llm import deterministic_text_embedding

    repo = InMemoryAlumniRepository()
    student = ProfileRecord(
        id="leo",
        full_name="Léo Bernard",
        promo_year=2026,
        associations=["BDS"],
        is_student=True,
        has_imported_linkedin=True,
    )
    # Unrelated 1-hop neighbor (high graph probability 0.65, zero career match)
    unrelated_hop = ProfileRecord(
        id="hop_unrelated",
        full_name="Paul Exemple",
        promo_year=2020,
        associations=["BDS"],
        bio="Passionné de cuisine et théâtre.",
        enrichment_source="LINKCS_DB",
        last_enriched_at=None,
    )
    # Sparse LinkCS profile with NO current_company/sector yet, connected 2 hops away
    target_linkcs = ProfileRecord(
        id="camille_mistral",
        full_name="Camille Mistral",
        promo_year=2020,
        associations=["Club Tech"],
        bio="Club Tech.",
        enrichment_source="LINKCS_DB",
        last_enriched_at=None,
    )
    for p in (student, unrelated_hop, target_linkcs):
        p.embedding = deterministic_text_embedding(p.searchable_text(), dim=768)
        await repo.upsert_profile(p)

    await repo.upsert_edges(
        [
            EdgeRecord("leo", "hop_unrelated", "INFERRED_ASSO", 0.65, "Même asso BDS"),
            EdgeRecord("hop_unrelated", "camille_mistral", "INFERRED_ASSO", 0.60, "Même promo"),
        ]
    )

    class DiscoveryTavily:
        async def search(self, query: str, max_results: int = 4) -> list[dict]:
            if "Camille Mistral" in query:
                return [
                    {
                        "title": "Camille Mistral - Mistral AI",
                        "url": "https://fr.linkedin.com/in/camille-mistral",
                        "content": "Camille Mistral travaille comme Lead ML Engineer chez Mistral AI (2023-Present).",
                    }
                ]
            if "Paul Exemple" in query:
                return [
                    {
                        "title": "Paul Exemple - Bistrot Paris",
                        "url": "https://fr.linkedin.com/in/paul-exemple",
                        "content": "Paul Exemple travaille comme Chef chez Bistrot Paris (2021-Present).",
                    }
                ]
            if "Mistral AI" in query:
                return [
                    {
                        "title": "Camille Mistral - Lead ML Engineer - Mistral AI",
                        "url": "https://fr.linkedin.com/in/camille-mistral",
                        "content": "Camille Mistral est Lead ML Engineer chez Mistral AI après CentraleSupélec.",
                    }
                ]
            return []

    graph = GraphEngine()
    graph.reload(await repo.list_profiles(), await repo.list_edges())
    llm = DeterministicLLMService(embedding_dim=768)
    enrichment = EnrichmentService(repo, llm, graph, web_client=DiscoveryTavily())
    agent = SearchAgentService(repo, llm, enrichment, graph)

    res = await agent.run_action_plan(
        "leo",
        ActionPlanRequest(query="Je cherche un alumni chez Mistral AI", limit=3),
    )
    assert len(res.solutions) >= 1
    top = res.solutions[0]
    assert top.target.full_name == "Camille Mistral"
    assert top.target.current_company == "Mistral AI"
    assert top.primary_path is not None and top.primary_path.hop_count == 2


@pytest.mark.asyncio
async def test_vertex_calibration_gating_slug_discovery_and_honest_fallback():
    from app.db.repository import EdgeRecord, InMemoryAlumniRepository, ProfileRecord, SearchCandidate
    from app.schemas.search import ParsedQuery
    from app.services.llm import deterministic_text_embedding
    from app.services.search_agent import _compute_profile_relevance

    # 1. Vertex cosine cone (0.80) on a non-matching enriched company must be gated <= 0.20
    q_vec = [1.0] * 768
    non_match = ProfileRecord(
        id="poly",
        full_name="Marc Polycea",
        current_company="Polycea",
        current_role="Consultant",
        sector="Digital",
        embedding=[1.0] * 768,  # raw cosine = 1.0, yet misses BNP Paribas!
        embedding_space="vertex",
    )
    rel = _compute_profile_relevance(
        SearchCandidate(profile=non_match, hybrid_score=0.5, semantic_score=0.8),
        q_vec,
        q_vec,
        ParsedQuery(target_companies=["BNP Paribas"], target_roles=["quant"], target_sector="Finance"),
        raw_query="Je cherche un quant chez BNP Paribas",
    )
    assert rel <= 0.20

    # 2. LinkedIn /in/<slug> discovery match + honest fallback summary when zero strong matches exist
    repo = InMemoryAlumniRepository()
    student = ProfileRecord(
        id="leo",
        full_name="Léo Bernard",
        promo_year=2026,
        associations=["BDS"],
        is_student=True,
        has_imported_linkedin=True,
    )
    slug_match = ProfileRecord(
        id="camille_slug",
        full_name="Camille Durand",
        promo_year=2020,
        associations=["BDS"],
        enrichment_source="LINKCS_DB",
    )
    for p in (student, slug_match):
        p.embedding = deterministic_text_embedding(p.searchable_text(), dim=768)
        await repo.upsert_profile(p)
    await repo.upsert_edges([EdgeRecord("leo", "camille_slug", "INFERRED_ASSO", 0.65, "BDS")])

    class SlugTavily:
        async def search(self, query: str, max_results: int = 4, include_domains=None):
            if include_domains == ["linkedin.com"]:
                return [
                    {
                        "title": "Profil LinkedIn",
                        "url": "https://fr.linkedin.com/in/camille-durand-98a1b21",
                        "content": "CentraleSupélec.",
                    }
                ]
            return []

    graph = GraphEngine()
    graph.reload(await repo.list_profiles(), await repo.list_edges())
    llm = DeterministicLLMService(embedding_dim=768)
    enrichment = EnrichmentService(repo, llm, graph, web_client=SlugTavily())
    discovered = await enrichment.discover_candidates_via_web(
        ParsedQuery(target_companies=["BNP Paribas"]),
        "Je cherche quelqu'un chez BNP Paribas",
        await repo.list_profiles(),
    )
    assert [d.id for d in discovered] == ["camille_slug"]

    agent = SearchAgentService(repo, llm, enrichment, graph)
    res = await agent.run_action_plan(
        "leo",
        ActionPlanRequest(query="Je cherche un alumni chez BNP Paribas", limit=3),
    )
    assert "Aucun match exact trouvé" in res.summary
    assert res.solutions[0].score_breakdown.profile_relevance <= 0.20
