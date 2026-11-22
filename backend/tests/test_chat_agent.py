"""Integration & unit tests for the iterative tool-calling Agent Chat API and SSE stream."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

from google.genai import types

from app.db.repository import ProfileRecord
from app.main import create_app
from app.services.enrichment import EnrichmentService
from app.services.graph_engine import GraphEngine
from app.services.llm import DeterministicLLMService, VertexLLMService, deterministic_text_embedding
from app.services.search_agent import SearchAgentService
from app.services.chat_agent import ChatAgentService
from app.schemas.chat import ChatMessage
from tests.conftest import SpyTavilyClient, build_test_repository


def _parse_sse_frames(raw_text: str) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    for block in re.split(r"\r?\n\r?\n", raw_text.strip()):
        if not block.strip():
            continue
        ev_name = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                ev_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if ev_name and data_lines:
            frames.append((ev_name, json.loads("\n".join(data_lines))))
    return frames


def test_chat_stream_reports_database_failure_without_exposing_parameters(client, monkeypatch):
    async def fail_search(*args, **kwargs):
        raise RuntimeError("SQL failure with private query parameters")

    monkeypatch.setattr(client.app.state.container.repository, "hybrid_search_alumni", fail_search)
    response = client.post("/api/v1/chat/stream", json={
        "messages": [{"role": "user", "content": "Je cherche un alumni chez Mistral AI"}],
    })
    assert response.status_code == 200
    frames = _parse_sse_frames(response.text)
    assert "tool_start" in [name for name, _ in frames]
    assert frames[-1] == ("error", {"detail": "La recherche a échoué. Veuillez réessayer."})
    assert "private query parameters" not in response.text
    assert "final_result" not in [name for name, _ in frames]


def test_chat_search_and_sse_stream_with_mutuals(client):
    payload = {
        "messages": [
            {
                "role": "user",
                "content": "Je cherche un alumni dans l'IA générative chez Mistral AI",
                "timestamp": "14:10",
            }
        ]
    }

    res = client.post("/api/v1/chat", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["intro_text"]
    assert body["total_candidates"] >= 1
    assert len(body["people"]) >= 1

    top = body["people"][0]
    assert top["full_name"] == "Alice Martin"
    assert "Mistral AI" in top["role_company"]
    assert top["thinking"]
    assert top["source_url"] == "https://www.linkedin.com/in/alice-martin"
    assert top["source_label"] == "LinkedIn"

    mutual_names = {m["full_name"] for m in top["mutuals"]}
    assert "Thomas Leroy" in mutual_names or "Sarah Cohen" in mutual_names
    assert any(m["reason"] for m in top["mutuals"])

    tool_names = [t["tool"] for t in body["tools_used"]]
    assert "search_alumni" in tool_names
    assert "find_mutual_connections" in tool_names
    for trace in body["tools_used"]:
        assert isinstance(trace["arguments"], dict)
        assert trace["result_summary"]

    # SSE stream verification
    with client.stream("POST", "/api/v1/chat/stream", json=payload) as stream_res:
        assert stream_res.status_code == 200
        raw_sse = "".join(stream_res.iter_text())

    frames = _parse_sse_frames(raw_sse)
    event_types = [ev for ev, _ in frames]
    assert "assistant_intro" in event_types
    assert "tool_start" in event_types
    assert "tool_done" in event_types
    assert event_types[-1] == "final_result"

    final_payload = frames[-1][1]["response"]
    assert final_payload["people"][0]["full_name"] == "Alice Martin"


def test_chat_friend_scoped_search_and_mutuals(client):
    # Thomas Leroy has 1-hop neighbor Claire Moreau (Doctolib) and 2-hop neighbor Alice Martin (ex-Doctolib)
    # Benoît Garnier (Engie) is NOT in Thomas's 1-2 hop neighborhood in conftest
    res = client.post(
        "/api/v1/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "Trouve dans les amis de Thomas quelqu'un chez Doctolib",
                }
            ]
        },
    )
    assert res.status_code == 200
    body = res.json()
    names = [p["full_name"] for p in body["people"]]
    assert "Claire Moreau" in names
    assert "Benoît Garnier" not in names
    assert "Thomas" in body["intro_text"]

    claire = next(p for p in body["people"] if p["full_name"] == "Claire Moreau")
    assert any(m["full_name"] == "Thomas Leroy" for m in claire["mutuals"])


def test_chat_multi_turn_context_inheritance_and_draft(client):
    # Turn 1: user specifies topic; Turn 2: follow-up scopes to Thomas's friends; Turn 3: drafts intro
    res_scoped = client.post(
        "/api/v1/chat",
        json={
            "messages": [
                {"role": "user", "content": "Je cherche quelqu'un en Product Management chez Doctolib"},
                {"role": "assistant", "content": "J'ai trouvé des profils chez Doctolib."},
                {"role": "user", "content": "Trouve dans les amis de Thomas"},
            ]
        },
    )
    assert res_scoped.status_code == 200
    scoped_body = res_scoped.json()
    assert scoped_body["people"]
    assert scoped_body["people"][0]["full_name"] == "Claire Moreau"

    res_draft = client.post(
        "/api/v1/chat",
        json={
            "messages": [
                {"role": "user", "content": "Je cherche un alumni chez Mistral AI"},
                {"role": "assistant", "content": "J'ai trouvé Alice Martin."},
                {
                    "role": "user",
                    "content": "Rédige un message à Thomas Leroy pour qu'il me présente Alice Martin pour un stage de césure",
                },
            ]
        },
    )
    assert res_draft.status_code == 200
    draft_body = res_draft.json()
    assert draft_body["drafted_message"]
    assert "Thomas" in draft_body["drafted_message"]
    assert "Alice Martin" in draft_body["drafted_message"]
    assert not re.search(r"\[[^\]]+\]", draft_body["drafted_message"])
    assert any(t["tool"] == "draft_intro_message" for t in draft_body["tools_used"])


def test_chat_clarify_on_greeting(client):
    res = client.post(
        "/api/v1/chat",
        json={"messages": [{"role": "user", "content": "Bonjour"}]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["people"] == []
    assert body["tools_used"] == []
    assert body["intro_text"]


async def test_iterative_tool_calling_loop_with_mocked_vertex_llm():
    """Verify multi-step native tool loop: search_alumni -> enrich_alumni_profiles -> find_mutual_connections."""
    repo = build_test_repository()
    marc_id = "66666666-6666-4666-8666-666666666666"
    repo.profiles[marc_id].location = "Paris, France"
    student_id = "11111111-1111-4111-8111-111111111111"

    graph = GraphEngine()
    graph.reload(await repo.list_profiles(), await repo.list_edges())

    class MockVertexToolLLM(VertexLLMService):
        def __init__(self) -> None:
            self.gemma_model = "gemma-4-test"
            self.embedding_dim = 768
            self._fallback = DeterministicLLMService(embedding_dim=768)
            self.step = 0
            self.client = SimpleNamespace(
                models=SimpleNamespace(generate_content=self._fake_generate_content)
            )

        def _fake_generate_content(self, *, model, contents, config):
            self.step += 1
            if self.step == 1:
                fc = types.FunctionCall(
                    name="search_alumni",
                    args={"query": "VP Engineering énergie GreenTech", "sector": "Énergie"},
                )
                return SimpleNamespace(
                    function_calls=[fc],
                    candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part(function_call=fc)]))],
                    text="",
                )
            if self.step == 2:
                # Confirm the LLM received Marc Petit's observation from search_alumni
                last_parts = contents[-1].parts
                obs = last_parts[0].function_response.response
                assert any(c["id"] == marc_id and c["needs_enrichment"] is True for c in obs["candidates"])
                fc = types.FunctionCall(
                    name="enrich_alumni_profiles",
                    args={"profile_ids": [marc_id]},
                )
                return SimpleNamespace(
                    function_calls=[fc],
                    candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part(function_call=fc)]))],
                    text="",
                )
            if self.step == 3:
                obs = contents[-1].parts[0].function_response.response
                assert obs["count"] == 1
                assert "Club Énergie" in obs["enriched"][0]["associations"]
                fc = types.FunctionCall(
                    name="find_mutual_connections",
                    args={"target_ids": [marc_id]},
                )
                return SimpleNamespace(
                    function_calls=[fc],
                    candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part(function_call=fc)]))],
                    text="",
                )
            return SimpleNamespace(
                function_calls=[],
                candidates=[],
                text=json.dumps(
                    {
                        "final_answer": "Voici Marc Petit après enrichissement web.",
                        "selected_people": [
                            {
                                "id": marc_id,
                                "thinking": "Marc Petit est VP Engineering chez GreenTech Energy, ancien du Club Énergie et passionné de trail.",
                            }
                        ],
                    }
                ),
            )

        async def parse_user_query(self, query: str):
            return await self._fallback.parse_user_query(query)

        async def extract_profile_from_snippets(self, full_name: str, snippets: str):
            return await self._fallback.extract_profile_from_snippets(full_name, snippets)

        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return await self._fallback.embed_texts(texts)

        def _generate_sync(self, prompt: str, *, temperature: float = 0.1, schema=None) -> str:
            return "{}"

    llm = MockVertexToolLLM()
    spy_web = SpyTavilyClient()
    enrichment = EnrichmentService(repo, llm, graph, web_client=spy_web)
    search_agent = SearchAgentService(repo, llm, enrichment, graph)
    chat_agent = ChatAgentService(repo, llm, enrichment, graph, search_agent)

    events: list[tuple[str, dict]] = []

    async def on_event(ev: str, payload: dict) -> None:
        events.append((ev, payload))

    response = await chat_agent.run_chat(
        student_id,
        [ChatMessage(role="user", content="Je cherche un VP Engineering dans l'énergie chez GreenTech")],
        event_callback=on_event,
    )

    assert [t.tool for t in response.tools_used] == [
        "search_alumni",
        "enrich_alumni_profiles",
        "find_mutual_connections",
    ]
    assert response.tools_used[0].arguments["sector"] == "Énergie"
    assert response.tools_used[1].arguments["profile_ids"] == [marc_id]
    assert response.tools_used[2].arguments["target_ids"] == [marc_id]

    tool_sequence = [(ev, p.get("tool")) for ev, p in events if ev in ("tool_start", "tool_done")]
    assert tool_sequence == [
        ("tool_start", "search_alumni"),
        ("tool_done", "search_alumni"),
        ("tool_start", "enrich_alumni_profiles"),
        ("tool_done", "enrich_alumni_profiles"),
        ("tool_start", "find_mutual_connections"),
        ("tool_done", "find_mutual_connections"),
    ]
    assert events[0][0] == "assistant_intro"
    assert events[-1][0] == "final_result"

    marc_res = response.people[0]
    assert marc_res.full_name == "Marc Petit"
    assert marc_res.location == "Paris, France"
    assert marc_res.source_url == "https://www.linkedin.com/in/marc-petit"
    assert marc_res.source_label == "LinkedIn"
    assert "GreenTech Energy" in marc_res.thinking

    # Confirm enrichment persisted to DB/cache
    updated_marc = await repo.get_profile(marc_id)
    assert updated_marc is not None
    assert updated_marc.last_enriched_at is not None
    assert "Club Énergie" in updated_marc.associations


async def test_react_json_fallback_when_native_tools_unsupported():
    """Verify automatic ReAct JSON fallback when Vertex Gemma rejects native function declarations."""
    repo = build_test_repository()
    graph = GraphEngine()
    graph.reload(await repo.list_profiles(), await repo.list_edges())

    class ReActFallbackLLM(VertexLLMService):
        def __init__(self) -> None:
            self.gemma_model = "gemma-4-test"
            self.embedding_dim = 768
            self._fallback = DeterministicLLMService(embedding_dim=768)
            self.turn = 0
            self.client = SimpleNamespace(
                models=SimpleNamespace(generate_content=self._reject_native)
            )

        def _reject_native(self, **kwargs):
            raise RuntimeError("Function calling is not supported on this Gemma endpoint")

        def _generate_sync(self, prompt: str, *, temperature: float = 0.1, schema=None) -> str:
            self.turn += 1
            if self.turn == 1:
                return json.dumps(
                    {
                        "thought": "Je cherche dans l'annuaire Doctolib.",
                        "intro": "Je recherche des alumni chez Doctolib.",
                        "tool_calls": [
                            {"name": "search_alumni", "arguments": {"query": "Product Manager Doctolib", "company": "Doctolib"}}
                        ],
                    }
                )
            if self.turn == 2:
                return json.dumps(
                    {
                        "thought": "Je vérifie les contacts communs pour Claire Moreau.",
                        "tool_calls": [
                            {
                                "name": "find_mutual_connections",
                                "arguments": {"target_ids": ["44444444-4444-4444-8444-444444444444"]},
                            }
                        ],
                    }
                )
            return json.dumps(
                {
                    "thought": "Je synthétise la réponse.",
                    "tool_calls": [],
                    "final_answer": "Claire Moreau correspond exactement à ta recherche chez Doctolib.",
                    "selected_people": [
                        {
                            "id": "44444444-4444-4444-8444-444444444444",
                            "thinking": "Product Manager chez Doctolib, membre du BDS comme Thomas Leroy.",
                        }
                    ],
                }
            )

        async def parse_user_query(self, query: str):
            return await self._fallback.parse_user_query(query)

        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return await self._fallback.embed_texts(texts)

    llm = ReActFallbackLLM()
    enrichment = EnrichmentService(repo, llm, graph, web_client=SpyTavilyClient())
    search_agent = SearchAgentService(repo, llm, enrichment, graph)
    chat_agent = ChatAgentService(repo, llm, enrichment, graph, search_agent)

    resp = await chat_agent.run_chat(
        "11111111-1111-4111-8111-111111111111",
        [ChatMessage(role="user", content="Cherche un Product Manager chez Doctolib")],
    )
    assert [t.tool for t in resp.tools_used] == ["search_alumni", "find_mutual_connections"]
    assert resp.people[0].full_name == "Claire Moreau"
    assert any(m.full_name == "Thomas Leroy" for m in resp.people[0].mutuals)


def test_chat_get_profile_details_followup_returns_prose(client):
    payload = {
        "messages": [
            {"role": "user", "content": "Je cherche un alumni chez Mistral AI"},
            {"role": "assistant", "content": "J'ai trouvé Alice Martin."},
            {
                "role": "user",
                "content": "Parle-moi plus en détail du parcours, des associations et des passions d'Alice Martin",
            },
        ]
    }
    res = client.post("/api/v1/chat", json=payload)
    assert res.status_code == 200
    body = res.json()

    assert body["people"] == []
    assert body["total_candidates"] == 0
    assert any(t["tool"] == "get_profile_details" for t in body["tools_used"])
    detail_trace = next(t for t in body["tools_used"] if t["tool"] == "get_profile_details")
    assert detail_trace["arguments"]["profile_id"] == "22222222-2222-4222-8222-222222222222"
    assert "Alice Martin" in detail_trace["result_summary"]

    prose = body["intro_text"]
    assert "Alice Martin" in prose
    assert "Mistral AI" in prose
    assert "Doctolib" in prose
    assert "Junior CentraleSupélec" in prose or "BDS" in prose


def test_chat_friend_scoped_draft_flow_and_noise_filtering(test_settings, fake_llm, spy_tavily):
    """Verify friend-scoped search + draft_intro_message flow, malformed company guard, and noise exclusion."""
    repo = build_test_repository()
    # Add a noisy unenriched profile with a malformed sentence fragment in current_company
    noisy = ProfileRecord(
        id="88888888-8888-4888-8888-888888888888",
        full_name="Paul Inconnu",
        promo_year=2022,
        current_role="Alumni",
        current_company="est un ingénieur qui a travaillé dans plusieurs secteurs très variés sans lien.",
        bio=None,
        experiences=[],
        associations=[],
        passions=[],
        has_imported_linkedin=False,
        last_enriched_at=None,
    )
    noisy.embedding = deterministic_text_embedding("Paul Inconnu CentraleSupélec", dim=768)
    repo.profiles[noisy.id] = noisy
    repo.profiles["44444444-4444-4444-8444-444444444444"].location = "Paris, France"

    app = create_app(
        settings=test_settings,
        repository=repo,
        llm_service=fake_llm,
        web_client=spy_tavily,
        graph_engine=GraphEngine(),
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        # 1. Friend-scoped search excludes unrelated noise and surfaces Claire Moreau with location
        res_search = c.post(
            "/api/v1/chat",
            json={
                "messages": [
                    {"role": "user", "content": "Trouve dans les amis de Thomas quelqu'un chez Doctolib"}
                ]
            },
        )
        assert res_search.status_code == 200
        search_body = res_search.json()
        names = [p["full_name"] for p in search_body["people"]]
        assert "Claire Moreau" in names
        assert "Paul Inconnu" not in names
        claire = next(p for p in search_body["people"] if p["full_name"] == "Claire Moreau")
        assert claire["location"] == "Paris, France"

        # 2. General search still filters out unenriched noisy Paul Inconnu when Mistral AI match exists
        res_mistral = c.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "Je cherche quelqu'un chez Mistral AI"}]},
        )
        assert res_mistral.status_code == 200
        mistral_names = [p["full_name"] for p in res_mistral.json()["people"]]
        assert "Alice Martin" in mistral_names
        assert "Paul Inconnu" not in mistral_names

        # 3. Follow-up draft_intro_message using friend Thomas Leroy -> Claire Moreau
        res_draft = c.post(
            "/api/v1/chat",
            json={
                "messages": [
                    {"role": "user", "content": "Trouve dans les amis de Thomas quelqu'un chez Doctolib"},
                    {"role": "assistant", "content": "J'ai trouvé Claire Moreau."},
                    {
                        "role": "user",
                        "content": "Rédige un message à Thomas Leroy pour contacter Claire Moreau au sujet du Product Management",
                    },
                ]
            },
        )
        assert res_draft.status_code == 200
        draft_body = res_draft.json()
        assert draft_body["drafted_message"]
        assert "Thomas" in draft_body["drafted_message"]
        assert "Claire Moreau" in draft_body["drafted_message"]
        assert any(t["tool"] == "draft_intro_message" for t in draft_body["tools_used"])
