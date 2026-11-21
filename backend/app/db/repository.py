"""Repository abstraction with PostgreSQL/pgvector and InMemory implementations."""

from __future__ import annotations

import math
import unicodedata
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import islice
from typing import Any, Optional, Protocol

import numpy as np
from anyio import to_thread
from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.enrichment_cache import EnrichmentCache
from app.db.models import ApiTokenORM, EdgeORM, ProfileORM
from app.schemas.profile import Education, Experience, ProfileRead, ProfileSummary
from app.schemas.search import ParsedQuery, SearchFilters


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return ascii_only.lower().strip()


def _format_short_meta(
    company: Optional[str],
    role: Optional[str],
    promo_year: Optional[int],
) -> str:
    parts: list[str] = []
    if company:
        parts.append(company)
    elif role:
        parts.append(role)
    if promo_year:
        parts.append(f"Promo {promo_year}")
    return " · ".join(parts)


@dataclass
class ProfileRecord:
    id: str
    full_name: str
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    photo_url: Optional[str] = None
    promo_year: Optional[int] = None
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    sector: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    experiences: list[dict[str, Any]] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    associations: list[str] = field(default_factory=list)
    passions: list[str] = field(default_factory=list)
    is_student: bool = False
    has_imported_linkedin: bool = False
    enrichment_source: str = "BASE_DB"
    last_enriched_at: Optional[datetime] = None
    embedding: Optional[list[float]] = None
    embedding_space: str = "deterministic"

    def to_profile_summary(self) -> ProfileSummary:
        return ProfileSummary(
            id=self.id,
            full_name=self.full_name,
            promo_year=self.promo_year,
            current_role=self.current_role,
            current_company=self.current_company,
            sector=self.sector,
            location=self.location,
            photo_url=self.photo_url,
            short_meta=_format_short_meta(self.current_company, self.current_role, self.promo_year),
        )

    def to_profile_read(self) -> ProfileRead:
        return ProfileRead(
            id=self.id,
            full_name=self.full_name,
            email=self.email,
            linkedin_url=self.linkedin_url,
            photo_url=self.photo_url,
            promo_year=self.promo_year,
            current_role=self.current_role,
            current_company=self.current_company,
            sector=self.sector,
            location=self.location,
            bio=self.bio,
            experiences=[Experience.model_validate(e) for e in self.experiences],
            education=[Education.model_validate(e) for e in self.education],
            associations=list(self.associations),
            passions=list(self.passions),
            is_student=self.is_student,
            has_imported_linkedin=self.has_imported_linkedin,
            enrichment_source=self.enrichment_source,
            last_enriched_at=self.last_enriched_at,
        )

    def searchable_text(self) -> str:
        exp_parts = [
            f"{e.get('role', '')} chez {e.get('company', '')} ({e.get('period') or e.get('start_date') or ''})"
            for e in self.experiences
        ]
        edu_parts = [f"{ed.get('school', '')} {ed.get('degree', '')}" for ed in self.education]
        parts = [
            self.full_name,
            self.current_role or "",
            self.current_company or "",
            self.sector or "",
            self.location or "",
            f"CentraleSupélec promo {self.promo_year}" if self.promo_year else "CentraleSupélec",
            self.bio or "",
            " ".join(exp_parts),
            " ".join(edu_parts),
            f"Associations: {', '.join(self.associations)}" if self.associations else "",
            f"Passions: {', '.join(self.passions)}" if self.passions else "",
        ]
        return " | ".join(p.strip() for p in parts if p and p.strip())


@dataclass
class EdgeRecord:
    source_id: str
    target_id: str
    edge_type: str
    probability: float
    reason: str
    id: Optional[str] = None


@dataclass
class ApiTokenRecord:
    id: str
    profile_id: str
    token_hash: str
    label: str
    created_at: datetime
    last_used_at: Optional[datetime] = None


@dataclass
class SearchCandidate:
    profile: ProfileRecord
    hybrid_score: float
    semantic_score: float


class AbstractAlumniRepository(Protocol):
    async def get_profile(self, profile_id: str) -> Optional[ProfileRecord]: ...

    async def get_profile_by_email_or_id(self, identifier: str) -> Optional[ProfileRecord]: ...

    async def get_profile_by_linkedin_url(self, linkedin_url: str) -> Optional[ProfileRecord]: ...

    async def list_profiles(self, limit: Optional[int] = None) -> list[ProfileRecord]: ...

    async def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord: ...

    async def update_enrichment(
        self,
        profile_id: str,
        *,
        bio: str,
        experiences: list[dict[str, Any]],
        associations: list[str],
        passions: list[str],
        embedding: list[float],
        current_role: Optional[str] = None,
        current_company: Optional[str] = None,
        sector: Optional[str] = None,
        location: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        photo_url: Optional[str] = None,
        embedding_space: str = "deterministic",
        enrichment_source: str = "WEB_TAVILY",
        enriched_at: Optional[datetime] = None,
    ) -> Optional[ProfileRecord]: ...

    async def count_enriched_profiles(self) -> int: ...

    async def list_edges(self) -> list[EdgeRecord]: ...

    async def upsert_edges(self, edges: list[EdgeRecord]) -> int: ...

    async def import_linkcs_records(
        self, profiles: list[ProfileRecord], edges: list[EdgeRecord]
    ) -> tuple[int, int]: ...

    async def hybrid_search_alumni(
        self,
        query_embedding: list[float],
        parsed_query: ParsedQuery,
        *,
        filters: Optional[SearchFilters] = None,
        exclude_profile_id: Optional[str] = None,
        limit: int = 20,
        raw_query: str = "",
        vertex_query_embedding: Optional[list[float]] = None,
    ) -> list[SearchCandidate]: ...

    async def create_api_token(self, profile_id: str, token_hash: str, label: str) -> ApiTokenRecord: ...

    async def list_api_tokens(self, profile_id: str) -> list[ApiTokenRecord]: ...

    async def delete_api_token(self, token_id: str, profile_id: str) -> bool: ...

    async def resolve_api_token(self, token_hash: str) -> Optional[str]: ...

    async def health_check(self) -> dict[str, Any]: ...


