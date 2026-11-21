"""Unit tests for FreeFirstWebSearchClient, EnrichmentCache SQLite roundtrip, career sanitization, and batch CLI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.enrichment_cache import EnrichmentCache
from app.db.repository import InMemoryAlumniRepository, ProfileRecord
from app.main import create_app
from app.schemas.profile import EnrichedProfile, Experience
from app.services.enrichment import _sanitize_extracted_career
from app.services.llm import DeterministicLLMService
from app.services.web_scraper import FreeFirstWebSearchClient
from scripts.enrich_batch import run_batch_enrichment


def test_enrichment_cache_save_load_merge_roundtrip_768_dim(tmp_path: Path):
    db_path = tmp_path / "enrichment_cache.sqlite"
    cache = EnrichmentCache(str(db_path))

    repo1 = InMemoryAlumniRepository(enrichment_cache=cache)
    prof = ProfileRecord(
        id="prof-alice-1",
        full_name="Alice Martin",
        promo_year=2020,
        associations=["Junior CentraleSupélec"],
        enrichment_source="LINKCS_DB",
        last_enriched_at=None,
    )
    repo1.profiles[prof.id] = prof

    vec_768 = [round((i % 13) * 0.01, 4) for i in range(768)]

    import asyncio

    updated = asyncio.run(
        repo1.update_enrichment(
            prof.id,
            bio="Lead ML Engineer chez Mistral AI à Paris.",
            experiences=[{"company": "Mistral AI", "role": "Lead ML Engineer", "period": "2023-Present"}],
            associations=["BDS"],
            passions=["trail"],
            embedding=vec_768,
            current_role="Lead ML Engineer",
            current_company="Mistral AI",
            sector="Intelligence Artificielle",
            location="Paris",
            linkedin_url="https://www.linkedin.com/in/alice-martin",
            embedding_space="vertex",
            enrichment_source="WEB_FREE",
            enriched_at=datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc),
        )
    )
    assert updated is not None
    assert cache.count_enriched() == 1

    loaded = cache.load_all()
    assert prof.id in loaded
    assert loaded[prof.id]["current_company"] == "Mistral AI"
    assert loaded[prof.id]["location"] == "Paris"
    assert loaded[prof.id]["linkedin_url"] == "https://www.linkedin.com/in/alice-martin"
    assert len(loaded[prof.id]["embedding"]) == 768
    assert loaded[prof.id]["embedding"][:5] == pytest.approx(vec_768[:5])
    assert loaded[prof.id]["embedding_space"] == "vertex"

    # Fresh repository reloads LinkCS profile with a different synthetic ID but same normalized name, or same ID
    repo2 = InMemoryAlumniRepository()
    sparse_reload = ProfileRecord(
        id="prof-alice-1",
        full_name="Alice Martin",
        promo_year=2020,
        associations=["Junior CentraleSupélec"],
        enrichment_source="LINKCS_DB",
        last_enriched_at=None,
    )
    repo2.profiles[sparse_reload.id] = sparse_reload
    merged_count = repo2.apply_cached_enrichment(cache)
    assert merged_count == 1
    assert sparse_reload.current_company == "Mistral AI"
    assert sparse_reload.current_role == "Lead ML Engineer"
    assert sparse_reload.location == "Paris"
    assert sparse_reload.linkedin_url == "https://www.linkedin.com/in/alice-martin"
    assert "BDS" in sparse_reload.associations
    assert "trail" in sparse_reload.passions
    assert sparse_reload.embedding_space == "vertex"
    assert sparse_reload.embedding is not None and len(sparse_reload.embedding) == 768
    assert sparse_reload.last_enriched_at is not None


@pytest.mark.asyncio
async def test_free_first_web_search_ddg_html_and_tavily_fallback():
    ddg_html = """
    <html><body>
      <div class="result results_links results_links_deep web-result">
        <h2 class="result__title">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ffr.linkedin.com%2Fin%2Falice-martin-cs%2F%3Ftrk%3Dpublic&amp;rut=abc">
            Alice Martin - Lead ML Engineer - Mistral AI | LinkedIn
          </a>
        </h2>
        <a class="result__snippet" href="#">
          Lead ML Engineer chez Mistral AI. Ancienne élève CentraleSupélec promo 2020.
        </a>
      </div>
    </body></html>
    """

    class SpyFallback:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def search(self, query: str, max_results: int = 4, include_domains=None) -> list[dict]:
            self.calls.append(query)
            return [{"title": "Tavily Hit", "url": "https://www.linkedin.com/in/fallback-user", "content": "Fallback"}]

    # 1. DDG HTML returns valid result -> must NOT call Tavily fallback
    def handler_ok(request: httpx.Request) -> httpx.Response:
        if "html.duckduckgo.com" in str(request.url):
            return httpx.Response(200, text=ddg_html)
        return httpx.Response(200, text="<html></html>")

    spy_fb = SpyFallback()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_ok)) as http_client:
        client = FreeFirstWebSearchClient(
            tavily_fallback=spy_fb,
            jitter_range=(0.0, 0.0),
            http_client=http_client,
        )
        assert client.provider_label == "free_first"
        results = await client.search('"Alice Martin" CentraleSupélec linkedin', max_results=4)

    assert len(results) == 1
    assert results[0]["title"] == "Alice Martin - Lead ML Engineer - Mistral AI | LinkedIn"
    assert results[0]["url"] == "https://www.linkedin.com/in/alice-martin-cs"
    assert "Mistral AI" in results[0]["content"]
    assert client.free_hits == 1
    assert client.tavily_fallbacks == 0
    assert spy_fb.calls == []

    # 2. DDG returns 0 results (or challenge page) -> cleanly falls back to Tavily
    def handler_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>No results</body></html>")

    spy_fb2 = SpyFallback()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_empty)) as http_client:
        client2 = FreeFirstWebSearchClient(
            tavily_fallback=spy_fb2,
            jitter_range=(0.0, 0.0),
            http_client=http_client,
        )
        results2 = await client2.search('"Unknown Person" CentraleSupélec linkedin', max_results=4)

    assert len(results2) == 1
    assert results2[0]["url"] == "https://www.linkedin.com/in/fallback-user"
    assert client2.free_hits == 0
    assert client2.tavily_fallbacks == 1
    assert len(spy_fb2.calls) == 1

    # 3. Challenge page with disable_tavily_fallback=True -> stops cleanly, never bypasses, returns []
    def handler_challenge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, text='<div class="anomaly-modal">Please complete the following challenge</div>')

    spy_fb3 = SpyFallback()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_challenge)) as http_client:
        client3 = FreeFirstWebSearchClient(
            tavily_fallback=spy_fb3,
            disable_tavily_fallback=True,
            jitter_range=(0.0, 0.0),
            http_client=http_client,
        )
        assert client3.provider_label == "free_first"
        results3 = await client3.search('"Alice Martin" CentraleSupélec linkedin', max_results=4)

    assert results3 == []
    assert client3.tavily_fallbacks == 0
    assert spy_fb3.calls == []


@pytest.mark.asyncio
async def test_free_first_web_search_ddg_challenge_cooldown_skips_repeat_http_calls():
    ddg_requests: list[str] = []

    def handler_challenge(request: httpx.Request) -> httpx.Response:
        ddg_requests.append(str(request.url))
        return httpx.Response(202, text='<div class="anomaly-modal">Please complete the following challenge</div>')

    class SpyFallback:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def search(self, query: str, max_results: int = 4, include_domains=None) -> list[dict]:
            self.calls.append(query)
            return [{"title": "Tavily Hit", "url": "https://www.linkedin.com/in/tavily-user", "content": "Fallback"}]

    spy_fb = SpyFallback()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_challenge)) as http_client:
        client = FreeFirstWebSearchClient(
            tavily_fallback=spy_fb,
            jitter_range=(0.0, 0.0),
            http_client=http_client,
            ddg_challenge_cooldown_seconds=600.0,
        )
        first = await client.search('"Alice Martin" CentraleSupélec linkedin', max_results=4)
        calls_after_first = len(ddg_requests)
        second = await client.search('"Bob Dupont" CentraleSupélec linkedin', max_results=4)

    assert len(first) == 1
    assert len(second) == 1
    assert calls_after_first == 1
    assert len(ddg_requests) == 1
    assert client.free_hits == 0
    assert client.tavily_fallbacks == 2
    assert len(spy_fb.calls) == 2


def test_sanitize_extracted_career_rejects_noise_and_extracts_canonical_linkedin():
    profile = ProfileRecord(
        id="p1",
        full_name="Élodie Mercier",
        promo_year=2021,
    )

    noisy_extracted = EnrichedProfile(
        bio="Élodie Mercier travaille dans la transition énergétique.",
        current_role="Senior Analyst",
        current_company="123 people are employed at CentraleSupélec and research is now expanding across Europe",
        location="Paris, France",
        linkedin_url="https://www.linkedin.com/in/someone-else-999",
        experiences=[
            Experience(company="CentraleSupélec", role="Student"),
            Experience(company="Some people are employed here", role="Intern"),
            Experience(company="Qair", role="Energy Analyst", period="2022-Present"),
        ],
    )
    search_results = [
        {
            "title": "Élodie Mercier - Energy Analyst - Qair | LinkedIn",
            "url": "https://fr.linkedin.com/in/elodie-mercier-42a/?locale=fr_FR",
            "content": "Energy Analyst chez Qair à Paris.",
        }
    ]

    sanitized = _sanitize_extracted_career(profile, noisy_extracted, search_results)
    assert sanitized.current_company == "Qair"
    assert sanitized.linkedin_url == "https://www.linkedin.com/in/elodie-mercier-42a"
    assert sanitized.location == "Paris, France"
    assert [e.company for e in sanitized.experiences] == ["Qair"]

    # Reject standalone CentraleSupélec with no valid backup experience
    school_only = EnrichedProfile(
        current_role="Ingénieure",
        current_company="CentraleSupélec",
        linkedin_url="https://fr.linkedin.com/in/elodie-mercier/?trk=test",
    )
    sanitized2 = _sanitize_extracted_career(profile, school_only)
    assert sanitized2.current_company is None
    assert sanitized2.linkedin_url == "https://www.linkedin.com/in/elodie-mercier"


@pytest.mark.asyncio
async def test_batch_enrichment_cli_resumable_and_health_fields(tmp_path: Path):
    data = [
        {
            "login": "2020_low",
            "nom_complet": "Lucie Faible",
            "promotion": 2020,
            "associations": ["BDS"],
            "clubs_et_groupes": [],
            "biographie": "",
            "reseaux_sociaux": [],
        },
        {
            "login": "2020_high",
            "nom_complet": "Hugo Actif",
            "promotion": 2020,
            "associations": ["BDS", "ViaRézo", "Junior CentraleSupélec"],
            "clubs_et_groupes": [],
            "biographie": "",
            "reseaux_sociaux": [],
        },
    ]
    dataset_path = tmp_path / "linkcs.json"
    dataset_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cache_path = tmp_path / "cache.sqlite"

    class FakeBatchSearch:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.free_hits = 0
            self.tavily_fallbacks = 0
            self.last_used_provider = "free"

        async def search(self, query: str, max_results: int = 4, include_domains=None) -> list[dict]:
            self.queries.append(query)
            self.free_hits += 1
            if "Lucie Faible" in query:
                return [
                    {
                        "title": "Lucie Faible - Data Analyst - Doctolib",
                        "url": "https://fr.linkedin.com/in/lucie-faible",
                        "content": "Lucie Faible travaille comme Data Analyst chez Doctolib (2023-Present).",
                    }
                ]
            return [
                {
                    "title": "Hugo Actif - Staff Engineer - Alan",
                    "url": "https://fr.linkedin.com/in/hugo-actif",
                    "content": "Hugo Actif travaille comme Staff Engineer chez Alan (2022-Present).",
                }
            ]

    fake_search = FakeBatchSearch()
    llm = DeterministicLLMService(embedding_dim=768)

    # Limit=1 must pick Hugo Actif (3 assos) before Lucie Faible (1 asso)
    stats1 = await run_batch_enrichment(
        input_path=str(dataset_path),
        limit=1,
        cache_path=str(cache_path),
        concurrency=2,
        no_tavily_fallback=True,
        llm_service=llm,
        web_client=fake_search,
    )
    assert stats1["processed"] == 1
    assert stats1["enriched_count"] == 1
    assert stats1["free_hits"] == 1
    assert stats1["cached_total"] == 1
    assert "Hugo Actif" in fake_search.queries[0]

    # Resumability: next run with limit=1 skips already cached Hugo Actif and processes Lucie Faible
    fake_search.queries.clear()
    stats2 = await run_batch_enrichment(
        input_path=str(dataset_path),
        limit=1,
        cache_path=str(cache_path),
        concurrency=2,
        no_tavily_fallback=True,
        llm_service=llm,
        web_client=fake_search,
    )
    assert stats2["processed"] == 1
    assert stats2["cached_total"] == 2
    assert "Lucie Faible" in fake_search.queries[0]

    # Verify create_app loads cache when linkcs_data_path is set and /health exposes enriched_profiles & search_provider
    app = create_app(
        settings=Settings(
            database_url=None,
            demo_mode=True,
            allow_demo_auth=True,
            linkcs_data_path=str(dataset_path),
            enrichment_cache_path=str(cache_path),
        )
    )
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["status"] == "ok"
        assert health["enriched_profiles"] >= 2
        assert health["search_provider"] == "disabled"


@pytest.mark.asyncio
async def test_photo_url_extraction_og_image_and_api_exposure(tmp_path: Path):
    from app.services.web_scraper import extract_photo_url_from_results, fetch_og_image

    # 1) Prioritize media.licdn.com/dms/image over generic assets
    results = [
        {
            "title": "Alice Martin - LinkedIn",
            "url": "https://www.linkedin.com/in/alice-martin",
            "content": "Lead ML Engineer",
            "images": [
                "https://static.licdn.com/sc/h/ghost-person.svg",
                "https://example.com/logo.png",
                "https://media.licdn.com/dms/image/v2/D4E03AQF123/profile-displayphoto-shrink_200_200/0/123?e=123",
            ],
        }
    ]
    picked = extract_photo_url_from_results(results, linkedin_url="https://www.linkedin.com/in/alice-martin")
    assert picked is not None
    assert "media.licdn.com/dms/image" in picked

    # 2) fetch_og_image extracts og:image on 200 HTML and returns None on 999/authwall
    def _handler(request: httpx.Request) -> httpx.Response:
        if "blocked" in str(request.url):
            return httpx.Response(999, text="Request denied")
        if "authwall" in str(request.url):
            return httpx.Response(200, text="<html><meta property='og:image' content='https://media.licdn.com/x.jpg'></html>", request=httpx.Request("GET", "https://www.linkedin.com/authwall"))
        return httpx.Response(
            200,
            text='<html><head><meta property="og:image" content="https://media.licdn.com/dms/image/C4D03AQH/profile.jpg"></head></html>',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        ok_img = await fetch_og_image("https://www.linkedin.com/in/alice-martin", http_client=client)
        assert ok_img == "https://media.licdn.com/dms/image/C4D03AQH/profile.jpg"
        blocked_img = await fetch_og_image("https://www.linkedin.com/in/blocked", http_client=client)
        assert blocked_img is None

    # 3) EnrichmentCache + API + Chat exposure of photo_url
    cache = EnrichmentCache(str(tmp_path / "photo_cache.sqlite"))
    repo = InMemoryAlumniRepository(enrichment_cache=cache)
    prof = ProfileRecord(
        id="11111111-1111-4111-8111-111111111111",
        full_name="Student Demo",
        is_student=True,
    )
    alumni = ProfileRecord(
        id="22222222-2222-4222-8222-222222222222",
        full_name="Alice Martin",
        promo_year=2020,
        associations=["BDS"],
    )
    repo.profiles[prof.id] = prof
    repo.profiles[alumni.id] = alumni

    await repo.update_enrichment(
        alumni.id,
        bio="Lead ML Engineer chez Mistral AI.",
        experiences=[{"company": "Mistral AI", "role": "Lead ML Engineer"}],
        associations=["BDS"],
        passions=[],
        embedding=[0.1] * 768,
        current_role="Lead ML Engineer",
        current_company="Mistral AI",
        linkedin_url="https://www.linkedin.com/in/alice-martin",
        photo_url=picked,
    )
    assert cache.load_all()[alumni.id]["photo_url"] == picked

    app = create_app(
        settings=Settings(database_url=None, demo_mode=True, allow_demo_auth=True),
        repository=repo,
    )
    with TestClient(app) as client:
        prof_json = client.get(f"/api/v1/profiles/{alumni.id}").json()
        assert prof_json["photo_url"] == picked
        dir_json = client.get("/api/v1/profiles?q=Alice").json()
        assert dir_json[0]["photo_url"] == picked
        chat_json = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "Qui travaille chez Mistral AI ?"}]},
        ).json()
        assert chat_json["people"]
        assert chat_json["people"][0]["photo_url"] == picked


@pytest.mark.asyncio
async def test_enrichment_rejects_wrong_person_hallucinated_photo_and_company_logos():
    from app.services.enrichment import EnrichmentService, _filter_results_for_person
    from app.services.graph_engine import GraphEngine
    from app.services.web_scraper import extract_photo_url_from_results

    # 1) extract_photo_url_from_results rejects company logos, feedshare, and random non-profile banners
    bad_results = [
        {
            "title": "Alice Martin - LinkedIn",
            "url": "https://www.linkedin.com/in/alice-martin",
            "content": "Engineer",
            "images": [
                "https://media.licdn.com/dms/image/v2/D4E0BAQ/company-logo_200_200/0/123",
                "https://media.licdn.com/dms/image/v2/D4E22AQ/feedshare-shrink_800/0/456",
                "https://example.com/banner.jpg",
            ],
        }
    ]
    assert extract_photo_url_from_results(bad_results, linkedin_url="https://www.linkedin.com/in/alice-martin") is None

    # 2) _filter_results_for_person drops homonyms/wrong LinkedIn profiles and directory listings
    prof = ProfileRecord(id="p-lucie", full_name="Lucie Faible", promo_year=2020)
    mixed = [
        {
            "title": "Hugo Actif - Staff Engineer - Alan",
            "url": "https://fr.linkedin.com/in/hugo-actif",
            "content": "Staff Engineer chez Alan (a mentionné Lucie Faible).",
        },
        {
            "title": "10+ profils Lucie Faible | LinkedIn",
            "url": "https://fr.linkedin.com/pub/dir/Lucie/Faible",
            "content": "Lucie Faible - HEC Paris...",
        },
    ]
    assert _filter_results_for_person(prof, mixed) == []

    # 3) _sanitize_extracted_career ignores LLM-hallucinated photo_url not present in search_results
    hallucinated = EnrichedProfile(
        bio="[Lucie Faible] (https://example.com): Lucie Faible chez Alan.",
        current_role="Engineer",
        current_company="Alan",
        photo_url="https://media.licdn.com/dms/image/C4D03AQ_HALLUCINATED/profile-displayphoto-shrink_200_200/0/1",
    )
    sanitized = _sanitize_extracted_career(prof, hallucinated, [])
    assert sanitized.photo_url is None
    assert "https://" not in sanitized.bio

    # 4) EnrichmentService.enrich_candidates returns [] when search results only match someone else
    repo = InMemoryAlumniRepository()
    await repo.upsert_profile(prof)

    class WrongPersonWebClient:
        last_used_provider = "tavily"

        async def search(self, query: str, max_results: int = 4, include_images: bool = False) -> list[dict]:
            return mixed

    enrichment = EnrichmentService(repo, DeterministicLLMService(), GraphEngine(), web_client=WrongPersonWebClient())
    updated = await enrichment.enrich_candidates([prof])
    assert updated == []
    assert prof.current_company is None
    assert prof.photo_url is None
    assert prof.last_enriched_at is None
