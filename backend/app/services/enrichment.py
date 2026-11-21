"""Just-In-Time (JIT) Web Discovery & Enrichment service using Tavily + Gemma 4 + DB cache."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional, Protocol

from tavily import TavilyClient

from app.db.repository import AbstractAlumniRepository, ProfileRecord
from app.schemas.profile import EnrichedProfile, Experience
from app.schemas.search import ParsedQuery
from app.services.graph_engine import GraphEngine, strip_accents
from app.services.linkedin_parser import normalize_linkedin_url
from app.services.llm import LLMServiceProtocol, VertexLLMService
from app.services.web_scraper import (
    extract_photo_url_from_results,
    fetch_og_image,
    is_valid_profile_photo_url,
)

_DISCOVERY_STOPWORDS = {
    "je", "tu", "il", "elle", "nous", "vous", "un", "une", "des", "le", "la", "les",
    "du", "de", "d", "et", "ou", "dans", "en", "sur", "avec", "pour", "qui", "que",
    "cherche", "veux", "voudrais", "trouver", "contacter", "echanger", "parler",
    "alumni", "ancien", "ancienne", "etudiant", "etudiante", "quelqu", "boite",
    "entreprise", "travaille", "travaillant", "stage", "cesure", "centralesupelec",
    "fait", "aime", "membre", "chez",
}


class WebSearchClientProtocol(Protocol):
    async def search(
        self,
        query: str,
        max_results: int = 4,
        include_domains: Optional[list[str]] = None,
        include_images: bool = False,
    ) -> list[dict]: ...


class TavilyWebSearchClient:
    """Async adapter around tavily.TavilyClient."""

    def __init__(self, api_key: str) -> None:
        self._client = TavilyClient(api_key=api_key)

    async def search(
        self,
        query: str,
        max_results: int = 4,
        include_domains: Optional[list[str]] = None,
        include_images: bool = False,
    ) -> list[dict]:
        kwargs: dict = {"query": query, "max_results": max_results}
        if include_domains:
            kwargs["include_domains"] = include_domains
        if include_images:
            kwargs["include_images"] = True
        res = await asyncio.to_thread(self._client.search, **kwargs)
        results = [dict(item) if isinstance(item, dict) else item for item in res.get("results", [])]
        raw_images = res.get("images") or []
        if raw_images and results:
            norm_images = [
                img.get("url") if isinstance(img, dict) else img
                for img in raw_images
            ]
            clean_images = [u for u in norm_images if isinstance(u, str) and u.strip()]
            if clean_images:
                li_target = next(
                    (
                        item
                        for item in results
                        if isinstance(item, dict) and "linkedin.com/in/" in str(item.get("url") or "").lower()
                    ),
                    None,
                )
                if li_target is not None:
                    li_target["images"] = clean_images
                elif isinstance(results[0], dict):
                    results[0]["images"] = clean_images
        return results


class NullWebSearchClient:
    """No-op web search client used when TAVILY_API_KEY is absent."""

    async def search(
        self,
        query: str,
        max_results: int = 4,
        include_domains: Optional[list[str]] = None,
        include_images: bool = False,
    ) -> list[dict]:
        return []


def _extract_query_keywords(raw_query: str) -> list[str]:
    norm = strip_accents(raw_query).lower()
    return [
        tok
        for tok in re.findall(r"[a-z0-9\-]{3,}", norm)
        if tok not in _DISCOVERY_STOPWORDS
    ]


def _detect_dominant_cohort_hint(profiles: list[ProfileRecord]) -> str:
    promos = [p.promo_year for p in profiles if not p.is_student and p.promo_year]
    if not promos:
        return ""
    top_promo, count = Counter(promos).most_common(1)[0]
    if count / len(promos) > 0.60:
        return f"{top_promo - 3} {top_promo}"
    return ""


def _build_name_slugs(full_name: str) -> tuple[str, list[str]]:
    norm = re.sub(r"\s+", " ", strip_accents(full_name).lower()).strip()
    parts = [re.sub(r"[^a-z0-9]", "", tok) for tok in norm.split()]
    parts = [p for p in parts if len(p) >= 2]
    if len(parts) < 2:
        return norm, []
    first, last = parts[0], parts[-1]
    return norm, [f"{first}-{last}", f"{last}-{first}", f"{first}{last}"]


_GARBAGE_CAREER_MARKERS = (
    "people are employed",
    "research is now",
    "is employed",
    "view profile",
    "voir le profil",
    "see who you know",
    "sign in",
    "join now",
    "http://",
    "https://",
)

_SCHOOL_ONLY_COMPANIES = {
    "centralesupelec",
    "centrale supelec",
    "ecole centrale",
    "ecole centrale paris",
    "supelec",
    "universite paris-saclay",
    "paris-saclay",
}


def _is_valid_company_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" -|•·,.;:")
    if not cleaned or len(cleaned) > 65:
        return None
    norm = strip_accents(cleaned).lower()
    if norm in _SCHOOL_ONLY_COMPANIES:
        return None
    if any(marker in norm for marker in _GARBAGE_CAREER_MARKERS):
        return None
    if norm in ("linkedin", "unknown", "inconnue", "n/a", "none", "null"):
        return None
    return cleaned


def _is_valid_role_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" -|•·,.;:")
    if not cleaned or len(cleaned) > 85:
        return None
    norm = strip_accents(cleaned).lower()
    if any(marker in norm for marker in _GARBAGE_CAREER_MARKERS):
        return None
    return cleaned


def _matches_person_linkedin(profile: ProfileRecord, norm_url: str, title: str = "") -> bool:
    if not norm_url or "/in/" not in norm_url:
        return False
    norm_name, slugs = _build_name_slugs(profile.full_name)
    tokens = [re.sub(r"[^a-z0-9]", "", tok) for tok in norm_name.split()]
    tokens = [t for t in tokens if len(t) >= 2]
    hyphen_tokens = [t for t in re.findall(r"[a-z0-9]{2,}", norm_name)]
    url_slug = norm_url.split("/in/", 1)[1].strip("/").lower()
    if any(s in url_slug for s in slugs):
        return True
    if len(tokens) >= 2 and tokens[0] in url_slug and tokens[-1] in url_slug:
        return True
    if len(hyphen_tokens) >= 2 and all(t in url_slug for t in (hyphen_tokens[0], hyphen_tokens[-1])):
        return True
    if title:
        norm_title = re.sub(r"\s+", " ", strip_accents(title).lower()).strip()
        if norm_name and (
            norm_title.startswith(norm_name)
            or f" {norm_name} -" in norm_title
            or f" {norm_name} |" in norm_title
        ):
            return True
    return False


def _filter_results_for_person(profile: ProfileRecord, results: list[dict]) -> list[dict]:
    """Keep only search results that plausibly belong to the target person (drop homonyms & directories)."""
    norm_name, _ = _build_name_slugs(profile.full_name)
    if not norm_name:
        return []
    name_re = re.compile(rf"(?<![a-z0-9]){re.escape(norm_name)}(?![a-z0-9])")

    filtered: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        raw_url = str(item.get("url") or "")
        low_url = raw_url.lower()
        title = str(item.get("title") or "")
        content = str(item.get("content") or "")

        if any(
            bad in low_url
            for bad in ("linkedin.com/pub/dir/", "linkedin.com/authwall", "linkedin.com/login", "linkedin.com/signup")
        ):
            continue

        if "linkedin.com/in/" in low_url:
            norm_url = normalize_linkedin_url(raw_url)
            if norm_url and _matches_person_linkedin(profile, norm_url, title):
                filtered.append(item)
            continue

        haystack = re.sub(r"\s+", " ", strip_accents(f"{title} {content}").lower())
        if name_re.search(haystack):
            filtered.append(item)

    return filtered


def _sanitize_extracted_career(
    profile: ProfileRecord,
    extracted: EnrichedProfile,
    search_results: Optional[list[dict]] = None,
) -> EnrichedProfile:
    """Reject noisy sentence fragments / school-only companies and canonicalize matching LinkedIn URLs."""
    clean_exps: list[Experience] = []
    for exp in extracted.experiences:
        valid_company = _is_valid_company_name(exp.company)
        valid_role = _is_valid_role_name(exp.role)
        if not valid_company or not valid_role:
            continue
        clean_exps.append(
            Experience(
                company=valid_company,
                role=valid_role,
                start_date=exp.start_date,
                end_date=exp.end_date,
                period=exp.period,
            )
        )

    clean_company = _is_valid_company_name(extracted.current_company)
    clean_role = _is_valid_role_name(extracted.current_role)
    if not clean_company and clean_exps:
        clean_company = clean_exps[0].company
        if not clean_role:
            clean_role = clean_exps[0].role

    clean_location: Optional[str] = None
    if extracted.location:
        loc = re.sub(r"\s+", " ", extracted.location).strip()
        loc_norm = strip_accents(loc).lower()
        if loc and len(loc) <= 80 and not any(m in loc_norm for m in _GARBAGE_CAREER_MARKERS):
            clean_location = loc

    clean_sector: Optional[str] = None
    if extracted.sector:
        sec = re.sub(r"\s+", " ", extracted.sector).strip(" -|•·,.;:")
        sec_norm = strip_accents(sec).lower()
        if sec and len(sec) <= 60 and not any(m in sec_norm for m in _GARBAGE_CAREER_MARKERS):
            clean_sector = sec

    clean_bio = re.sub(r"^\[[^\]]*\]\s*\([^)]*\)\s*:\s*", "", (extracted.bio or "").strip())
    clean_bio = re.sub(r"https?://\S+", "", clean_bio).strip()
    bio_norm = strip_accents(clean_bio).lower()
    if any(m in bio_norm for m in _GARBAGE_CAREER_MARKERS):
        clean_bio = ""

    clean_assos: list[str] = []
    comp_norm = strip_accents(clean_company or "").lower()
    for asso in extracted.associations:
        a_clean = re.sub(r"\s+", " ", asso).strip()
        a_norm = strip_accents(a_clean).lower()
        if (
            not a_clean
            or len(a_clean) > 65
            or a_norm in _SCHOOL_ONLY_COMPANIES
            or (comp_norm and a_norm == comp_norm)
            or any(m in a_norm for m in _GARBAGE_CAREER_MARKERS)
        ):
            continue
        clean_assos.append(a_clean)

    canonical_linkedin: Optional[str] = None
    if search_results:
        for item in search_results:
            raw_url = str(item.get("url") or "")
            if "linkedin.com/in/" not in raw_url.lower():
                continue
            norm_url = normalize_linkedin_url(raw_url)
            if norm_url and _matches_person_linkedin(profile, norm_url, str(item.get("title") or "")):
                canonical_linkedin = norm_url
                break

    if not canonical_linkedin and extracted.linkedin_url:
        norm_ext = normalize_linkedin_url(extracted.linkedin_url)
        if norm_ext and _matches_person_linkedin(profile, norm_ext, ""):
            canonical_linkedin = norm_ext

    resolved_photo = extract_photo_url_from_results(
        search_results or [],
        linkedin_url=canonical_linkedin,
        full_name=profile.full_name,
    )

    return EnrichedProfile(
        bio=clean_bio,
        current_role=clean_role,
        current_company=clean_company,
        sector=clean_sector,
        location=clean_location,
        linkedin_url=canonical_linkedin,
        photo_url=resolved_photo,
        experiences=clean_exps,
        associations=clean_assos,
        passions=list(extracted.passions),
    )


class EnrichmentService:
    """Discover matching alumni on the web and enrich incomplete profiles with Tavily + Gemma 4."""

    def __init__(
        self,
        repository: AbstractAlumniRepository,
        llm_service: LLMServiceProtocol,
        graph_engine: GraphEngine,
        web_client: Optional[WebSearchClientProtocol] = None,
    ) -> None:
        self.repository = repository
        self.llm = llm_service
        self.graph_engine = graph_engine
        self.web_client = web_client or NullWebSearchClient()

    def is_web_enabled(self) -> bool:
        return not isinstance(self.web_client, NullWebSearchClient)

    @staticmethod
    def needs_enrichment(profile: ProfileRecord) -> bool:
        """Only enrich profiles without cached enrichment and without LinkedIn archive import."""
        return profile.last_enriched_at is None and not profile.has_imported_linkedin

    async def _call_web_search(
        self,
        query: str,
        *,
        max_results: int,
        include_domains: Optional[list[str]] = None,
        include_images: bool = False,
    ) -> list[dict]:
        """Call web_client.search cleanly while staying compatible with minimal 2-arg test mocks."""
        sig = inspect.signature(self.web_client.search)
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        kwargs: dict = {"query": query, "max_results": max_results}
        if include_domains and ("include_domains" in sig.parameters or has_varkw):
            kwargs["include_domains"] = include_domains
        if include_images and ("include_images" in sig.parameters or has_varkw):
            kwargs["include_images"] = True
        return await self.web_client.search(**kwargs)

    async def discover_candidates_via_web(
        self,
        parsed_query: ParsedQuery,
        raw_query: str,
        all_profiles: list[ProfileRecord],
        *,
        max_results_per_query: int = 20,
        timeout_seconds: float = 10.0,
    ) -> list[ProfileRecord]:
        """Search Tavily for CentraleSupélec alumni matching the query and match them against DB profiles."""
        if not self.is_web_enabled():
            return []

        companies = [c.strip() for c in parsed_query.target_companies if c.strip()]
        roles = [r.strip() for r in parsed_query.target_roles if r.strip()]
        sector = (parsed_query.target_sector or "").strip()
        keywords = _extract_query_keywords(raw_query)

        focus_terms = companies[:2] or roles[:2] or ([sector] if sector else keywords[:4])
        if not focus_terms:
            return []

        cohort_hint = _detect_dominant_cohort_hint(all_profiles)
        focus_str = " ".join(focus_terms)

        specs: list[tuple[str, Optional[list[str]], int]] = []
        if cohort_hint:
            specs.append((f"CentraleSupélec {cohort_hint} {focus_str}", ["linkedin.com"], max_results_per_query))
        specs.append((f"CentraleSupélec {focus_str}", ["linkedin.com"], max_results_per_query))
        specs.append((f'"CentraleSupélec" {cohort_hint} {focus_str}'.strip(), None, 10))

        # Deduplicate while keeping order, max 3 Tavily calls
        deduped_specs: list[tuple[str, Optional[list[str]], int]] = []
        seen_specs: set[tuple[str, tuple[str, ...]]] = set()
        for q, doms, max_r in specs:
            key = (q, tuple(doms or ()))
            if key not in seen_specs:
                seen_specs.add(key)
                deduped_specs.append((q, doms, max_r))
        deduped_specs = deduped_specs[:3]

        async def _run_search(q: str, doms: Optional[list[str]], max_r: int) -> list[dict]:
            try:
                return await asyncio.wait_for(
                    self._call_web_search(q, max_results=max_r, include_domains=doms),
                    timeout=timeout_seconds,
                )
            except Exception:
                return []

        batches = await asyncio.gather(*(_run_search(q, d, m) for q, d, m in deduped_specs))
        results = [item for batch in batches for item in batch]
        if not results:
            return []

        non_students = [p for p in all_profiles if not p.is_student]
        by_url: dict[str, ProfileRecord] = {}
        slug_index: dict[str, list[ProfileRecord]] = {}
        name_index: list[tuple[str, ProfileRecord]] = []

        for prof in non_students:
            norm_url = normalize_linkedin_url(prof.linkedin_url)
            if norm_url:
                by_url[norm_url] = prof
            norm_name, slugs = _build_name_slugs(prof.full_name)
            if " " in norm_name and len(norm_name) >= 5:
                name_index.append((norm_name, prof))
            for slug in slugs:
                slug_index.setdefault(slug, []).append(prof)

        hit_counts: dict[str, int] = {}
        prof_by_id: dict[str, ProfileRecord] = {p.id: p for p in non_students}

        for item in results:
            raw_url = str(item.get("url") or "")
            url_norm = normalize_linkedin_url(raw_url)
            if url_norm and url_norm in by_url:
                matched = by_url[url_norm]
                hit_counts[matched.id] = hit_counts.get(matched.id, 0) + 4

            if url_norm and "/in/" in url_norm:
                url_slug = url_norm.split("/in/", 1)[1].strip("/").lower()
                for candidate_slug, profs in slug_index.items():
                    if candidate_slug in url_slug and len(profs) == 1:
                        pid = profs[0].id
                        hit_counts[pid] = hit_counts.get(pid, 0) + 3

            haystack = re.sub(
                r"\s+",
                " ",
                strip_accents(f"{item.get('title', '')} {item.get('content', '')}").lower(),
            )
            for norm_name, prof in name_index:
                if norm_name in haystack:
                    if re.search(rf"(?<![a-z0-9]){re.escape(norm_name)}(?![a-z0-9])", haystack):
                        hit_counts[prof.id] = hit_counts.get(prof.id, 0) + 2

        ranked_ids = sorted(hit_counts.keys(), key=lambda pid: hit_counts[pid], reverse=True)
        return [prof_by_id[pid] for pid in ranked_ids[:12]]

    async def enrich_candidates(
        self,
        candidates: list[ProfileRecord],
        *,
        extra_terms: Optional[list[str]] = None,
        max_concurrency: int = 3,
        max_profiles: int = 6,
        timeout_seconds: float = 12.0,
    ) -> list[ProfileRecord]:
        """Concurrently enrich uncached candidates with Tavily + Gemma 4 and update DB + graph."""
        targets = [c for c in candidates if self.needs_enrichment(c)][:max_profiles]
        if not targets:
            return []

        semaphore = asyncio.Semaphore(max_concurrency)
        all_profiles = await self.repository.list_profiles()
        embedding_space = "vertex" if isinstance(self.llm, VertexLLMService) else "deterministic"

        async def _enrich_one(profile: ProfileRecord) -> Optional[ProfileRecord]:
            async with semaphore:
                company_hint = f' "{profile.current_company}"' if profile.current_company else ""
                extra = " ".join(extra_terms[:2]) if extra_terms else ""
                li_hint = "" if ("linkedin" in extra.lower() or company_hint) else " linkedin"
                query = f'"{profile.full_name}" CentraleSupélec{company_hint} {extra}{li_hint}'.strip()
                try:
                    results = await asyncio.wait_for(
                        self._call_web_search(query, max_results=4, include_images=True),
                        timeout=timeout_seconds,
                    )
                    results = _filter_results_for_person(profile, results)
                    if not results:
                        return None
                    snippets = "\n\n".join(
                        f"- [{r.get('title', '')}] ({r.get('url', '')}): {r.get('content', '')}"
                        for r in results
                    )
                    raw_extracted = await asyncio.wait_for(
                        self.llm.extract_profile_from_snippets(profile.full_name, snippets),
                        timeout=timeout_seconds,
                    )
                    extracted = _sanitize_extracted_career(profile, raw_extracted, results)
                    has_signal = any(
                        [
                            extracted.current_company,
                            extracted.current_role,
                            extracted.experiences,
                            extracted.linkedin_url,
                            extracted.bio,
                            extracted.location,
                            extracted.sector,
                            extracted.photo_url,
                        ]
                    )
                    if not has_signal:
                        return None
                    exp_dicts = [exp.model_dump() for exp in extracted.experiences]
                    resolved_company = extracted.current_company or profile.current_company
                    resolved_role = extracted.current_role or profile.current_role
                    if not resolved_company:
                        first_exp = next((e for e in exp_dicts if e.get("company")), None)
                        if first_exp:
                            resolved_company = first_exp.get("company")
                            resolved_role = resolved_role or first_exp.get("role")
                    resolved_sector = extracted.sector or profile.sector
                    resolved_location = extracted.location or profile.location
                    resolved_linkedin = extracted.linkedin_url or profile.linkedin_url
                    resolved_photo = extracted.photo_url or profile.photo_url
                    if not resolved_photo and resolved_linkedin:
                        resolved_photo = await fetch_og_image(resolved_linkedin, timeout_seconds=4.0)
                    has_image_provider = isinstance(self.web_client, TavilyWebSearchClient) or (
                        getattr(self.web_client, "tavily_fallback", None) is not None
                        and not getattr(self.web_client, "disable_tavily_fallback", False)
                    )
                    if not resolved_photo and resolved_company and has_image_provider:
                        try:
                            img_results = await asyncio.wait_for(
                                self._call_web_search(
                                    f'"{profile.full_name}" "{resolved_company}"',
                                    max_results=3,
                                    include_images=True,
                                ),
                                timeout=min(timeout_seconds, 6.0),
                            )
                            resolved_photo = extract_photo_url_from_results(
                                img_results,
                                linkedin_url=resolved_linkedin,
                                full_name=profile.full_name,
                            )
                        except Exception:
                            pass

                    preview = ProfileRecord(
                        id=profile.id,
                        full_name=profile.full_name,
                        linkedin_url=resolved_linkedin,
                        photo_url=resolved_photo,
                        promo_year=profile.promo_year,
                        current_role=resolved_role,
                        current_company=resolved_company,
                        sector=resolved_sector,
                        location=resolved_location,
                        bio=extracted.bio or profile.bio,
                        experiences=[*profile.experiences, *exp_dicts],
                        education=profile.education,
                        associations=list(dict.fromkeys([*profile.associations, *extracted.associations])),
                        passions=list(dict.fromkeys([*profile.passions, *extracted.passions])),
                    )
                    new_vec = (await self.llm.embed_texts([preview.searchable_text()]))[0]
                    source_tag = (
                        "WEB_FREE"
                        if getattr(self.web_client, "last_used_provider", None) == "free"
                        else "WEB_TAVILY"
                    )
                    updated = await self.repository.update_enrichment(
                        profile.id,
                        bio=extracted.bio,
                        experiences=exp_dicts,
                        associations=extracted.associations,
                        passions=extracted.passions,
                        embedding=new_vec,
                        current_role=extracted.current_role,
                        current_company=extracted.current_company,
                        sector=extracted.sector,
                        location=extracted.location,
                        linkedin_url=extracted.linkedin_url,
                        photo_url=resolved_photo,
                        embedding_space=embedding_space,
                        enrichment_source=source_tag,
                        enriched_at=datetime.now(timezone.utc),
                    )
                    if updated is None:
                        return None

                    new_edges = self.graph_engine.infer_edges_for_profile(updated, all_profiles)
                    if new_edges:
                        await self.repository.upsert_edges(new_edges)
                    self.graph_engine.upsert_node(updated)
                    self.graph_engine.upsert_edges(new_edges)
                    return updated
                except Exception:
                    return None

        enriched_results = await asyncio.gather(*(_enrich_one(p) for p in targets))
        return [res for res in enriched_results if res is not None]