def _compute_metadata_boost(
    profile: ProfileRecord,
    parsed_query: ParsedQuery,
    filters: Optional[SearchFilters],
    worked_with_neighbor_ids: set[str],
) -> float:
    boost = 0.0
    sector_text = _normalize_text(profile.sector)
    company_text = _normalize_text(profile.current_company)
    role_text = _normalize_text(profile.current_role)
    searchable = _normalize_text(profile.searchable_text())

    target_sector = _normalize_text((filters.sector if filters else None) or parsed_query.target_sector)
    if target_sector:
        sector_tokens = [tok for tok in target_sector.replace("/", " ").split() if len(tok) > 1]
        if target_sector in sector_text or (sector_tokens and any(tok in sector_text for tok in sector_tokens)):
            boost += 0.25
        elif sector_tokens and any(tok in searchable for tok in sector_tokens):
            boost += 0.12

    companies = (filters.companies if filters and filters.companies else parsed_query.target_companies) or []
    for comp in companies:
        norm_comp = _normalize_text(comp)
        if norm_comp and (norm_comp in company_text or norm_comp in searchable):
            boost += 0.28
            break

    roles = (filters.roles if filters and filters.roles else parsed_query.target_roles) or []
    for role in roles:
        norm_role = _normalize_text(role)
        if norm_role and (norm_role in role_text or norm_role in searchable):
            boost += 0.22
            break

    worked_with = _normalize_text((filters.worked_with if filters else None) or parsed_query.worked_with)
    if worked_with:
        exp_companies = " ".join(_normalize_text(e.get("company")) for e in profile.experiences)
        if worked_with in exp_companies or worked_with in searchable or profile.id in worked_with_neighbor_ids:
            boost += 0.30

    return min(boost, 0.85)


