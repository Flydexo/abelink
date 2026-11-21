"""Polite free-first web search client (DuckDuckGo HTML/Lite + optional ddgs) with clean Tavily fallback."""

from __future__ import annotations

import asyncio
import html
import inspect
import random
import re
import time
from html.parser import HTMLParser
from typing import Any, Optional, Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.services.linkedin_parser import normalize_linkedin_url

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}

_CHALLENGE_MARKERS = (
    "anomaly-modal",
    "please complete the following challenge",
    "bots use duckduckgo",
    "g-recaptcha",
    "h-captcha",
    "cf-turnstile",
    "captcha",
)


class _SearchClientProtocol(Protocol):
    async def search(
        self,
        query: str,
        max_results: int = 4,
        include_domains: Optional[list[str]] = None,
        include_images: bool = False,
    ) -> list[dict]: ...


def unwrap_ddg_url(raw_url: str) -> str:
    """Unwrap DuckDuckGo /l/?uddg=... redirect links and normalize linkedin.com/in/ URLs."""
    cleaned = html.unescape((raw_url or "").strip())
    if not cleaned:
        return ""
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    elif cleaned.startswith("/l/?"):
        cleaned = "https://duckduckgo.com" + cleaned

    parsed = urlparse(cleaned)
    if "duckduckgo.com" in parsed.netloc.lower() and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        if uddg and uddg[0]:
            cleaned = unquote(uddg[0]).strip()

    low = cleaned.lower()
    if "linkedin.com/in/" in low:
        normalized = normalize_linkedin_url(cleaned)
        if normalized:
            return normalized
    return cleaned


def _is_challenge_page(status_code: int, body: str) -> bool:
    if status_code in (202, 403, 429, 503, 999):
        return True
    low = body.lower()
    return any(marker in low for marker in _CHALLENGE_MARKERS)


_PHOTO_REJECT_MARKERS = (
    "static.licdn.com",
    "licdn.com/sc/",
    "linkedin.com/sc/",
    "ghost-person",
    "ghost_person",
    "default-avatar",
    "favicon",
    "og-image-default",
    "/logo",
    "logo.",
    "company-logo",
    "school-logo",
    "organization-logo",
    "group-logo",
    "showcase-logo",
    "feedshare",
    "article-cover",
    "profile-displaybackgroundimage",
    "background-image",
    "banner",
)


def is_valid_profile_photo_url(url: Optional[str]) -> bool:
    """Return True if url looks like a real profile photo URL rather than a generic asset/placeholder."""
    if not url or not isinstance(url, str):
        return False
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")) or len(cleaned) > 1000:
        return False
    low = cleaned.lower()
    if low.endswith(".svg") or ".svg?" in low:
        return False
    return not any(marker in low for marker in _PHOTO_REJECT_MARKERS)