def _cosine_sim(vec_a: Optional[list[float]], vec_b: Optional[list[float]]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 0.0:
        return 0.0
    return max(0.0, min(1.0, float(np.dot(a, b) / denom)))


def _lexical_overlap_score(searchable: str, terms: list[str]) -> float:
    if not terms or not searchable:
        return 0.0
    hits = sum(1 for t in terms if t and t in searchable)
    return min(0.35, 0.08 * hits)


class InMemoryAlumniRepository:
    """In-memory repository for unit tests, API/MCP integration tests, and demo mode."""

    def __init__(self, enrichment_cache: Optional[EnrichmentCache] = None) -> None:
        self.profiles: dict[str, ProfileRecord] = {}
        self.edges: dict[tuple[str, str, str], EdgeRecord] = {}
        self.tokens: dict[str, ApiTokenRecord] = {}
        self._enrichment_cache = enrichment_cache

    def apply_cached_enrichment(self, cache: Optional[EnrichmentCache] = None) -> int:
        """Merge cached enrichments and 768-dim embeddings from SQLite into loaded profiles."""
        target_cache = cache or self._enrichment_cache
        if target_cache is None:
            return 0
        cached_rows = target_cache.load_all()
        if not cached_rows:
            return 0

        by_name: dict[str, list[dict[str, Any]]] = {}
        for row in cached_rows.values():
            norm_name = " ".join(_normalize_text(row.get("full_name_norm")).split())
            if norm_name:
                by_name.setdefault(norm_name, []).append(row)

        applied = 0
        for profile in self.profiles.values():
            entry = cached_rows.get(profile.id)
            if entry is None:
                name_key = " ".join(_normalize_text(profile.full_name).split())
                matches = by_name.get(name_key, [])
                if len(matches) == 1:
                    entry = matches[0]
            if not entry or not entry.get("last_enriched_at"):
                continue

            cached_bio = entry.get("bio")
            if cached_bio and (not profile.bio or len(cached_bio) > len(profile.bio)):
                profile.bio = cached_bio

            if entry.get("current_company") and not profile.current_company:
                profile.current_company = entry["current_company"]
            if entry.get("current_role") and not profile.current_role:
                profile.current_role = entry["current_role"]
            if entry.get("sector") and not profile.sector:
                profile.sector = entry["sector"]
            if entry.get("location") and not profile.location:
                profile.location = entry["location"]
            if entry.get("linkedin_url") and not profile.linkedin_url:
                profile.linkedin_url = entry["linkedin_url"]
            if entry.get("photo_url") and not profile.photo_url:
                profile.photo_url = entry["photo_url"]

            existing_exps = {
                (_normalize_text(e.get("company")), _normalize_text(e.get("role")))
                for e in profile.experiences
            }
            for exp in entry.get("experiences") or []:
                if not isinstance(exp, dict):
                    continue
                key = (_normalize_text(exp.get("company")), _normalize_text(exp.get("role")))
                if key not in existing_exps and exp.get("company"):
                    profile.experiences.append(exp)
                    existing_exps.add(key)

            existing_assos = {_normalize_text(a) for a in profile.associations}
            for asso in entry.get("associations") or []:
                k = _normalize_text(asso)
                if k and k not in existing_assos:
                    profile.associations.append(asso)
                    existing_assos.add(k)

            existing_passions = {_normalize_text(p) for p in profile.passions}
            for passion in entry.get("passions") or []:
                k = _normalize_text(passion)
                if k and k not in existing_passions:
                    profile.passions.append(passion)
                    existing_passions.add(k)

            emb = entry.get("embedding")
            if isinstance(emb, list) and emb:
                profile.embedding = [float(v) for v in emb]
                profile.embedding_space = entry.get("embedding_space") or profile.embedding_space

            profile.enrichment_source = entry.get("enrichment_source") or profile.enrichment_source
            try:
                parsed_dt = datetime.fromisoformat(str(entry["last_enriched_at"]))
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                profile.last_enriched_at = parsed_dt
            except Exception:
                profile.last_enriched_at = datetime.now(timezone.utc)
            applied += 1
        return applied

    async def get_profile(self, profile_id: str) -> Optional[ProfileRecord]:
        return self.profiles.get(str(profile_id))

    async def get_profile_by_email_or_id(self, identifier: str) -> Optional[ProfileRecord]:
        ident = identifier.strip()
        if ident in self.profiles:
            return self.profiles[ident]
        lowered = ident.lower()
        for profile in self.profiles.values():
            if profile.email and profile.email.lower() == lowered:
                return profile
        norm_ident = _normalize_text(ident)
        for profile in self.profiles.values():
            if _normalize_text(profile.full_name) == norm_ident:
                return profile
        return None

    async def get_profile_by_linkedin_url(self, linkedin_url: str) -> Optional[ProfileRecord]:
        norm = linkedin_url.strip().rstrip("/").lower()
        for profile in self.profiles.values():
            if profile.linkedin_url and profile.linkedin_url.strip().rstrip("/").lower() == norm:
                return profile
        return None

    async def list_profiles(self, limit: Optional[int] = None) -> list[ProfileRecord]:
        items = list(self.profiles.values())
        return items[:limit] if limit is not None else items

    async def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord:
        if not profile.id:
            profile.id = str(uuid.uuid4())
        self.profiles[profile.id] = profile
        return profile

    async def import_linkcs_records(
        self, profiles: list[ProfileRecord], edges: list[EdgeRecord]
    ) -> tuple[int, int]:
        known_urls = {profile.linkedin_url for profile in self.profiles.values() if profile.linkedin_url}
        additions = [profile for profile in profiles if profile.id not in self.profiles]
        if any(profile.linkedin_url in known_urls for profile in additions if profile.linkedin_url):
            raise ValueError("Un profil existe déjà avec cette URL LinkedIn ; réessayez l’import.")
        valid_ids = set(self.profiles) | {profile.id for profile in additions}
        if any(edge.source_id not in valid_ids or edge.target_id not in valid_ids for edge in edges):
            raise ValueError("Une relation référence un profil inconnu.")
        new_edges = {
            (edge.source_id, edge.target_id, edge.edge_type): edge
            for edge in edges
            if (edge.source_id, edge.target_id, edge.edge_type) not in self.edges
        }
        self.profiles.update({profile.id: profile for profile in additions})
        self.edges.update(new_edges)
        return len(additions), len(new_edges)

    async def update_enrichment(
        self,
        profile_id: str,
        *,
        bio: str,
        experiences: list[dict[str, Any]],
        associations: list[str],
        passions: list[str],
        embedding: list[float],
        current_role: Optional[str] = None,
        current_company: Optional[str] = None,
        sector: Optional[str] = None,
        location: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        photo_url: Optional[str] = None,
        embedding_space: str = "deterministic",
        enrichment_source: str = "WEB_TAVILY",
        enriched_at: Optional[datetime] = None,
    ) -> Optional[ProfileRecord]:
        profile = self.profiles.get(profile_id)
        if profile is None:
            return None

        if bio and (not profile.bio or len(bio) > len(profile.bio)):
            profile.bio = bio

        existing_exps = {
            (_normalize_text(e.get("company")), _normalize_text(e.get("role")))
            for e in profile.experiences
        }
        for exp in experiences:
            key = (_normalize_text(exp.get("company")), _normalize_text(exp.get("role")))
            if key not in existing_exps and exp.get("company"):
                profile.experiences.append(exp)
                existing_exps.add(key)

        if current_company and not profile.current_company:
            profile.current_company = current_company
        if current_role and not profile.current_role:
            profile.current_role = current_role
        if sector and not profile.sector:
            profile.sector = sector
        if location and not profile.location:
            profile.location = location
        if linkedin_url and not profile.linkedin_url:
            profile.linkedin_url = linkedin_url
        if photo_url and not profile.photo_url:
            profile.photo_url = photo_url

        if not profile.current_company:
            first_with_company = next((e for e in profile.experiences if e.get("company")), None)
            if first_with_company:
                profile.current_company = first_with_company.get("company")
                if not profile.current_role and first_with_company.get("role"):
                    profile.current_role = first_with_company.get("role")

        existing_assos = {_normalize_text(a): a for a in profile.associations}
        for asso in associations:
            k = _normalize_text(asso)
            if k and k not in existing_assos:
                profile.associations.append(asso)
                existing_assos[k] = asso

        existing_passions = {_normalize_text(p): p for p in profile.passions}
        for passion in passions:
            k = _normalize_text(passion)
            if k and k not in existing_passions:
                profile.passions.append(passion)
                existing_passions[k] = passion

        profile.embedding = list(embedding)
        profile.embedding_space = embedding_space
        profile.enrichment_source = enrichment_source
        profile.last_enriched_at = enriched_at or datetime.now(timezone.utc)
        if self._enrichment_cache is not None:
            self._enrichment_cache.save_profile(profile)
        return profile

    async def count_enriched_profiles(self) -> int:
        return sum(1 for p in self.profiles.values() if p.last_enriched_at is not None)

    async def list_edges(self) -> list[EdgeRecord]:
        return list(self.edges.values())

    async def upsert_edges(self, edges: list[EdgeRecord]) -> int:
        count = 0
        for edge in edges:
            if edge.source_id == edge.target_id:
                continue
            key = (edge.source_id, edge.target_id, edge.edge_type)
            if not edge.id:
                edge.id = str(uuid.uuid4())
            self.edges[key] = edge
            count += 1
        return count

    async def hybrid_search_alumni(
        self,
        query_embedding: list[float],
        parsed_query: ParsedQuery,
        *,
        filters: Optional[SearchFilters] = None,
        exclude_profile_id: Optional[str] = None,
        limit: int = 20,
        raw_query: str = "",
        vertex_query_embedding: Optional[list[float]] = None,
    ) -> list[SearchCandidate]:
        worked_with_norm = _normalize_text((filters.worked_with if filters else None) or parsed_query.worked_with)
        worked_with_neighbors: set[str] = set()
        if worked_with_norm:
            matched_person_ids = {
                p.id for p in self.profiles.values() if worked_with_norm in _normalize_text(p.full_name)
            }
            for edge in self.edges.values():
                if edge.source_id in matched_person_ids:
                    worked_with_neighbors.add(edge.target_id)
                if edge.target_id in matched_person_ids:
                    worked_with_neighbors.add(edge.source_id)

        lexical_terms = list(
            dict.fromkeys(
                tok
                for tok in _normalize_text(
                    " ".join(
                        [
                            parsed_query.target_sector or "",
                            " ".join(parsed_query.target_companies),
                            " ".join(parsed_query.target_roles),
                            parsed_query.worked_with or "",
                            " ".join(parsed_query.icebreakers),
                            parsed_query.summary_label or "",
                            parsed_query.intent or "",
                            raw_query or "",
                        ]
                    )
                ).split()
                if len(tok) > 2
            )
        )

        promo_min = filters.promo_min if filters else None
        promo_max = filters.promo_max if filters else None

        candidates: list[SearchCandidate] = []
        for profile in self.profiles.values():
            if exclude_profile_id and profile.id == exclude_profile_id:
                continue
            if profile.is_student:
                continue
            if promo_min is not None and (profile.promo_year is None or profile.promo_year < promo_min):
                continue
            if promo_max is not None and (profile.promo_year is None or profile.promo_year > promo_max):
                continue

            target_qvec = (
                vertex_query_embedding
                if profile.embedding_space == "vertex" and vertex_query_embedding is not None
                else query_embedding
            )
            sem = _cosine_sim(target_qvec, profile.embedding) if profile.embedding else 0.25
            lex = _lexical_overlap_score(_normalize_text(profile.searchable_text()), lexical_terms)
            meta_boost = _compute_metadata_boost(profile, parsed_query, filters, worked_with_neighbors)
            hybrid = 0.65 * sem + lex + meta_boost
            candidates.append(SearchCandidate(profile=profile, hybrid_score=hybrid, semantic_score=sem))

        candidates.sort(key=lambda c: c.hybrid_score, reverse=True)
        return candidates[:limit]

    async def create_api_token(self, profile_id: str, token_hash: str, label: str) -> ApiTokenRecord:
        record = ApiTokenRecord(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            token_hash=token_hash,
            label=label,
            created_at=datetime.now(timezone.utc),
        )
        self.tokens[record.id] = record
        return record

    async def list_api_tokens(self, profile_id: str) -> list[ApiTokenRecord]:
        return [t for t in self.tokens.values() if t.profile_id == profile_id]

    async def delete_api_token(self, token_id: str, profile_id: str) -> bool:
        tok = self.tokens.get(token_id)
        if tok and tok.profile_id == profile_id:
            del self.tokens[token_id]
            return True
        return False

    async def resolve_api_token(self, token_hash: str) -> Optional[str]:
        for tok in self.tokens.values():
            if tok.token_hash == token_hash:
                tok.last_used_at = datetime.now(timezone.utc)
                return tok.profile_id
        return None

    async def health_check(self) -> dict[str, Any]:
        return {"backend": "in_memory", "ok": True, "profiles": len(self.profiles), "edges": len(self.edges)}


def _orm_to_record(row: ProfileORM) -> ProfileRecord:
    emb: Optional[list[float]] = None
    if row.embedding is not None:
        emb = [float(x) for x in row.embedding]
    return ProfileRecord(
        id=str(row.id),
        full_name=row.full_name,
        email=row.email,
        linkedin_url=row.linkedin_url,
        photo_url=row.photo_url,
        promo_year=row.promo_year,
        current_role=row.current_role,
        current_company=row.current_company,
        sector=row.sector,
        location=row.location,
        bio=row.bio,
        experiences=list(row.experiences or []),
        education=list(row.education or []),
        associations=list(row.associations or []),
        passions=list(row.passions or []),
        is_student=bool(row.is_student),
        has_imported_linkedin=bool(row.has_imported_linkedin),
        enrichment_source=row.enrichment_source,
        last_enriched_at=row.last_enriched_at,
        embedding=emb,
    )


class PostgresAlumniRepository:
    """Async PostgreSQL + pgvector repository."""

    def __init__(self, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.engine = engine
        self.session_factory = session_factory

    async def import_bundle_records(self, records: Iterator[ProfileRecord | EdgeRecord]) -> tuple[int, int, int]:
        """Insert the ordered bundle in one transaction without replacing stored rows."""
        profiles_seen = profiles_added = edges_added = 0
        profile_insert = pg_insert(ProfileORM).on_conflict_do_nothing().returning(ProfileORM.id)
        remapped_ids: dict[uuid.UUID, uuid.UUID] = {}
        edge_insert = pg_insert(EdgeORM).on_conflict_do_nothing(
            index_elements=[EdgeORM.source_id, EdgeORM.target_id, EdgeORM.edge_type]
        )
        async with self.session_factory() as session, session.begin():
            while batch := await to_thread.run_sync(lambda: list(islice(records, 32))):
                profiles, edges = [], []
                for record in batch:
                    if isinstance(record, ProfileRecord):
                        row = vars(record).copy()
                        row.pop("embedding_space")
                        row["id"] = uuid.UUID(record.id)
                        profiles.append(row)
                    else:
                        row = asdict(record)
                        row["id"] = uuid.UUID(record.id) if record.id else uuid.uuid4()
                        edges.append(row)
                if profiles:
                    profiles_seen += len(profiles)
                    result = await session.execute(profile_insert, profiles)
                    inserted_ids = set(result.scalars().all())
                    profiles_added += len(inserted_ids)
                    skipped = [row for row in profiles if row["id"] not in inserted_ids]
                    if skipped:
                        matches = await session.execute(select(ProfileORM.id, ProfileORM.linkedin_url).where(or_(
                            ProfileORM.id.in_({row["id"] for row in skipped}),
                            ProfileORM.linkedin_url.in_({row["linkedin_url"] for row in skipped if row["linkedin_url"] is not None}),
                        )))
                        existing_ids = set(inserted_ids)
                        ids_by_url = {}
                        for existing_id, url in matches:
                            existing_ids.add(existing_id)
                            if url is not None:
                                ids_by_url[url] = existing_id
                        for row in skipped:
                            imported_id = row["id"]
                            if imported_id not in existing_ids:
                                matched_id = ids_by_url.get(row["linkedin_url"])
                                if matched_id is None:
                                    raise ValueError("Le profil existant n’a pas pu être retrouvé.")
                                remapped_ids[imported_id] = matched_id
                if edges:
                    mapped_edges = []
                    for row in edges:
                        source_id = uuid.UUID(row["source_id"])
                        target_id = uuid.UUID(row["target_id"])
                        row["source_id"] = remapped_ids.get(source_id, source_id)
                        row["target_id"] = remapped_ids.get(target_id, target_id)
                        if row["source_id"] != row["target_id"]:
                            mapped_edges.append(row)
                    if mapped_edges:
                        result = await session.execute(edge_insert.returning(EdgeORM.id), mapped_edges)
                        edges_added += len(result.scalars().all())
        return profiles_seen, profiles_added, edges_added

    async def iter_graph_records(self) -> AsyncIterator[ProfileRecord | EdgeRecord]:
        """Read just the fields the graph uses, with a server-side cursor."""
        async with self.session_factory() as session:
            nodes = await session.stream(select(
                ProfileORM.id, ProfileORM.full_name, ProfileORM.promo_year, ProfileORM.current_role,
                ProfileORM.current_company, ProfileORM.sector, ProfileORM.photo_url, ProfileORM.is_student,
            ).execution_options(yield_per=1000))
            async for row in nodes.mappings():
                yield ProfileRecord(**{**row, "id": str(row["id"])})
            edges = await session.stream(select(
                EdgeORM.source_id, EdgeORM.target_id, EdgeORM.edge_type, EdgeORM.probability, EdgeORM.reason,
            ).execution_options(yield_per=1000))
            async for row in edges.mappings():
                yield EdgeRecord(**{**row, "source_id": str(row["source_id"]), "target_id": str(row["target_id"])})

    async def import_linkcs_records(
        self, profiles: list[ProfileRecord], edges: list[EdgeRecord]
    ) -> tuple[int, int]:
        """Insert a dump atomically, preserving every existing profile and relation."""
        profiles_added = 0
        edges_added = 0
        async with self.session_factory() as session, session.begin():
            for start in range(0, len(profiles), 100):
                batch = profiles[start : start + 100]
                values = [
                    {
                        "id": uuid.UUID(profile.id),
                        "full_name": profile.full_name,
                        "email": profile.email,
                        "linkedin_url": profile.linkedin_url,
                        "promo_year": profile.promo_year,
                        "bio": profile.bio,
                        "education": profile.education,
                        "associations": profile.associations,
                        "passions": profile.passions,
                        "is_student": False,
                        "has_imported_linkedin": False,
                        "enrichment_source": "LINKCS_DB",
                    }
                    for profile in batch
                ]
                statement = pg_insert(ProfileORM).on_conflict_do_nothing().returning(ProfileORM.id)
                result = await session.execute(statement, values)
                profiles_added += len(result.scalars().all())
            for start in range(0, len(edges), 500):
                batch = edges[start : start + 500]
                values = [
                    {
                        "source_id": uuid.UUID(edge.source_id),
                        "target_id": uuid.UUID(edge.target_id),
                        "edge_type": edge.edge_type,
                        "probability": edge.probability,
                        "reason": edge.reason,
                    }
                    for edge in batch
                ]
                statement = pg_insert(EdgeORM).on_conflict_do_nothing().returning(EdgeORM.id)
                result = await session.execute(statement, values)
                edges_added += len(result.scalars().all())
        return profiles_added, edges_added

    async def get_profile(self, profile_id: str) -> Optional[ProfileRecord]:
        try:
            uid = uuid.UUID(str(profile_id))
        except ValueError:
            return None
        async with self.session_factory() as session:
            row = await session.get(ProfileORM, uid)
            return _orm_to_record(row) if row else None

    async def get_profile_by_email_or_id(self, identifier: str) -> Optional[ProfileRecord]:
        ident = identifier.strip()
        try:
            uid = uuid.UUID(ident)
        except ValueError:
            uid = None

        async with self.session_factory() as session:
            if uid is not None:
                row = await session.get(ProfileORM, uid)
                if row:
                    return _orm_to_record(row)
            stmt = select(ProfileORM).where(ProfileORM.email.ilike(ident))
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row:
                return _orm_to_record(row)
            stmt_name = select(ProfileORM).where(ProfileORM.full_name.ilike(ident)).limit(1)
            row_name = (await session.execute(stmt_name)).scalar_one_or_none()
            return _orm_to_record(row_name) if row_name else None

    async def get_profile_by_linkedin_url(self, linkedin_url: str) -> Optional[ProfileRecord]:
        norm = linkedin_url.strip().rstrip("/")
        async with self.session_factory() as session:
            stmt = select(ProfileORM).where(ProfileORM.linkedin_url.ilike(norm))
            row = (await session.execute(stmt)).scalar_one_or_none()
            return _orm_to_record(row) if row else None

    async def list_profiles(self, limit: Optional[int] = None) -> list[ProfileRecord]:
        async with self.session_factory() as session:
            stmt = select(ProfileORM).order_by(ProfileORM.created_at.asc())
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_orm_to_record(r) for r in rows]

    async def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord:
        uid = uuid.UUID(profile.id) if profile.id else uuid.uuid4()
        profile.id = str(uid)
        async with self.session_factory() as session:
            values = {
                "id": uid,
                "full_name": profile.full_name,
                "email": profile.email,
                "linkedin_url": profile.linkedin_url,
                "photo_url": profile.photo_url,
                "promo_year": profile.promo_year,
                "current_role": profile.current_role,
                "current_company": profile.current_company,
                "sector": profile.sector,
                "location": profile.location,
                "bio": profile.bio,
                "experiences": profile.experiences,
                "education": profile.education,
                "associations": profile.associations,
                "passions": profile.passions,
                "is_student": profile.is_student,
                "has_imported_linkedin": profile.has_imported_linkedin,
                "enrichment_source": profile.enrichment_source,
                "last_enriched_at": profile.last_enriched_at,
                "embedding": profile.embedding,
                "updated_at": datetime.now(timezone.utc),
            }
            stmt = (
                pg_insert(ProfileORM)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[ProfileORM.id],
                    set_={k: v for k, v in values.items() if k != "id"},
                )
            )
            await session.execute(stmt)
            await session.commit()
        return profile

    async def update_enrichment(
        self,
        profile_id: str,
        *,
        bio: str,
        experiences: list[dict[str, Any]],
        associations: list[str],
        passions: list[str],
        embedding: list[float],
        current_role: Optional[str] = None,
        current_company: Optional[str] = None,
        sector: Optional[str] = None,
        location: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        photo_url: Optional[str] = None,
        embedding_space: str = "vertex",
        enrichment_source: str = "WEB_TAVILY",
        enriched_at: Optional[datetime] = None,
    ) -> Optional[ProfileRecord]:
        existing = await self.get_profile(profile_id)
        if existing is None:
            return None

        merged_bio = existing.bio
        if bio and (not existing.bio or len(bio) > len(existing.bio)):
            merged_bio = bio

        merged_exps = list(existing.experiences)
        seen_exp = {(_normalize_text(e.get("company")), _normalize_text(e.get("role"))) for e in merged_exps}
        for exp in experiences:
            key = (_normalize_text(exp.get("company")), _normalize_text(exp.get("role")))
            if key not in seen_exp and exp.get("company"):
                merged_exps.append(exp)
                seen_exp.add(key)

        merged_company = current_company if (current_company and not existing.current_company) else existing.current_company
        merged_role = current_role if (current_role and not existing.current_role) else existing.current_role
        merged_sector = sector if (sector and not existing.sector) else existing.sector
        merged_location = location if (location and not existing.location) else existing.location
        merged_linkedin_url = existing.linkedin_url
        if linkedin_url and not existing.linkedin_url:
            conflict = await self.get_profile_by_linkedin_url(linkedin_url)
            if conflict is None or conflict.id == profile_id:
                merged_linkedin_url = linkedin_url
        merged_photo_url = photo_url if (photo_url and not existing.photo_url) else existing.photo_url
        if not merged_company:
            first_with_company = next((e for e in merged_exps if e.get("company")), None)
            if first_with_company:
                merged_company = first_with_company.get("company")
                if not merged_role and first_with_company.get("role"):
                    merged_role = first_with_company.get("role")

        merged_assos = list(existing.associations)
        seen_asso = {_normalize_text(a) for a in merged_assos}
        for asso in associations:
            k = _normalize_text(asso)
            if k and k not in seen_asso:
                merged_assos.append(asso)
                seen_asso.add(k)

        merged_passions = list(existing.passions)
        seen_passion = {_normalize_text(p) for p in merged_passions}
        for passion in passions:
            k = _normalize_text(passion)
            if k and k not in seen_passion:
                merged_passions.append(passion)
                seen_passion.add(k)

        ts = enriched_at or datetime.now(timezone.utc)
        async with self.session_factory() as session:
            stmt = (
                update(ProfileORM)
                .where(ProfileORM.id == uuid.UUID(profile_id))
                .values(
                    bio=merged_bio,
                    current_company=merged_company,
                    current_role=merged_role,
                    sector=merged_sector,
                    location=merged_location,
                    linkedin_url=merged_linkedin_url,
                    photo_url=merged_photo_url,
                    experiences=merged_exps,
                    associations=merged_assos,
                    passions=merged_passions,
                    embedding=embedding,
                    enrichment_source=enrichment_source,
                    last_enriched_at=ts,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.execute(stmt)
            await session.commit()

        existing.bio = merged_bio
        existing.current_company = merged_company
        existing.current_role = merged_role
        existing.sector = merged_sector
        existing.location = merged_location
        existing.linkedin_url = merged_linkedin_url
        existing.photo_url = merged_photo_url
        existing.experiences = merged_exps
        existing.associations = merged_assos
        existing.passions = merged_passions
        existing.embedding = embedding
        existing.embedding_space = embedding_space
        existing.enrichment_source = enrichment_source
        existing.last_enriched_at = ts
        return existing

    async def count_enriched_profiles(self) -> int:
        async with self.session_factory() as session:
            res = await session.execute(
                text("SELECT COUNT(*) FROM profiles WHERE last_enriched_at IS NOT NULL")
            )
            return int(res.scalar_one() or 0)

    async def list_edges(self) -> list[EdgeRecord]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(EdgeORM))).scalars().all()
            return [
                EdgeRecord(
                    id=str(r.id),
                    source_id=str(r.source_id),
                    target_id=str(r.target_id),
                    edge_type=r.edge_type,
                    probability=float(r.probability),
                    reason=r.reason,
                )
                for r in rows
            ]

    async def upsert_edges(self, edges: list[EdgeRecord]) -> int:
        if not edges:
            return 0
        rows_to_insert = []
        for edge in edges:
            if edge.source_id == edge.target_id:
                continue
            rows_to_insert.append(
                {
                    "id": uuid.UUID(edge.id) if edge.id else uuid.uuid4(),
                    "source_id": uuid.UUID(edge.source_id),
                    "target_id": uuid.UUID(edge.target_id),
                    "edge_type": edge.edge_type,
                    "probability": float(max(0.05, min(0.99, edge.probability))),
                    "reason": edge.reason,
                }
            )
        if not rows_to_insert:
            return 0
        async with self.session_factory() as session:
            stmt = pg_insert(EdgeORM).values(rows_to_insert)
            stmt = stmt.on_conflict_do_update(
                index_elements=[EdgeORM.source_id, EdgeORM.target_id, EdgeORM.edge_type],
                set_={
                    "probability": stmt.excluded.probability,
                    "reason": stmt.excluded.reason,
                },
            )
            await session.execute(stmt)
            await session.commit()
        return len(rows_to_insert)

    async def hybrid_search_alumni(
        self,
        query_embedding: list[float],
        parsed_query: ParsedQuery,
        *,
        filters: Optional[SearchFilters] = None,
        exclude_profile_id: Optional[str] = None,
        limit: int = 20,
        raw_query: str = "",
        vertex_query_embedding: Optional[list[float]] = None,
    ) -> list[SearchCandidate]:
        """Single-query SQL + pgvector hybrid pre-filter without excluding sparse profiles."""
        effective_vec = vertex_query_embedding if vertex_query_embedding is not None else query_embedding
        vec_literal = "[" + ",".join(f"{float(v):.6f}" for v in effective_vec) + "]"
        lexical_terms = " ".join(
            [
                parsed_query.target_sector or "",
                " ".join(parsed_query.target_companies),
                " ".join(parsed_query.target_roles),
                parsed_query.worked_with or "",
                " ".join(parsed_query.icebreakers),
                raw_query or "",
            ]
        ).strip()

        sector_pattern = f"%{(filters.sector if filters and filters.sector else parsed_query.target_sector) or ''}%"
        companies = (filters.companies if filters and filters.companies else parsed_query.target_companies) or []
        company_pattern = f"%{companies[0]}%" if companies else "%"
        roles = (filters.roles if filters and filters.roles else parsed_query.target_roles) or []
        role_pattern = f"%{roles[0]}%" if roles else "%"
        worked_with = ((filters.worked_with if filters else None) or parsed_query.worked_with or "").strip()
        worked_with_pattern = f"%{worked_with}%" if worked_with else ""

        promo_min = filters.promo_min if filters else None
        promo_max = filters.promo_max if filters else None

        sql = text(
            """
            SELECT
                p.id::text AS id,
                CASE
                    WHEN p.embedding IS NOT NULL
                    THEN GREATEST(0.0, 1.0 - (p.embedding <=> CAST(:qvec AS vector)))
                    ELSE 0.25
                END AS semantic_score,
                (
                    0.65 * CASE
                        WHEN p.embedding IS NOT NULL
                        THEN GREATEST(0.0, 1.0 - (p.embedding <=> CAST(:qvec AS vector)))
                        ELSE 0.25
                    END
                    + CASE
                        WHEN :lexical_terms <> ''
                        THEN LEAST(0.25, ts_rank_cd(p.search_tsv, plainto_tsquery('french', :lexical_terms)))
                        ELSE 0.0
                    END
                    + CASE
                        WHEN :has_sector AND COALESCE(p.sector, '') ILIKE :sector_pattern THEN 0.20
                        ELSE 0.0
                    END
                    + CASE
                        WHEN :has_company AND COALESCE(p.current_company, '') ILIKE :company_pattern THEN 0.25
                        ELSE 0.0
                    END
                    + CASE
                        WHEN :has_role AND COALESCE(p."current_role", '') ILIKE :role_pattern THEN 0.20
                        ELSE 0.0
                    END
                    + CASE
                        WHEN :has_worked_with AND (
                            p.experiences::text ILIKE :worked_with_pattern
                            OR COALESCE(p.current_company, '') ILIKE :worked_with_pattern
                        ) THEN 0.25
                        ELSE 0.0
                    END
                ) AS hybrid_score
            FROM profiles p
            WHERE p.is_student = FALSE
              AND (CAST(:exclude_id AS text) IS NULL OR p.id::text <> CAST(:exclude_id AS text))
              AND (CAST(:promo_min AS integer) IS NULL OR p.promo_year >= CAST(:promo_min AS integer))
              AND (CAST(:promo_max AS integer) IS NULL OR p.promo_year <= CAST(:promo_max AS integer))
            ORDER BY hybrid_score DESC
            LIMIT :limit
            """
        )

        params = {
            "qvec": vec_literal,
            "lexical_terms": lexical_terms,
            "has_sector": bool((filters.sector if filters else None) or parsed_query.target_sector),
            "sector_pattern": sector_pattern,
            "has_company": bool(companies),
            "company_pattern": company_pattern,
            "has_role": bool(roles),
            "role_pattern": role_pattern,
            "has_worked_with": bool(worked_with),
            "worked_with_pattern": worked_with_pattern,
            "exclude_id": exclude_profile_id,
            "promo_min": promo_min,
            "promo_max": promo_max,
            "limit": limit,
        }

        async with self.session_factory() as session:
            rows = (await session.execute(sql, params)).all()
            if not rows:
                return []
            ordered_ids = [uuid.UUID(r.id) for r in rows]
            score_map = {str(r.id): (float(r.hybrid_score), float(r.semantic_score)) for r in rows}
            orm_rows = (
                await session.execute(select(ProfileORM).where(ProfileORM.id.in_(ordered_ids)))
            ).scalars().all()
            by_id = {str(o.id): _orm_to_record(o) for o in orm_rows}

        candidates: list[SearchCandidate] = []
        for r in rows:
            prof = by_id.get(str(r.id))
            if prof:
                h_score, s_score = score_map[str(r.id)]
                candidates.append(SearchCandidate(profile=prof, hybrid_score=h_score, semantic_score=s_score))
        return candidates

    async def create_api_token(self, profile_id: str, token_hash: str, label: str) -> ApiTokenRecord:
        uid = uuid.uuid4()
        async with self.session_factory() as session:
            row = ApiTokenORM(
                id=uid,
                profile_id=uuid.UUID(profile_id),
                token_hash=token_hash,
                label=label,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return ApiTokenRecord(
                id=str(row.id),
                profile_id=str(row.profile_id),
                token_hash=row.token_hash,
                label=row.label,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
            )

    async def list_api_tokens(self, profile_id: str) -> list[ApiTokenRecord]:
        async with self.session_factory() as session:
            stmt = select(ApiTokenORM).where(ApiTokenORM.profile_id == uuid.UUID(profile_id))
            rows = (await session.execute(stmt)).scalars().all()
            return [
                ApiTokenRecord(
                    id=str(r.id),
                    profile_id=str(r.profile_id),
                    token_hash=r.token_hash,
                    label=r.label,
                    created_at=r.created_at,
                    last_used_at=r.last_used_at,
                )
                for r in rows
            ]

    async def delete_api_token(self, token_id: str, profile_id: str) -> bool:
        async with self.session_factory() as session:
            stmt = delete(ApiTokenORM).where(
                ApiTokenORM.id == uuid.UUID(token_id),
                ApiTokenORM.profile_id == uuid.UUID(profile_id),
            )
            res = await session.execute(stmt)
            await session.commit()
            return (res.rowcount or 0) > 0

    async def resolve_api_token(self, token_hash: str) -> Optional[str]:
        async with self.session_factory() as session:
            stmt = select(ApiTokenORM).where(ApiTokenORM.token_hash == token_hash)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.last_used_at = datetime.now(timezone.utc)
            await session.commit()
            return str(row.profile_id)

    async def health_check(self) -> dict[str, Any]:
        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
            return {"backend": "postgres", "ok": True}
        except Exception as exc:
            return {"backend": "postgres", "ok": False, "error": str(exc)}