class _OgImageParser(HTMLParser):
    """Extract og:image / twitter:image meta tag content from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_image: Optional[str] = None
        self.twitter_image: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "meta":
            return
        attr_map = {k.lower(): (v or "").strip() for k, v in attrs}
        prop = attr_map.get("property", "").lower()
        name = attr_map.get("name", "").lower()
        content = html.unescape(attr_map.get("content", "")).strip()
        if not content:
            return
        if prop in ("og:image", "og:image:secure_url") and not self.og_image:
            self.og_image = content
        elif name in ("twitter:image", "twitter:image:src") and not self.twitter_image:
            self.twitter_image = content


async def fetch_og_image(
    url: str,
    *,
    timeout_seconds: float = 5.0,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Optional[str]:
    """Politely fetch og:image from a public page; returns None on any authwall, challenge, or error."""
    if not url or not url.startswith(("http://", "https://")):
        return None

    async def _get(client: httpx.AsyncClient) -> Optional[str]:
        try:
            resp = await client.get(url)
        except Exception:
            return None
        final_url = str(resp.url).lower()
        if "authwall" in final_url or "/login" in final_url or "/checkpoint" in final_url:
            return None
        if resp.status_code != 200 or _is_challenge_page(resp.status_code, resp.text):
            return None
        parser = _OgImageParser()
        try:
            parser.feed(resp.text[:150_000])
            parser.close()
        except Exception:
            return None
        for candidate in (parser.og_image, parser.twitter_image):
            if is_valid_profile_photo_url(candidate):
                return candidate
        return None

    if http_client is not None:
        return await _get(http_client)

    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=_DEFAULT_HEADERS,
    ) as client:
        return await _get(client)


def _url_matches_person_name(url: str, full_name: Optional[str]) -> bool:
    if not full_name:
        return False
    import unicodedata

    norm_name = unicodedata.normalize("NFKD", full_name)
    norm_name = "".join(ch for ch in norm_name if not unicodedata.combining(ch)).lower()
    tokens = [t for t in re.findall(r"[a-z0-9]{2,}", norm_name)]
    if len(tokens) < 2:
        return False
    low_url = url.lower()
    return tokens[0] in low_url and tokens[-1] in low_url


def extract_photo_url_from_results(
    results: list[dict[str, Any]],
    *,
    linkedin_url: Optional[str] = None,
    full_name: Optional[str] = None,
) -> Optional[str]:
    """Pick the best verified profile photo URL from search results (never arbitrary non-profile assets)."""
    li_slug_norm = linkedin_url.rstrip("/").lower() if linkedin_url else None
    li_candidates: list[str] = []
    other_li_images: list[str] = []
    name_matched_images: list[str] = []

    for item in results:
        if not isinstance(item, dict):
            continue
        item_url = str(item.get("url") or "").strip().lower()
        matches_target_li = bool(li_slug_norm and li_slug_norm in item_url)
        is_li_item = matches_target_li or ("linkedin.com/in/" in item_url and li_slug_norm is None)

        for key in ("photo_url", "image_url"):
            val = item.get(key)
            if isinstance(val, str) and is_valid_profile_photo_url(val):
                if is_li_item:
                    return val.strip()

        raw_images = item.get("images")
        if isinstance(raw_images, list):
            for img in raw_images:
                img_url = img.get("url") if isinstance(img, dict) else img
                if isinstance(img_url, str) and is_valid_profile_photo_url(img_url):
                    cleaned_img = img_url.strip()
                    if is_li_item:
                        li_candidates.append(cleaned_img)
                    elif "profile-displayphoto" in cleaned_img.lower():
                        other_li_images.append(cleaned_img)
                    elif _url_matches_person_name(cleaned_img, full_name):
                        name_matched_images.append(cleaned_img)

    for pool in (li_candidates, other_li_images, name_matched_images):
        for cand in pool:
            if "profile-displayphoto" in cand.lower():
                return cand
        for cand in pool:
            if "media.licdn.com/dms/image" in cand.lower():
                return cand
        for cand in pool:
            if "licdn.com" in cand.lower():
                return cand
        if pool is name_matched_images and pool:
            return pool[0]
    return None


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


class _DuckDuckGoHTMLParser(HTMLParser):
    """Extract results from DuckDuckGo HTML or Lite pages without external dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._current_href = ""
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._pending: Optional[dict[str, str]] = None

    def _flush_pending(self) -> None:
        if self._pending and self._pending.get("url") and self._pending.get("title"):
            self.results.append(self._pending)
        self._pending = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        classes = set(attr_map.get("class", "").split())

        if tag == "a" and ("result__a" in classes or "result-link" in classes):
            self._flush_pending()
            self._in_title = True
            self._current_href = attr_map.get("href", "")
            self._title_parts = []
        elif tag in ("a", "div", "td", "span") and (
            "result__snippet" in classes or "result-snippet" in classes
        ):
            self._in_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            title = _clean_whitespace("".join(self._title_parts))
            url = unwrap_ddg_url(self._current_href)
            if title and url and not url.startswith("/"):
                self._pending = {"title": title, "url": url, "content": ""}
            else:
                self._pending = None
        elif self._in_snippet and tag in ("a", "div", "td", "span"):
            self._in_snippet = False
            snippet = _clean_whitespace("".join(self._snippet_parts))
            if self._pending is not None:
                self._pending["content"] = snippet
                self._flush_pending()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush_pending()


def parse_duckduckgo_results(
    html_text: str,
    *,
    max_results: int = 4,
    include_domains: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML or Lite markup into [{title, url, content}]."""
    if not html_text:
        return []
    parser = _DuckDuckGoHTMLParser()
    parser.feed(html_text)
    parser.close()

    domain_filters = [d.lower().lstrip(".") for d in (include_domains or []) if d.strip()]
    deduped: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in parser.results:
        url = item["url"]
        if not url.startswith(("http://", "https://")):
            continue
        host = urlparse(url).netloc.lower()
        if "duckduckgo.com" in host:
            continue
        if domain_filters and not any(d in host for d in domain_filters):
            continue
        norm_key = url.rstrip("/").lower()
        if norm_key in seen_urls:
            continue
        seen_urls.add(norm_key)
        deduped.append(item)
        if len(deduped) >= max_results:
            break
    return deduped


def _apply_domain_filter(query: str, include_domains: Optional[list[str]]) -> str:
    if not include_domains or "site:" in query.lower():
        return query
    cleaned = [d.strip() for d in include_domains if d.strip()]
    if not cleaned:
        return query
    if len(cleaned) == 1:
        return f"{query} site:{cleaned[0]}"
    clauses = " OR ".join(f"site:{d}" for d in cleaned)
    return f"{query} ({clauses})"


class FreeFirstWebSearchClient:
    """Free-first search via polite DuckDuckGo HTML/Lite (or optional ddgs) with Tavily fallback."""

    def __init__(
        self,
        *,
        tavily_fallback: Optional[_SearchClientProtocol] = None,
        disable_tavily_fallback: bool = False,
        max_concurrency: int = 2,
        timeout_seconds: float = 10.0,
        jitter_range: tuple[float, float] = (0.15, 0.45),
        http_client: Optional[httpx.AsyncClient] = None,
        try_ddgs: bool = True,
        ddg_challenge_cooldown_seconds: float = 600.0,
    ) -> None:
        self.tavily_fallback = tavily_fallback
        self.disable_tavily_fallback = disable_tavily_fallback
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self.timeout_seconds = timeout_seconds
        self.jitter_range = jitter_range
        self._http_client = http_client
        self.try_ddgs = try_ddgs
        self.ddg_challenge_cooldown_seconds = max(0.0, float(ddg_challenge_cooldown_seconds))
        self._ddg_blocked_until: float = 0.0
        self.free_hits: int = 0
        self.tavily_fallbacks: int = 0
        self.last_used_provider: str = "none"

    @property
    def provider_label(self) -> str:
        return "free_first"

    async def _fetch_ddg_endpoint(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        query: str,
        *,
        max_results: int,
        include_domains: Optional[list[str]],
    ) -> tuple[list[dict[str, str]], bool]:
        """Return (results, was_challenged)."""
        try:
            resp = await client.post(endpoint, data={"q": query, "kl": "fr-fr"})
        except Exception:
            return [], False
        if _is_challenge_page(resp.status_code, resp.text):
            return [], True
        if resp.status_code != 200:
            return [], False
        parsed = parse_duckduckgo_results(
            resp.text,
            max_results=max_results,
            include_domains=include_domains,
        )
        return parsed, False

    async def _search_via_httpx(
        self,
        effective_query: str,
        *,
        max_results: int,
        include_domains: Optional[list[str]],
    ) -> list[dict[str, str]]:
        async def _run_with(client: httpx.AsyncClient) -> list[dict[str, str]]:
            results, challenged = await self._fetch_ddg_endpoint(
                client,
                _DDG_HTML_URL,
                effective_query,
                max_results=max_results,
                include_domains=include_domains,
            )
            if challenged:
                self._ddg_blocked_until = time.monotonic() + self.ddg_challenge_cooldown_seconds
                return []
            if results:
                return results
            results_lite, challenged_lite = await self._fetch_ddg_endpoint(
                client,
                _DDG_LITE_URL,
                effective_query,
                max_results=max_results,
                include_domains=include_domains,
            )
            if challenged_lite:
                self._ddg_blocked_until = time.monotonic() + self.ddg_challenge_cooldown_seconds
                return []
            return results_lite

        if self._http_client is not None:
            return await _run_with(self._http_client)

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers=_DEFAULT_HEADERS,
        ) as client:
            return await _run_with(client)

    def _search_via_ddgs_sync(
        self,
        effective_query: str,
        *,
        max_results: int,
        include_domains: Optional[list[str]],
    ) -> list[dict[str, str]]:
        try:
            from ddgs import DDGS  # type: ignore[import-not-found]
        except ImportError:
            return []

        try:
            raw_items = list(DDGS().text(effective_query, max_results=max_results))
        except Exception:
            return []

        domain_filters = [d.lower().lstrip(".") for d in (include_domains or []) if d.strip()]
        out: list[dict[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            url = unwrap_ddg_url(str(item.get("href") or item.get("url") or ""))
            title = _clean_whitespace(str(item.get("title") or ""))
            content = _clean_whitespace(str(item.get("body") or item.get("content") or ""))
            if not url or not title:
                continue
            host = urlparse(url).netloc.lower()
            if domain_filters and not any(d in host for d in domain_filters):
                continue
            out.append({"title": title, "url": url, "content": content})
            if len(out) >= max_results:
                break
        return out

    async def _call_tavily_fallback(
        self,
        query: str,
        *,
        max_results: int,
        include_domains: Optional[list[str]],
        include_images: bool = False,
    ) -> list[dict[str, Any]]:
        if self.tavily_fallback is None or self.disable_tavily_fallback:
            return []
        self.tavily_fallbacks += 1
        self.last_used_provider = "tavily"
        sig = inspect.signature(self.tavily_fallback.search)
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        kwargs: dict[str, Any] = {"query": query, "max_results": max_results}
        if include_domains and ("include_domains" in sig.parameters or has_varkw):
            kwargs["include_domains"] = include_domains
        if include_images and ("include_images" in sig.parameters or has_varkw):
            kwargs["include_images"] = True
        return await self.tavily_fallback.search(**kwargs)

    async def search(
        self,
        query: str,
        max_results: int = 4,
        include_domains: Optional[list[str]] = None,
        include_images: bool = False,
    ) -> list[dict]:
        """Search free DDG HTML/Lite first (polite semaphore + jitter), falling back to Tavily only on empty/failure."""
        if time.monotonic() < self._ddg_blocked_until:
            return await self._call_tavily_fallback(
                query,
                max_results=max_results,
                include_domains=include_domains,
                include_images=include_images,
            )

        effective_query = _apply_domain_filter(query, include_domains)
        results: list[dict[str, Any]] = []

        blocked = False
        async with self._semaphore:
            if time.monotonic() < self._ddg_blocked_until:
                blocked = True
            else:
                lo, hi = self.jitter_range
                if hi > 0:
                    await asyncio.sleep(random.uniform(max(0.0, lo), hi))

                results = await self._search_via_httpx(
                    effective_query,
                    max_results=max_results,
                    include_domains=include_domains,
                )
                if (
                    not results
                    and time.monotonic() >= self._ddg_blocked_until
                    and self.try_ddgs
                    and self._http_client is None
                ):
                    results = await asyncio.to_thread(
                        self._search_via_ddgs_sync,
                        effective_query,
                        max_results=max_results,
                        include_domains=include_domains,
                    )

        if not blocked and results:
            self.free_hits += 1
            self.last_used_provider = "free"
            return results

        return await self._call_tavily_fallback(
            query,
            max_results=max_results,
            include_domains=include_domains,
            include_images=include_images,
        )
