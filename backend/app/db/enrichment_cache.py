"""Persistent local SQLite cache for enriched alumni profiles and 768-dim embeddings."""

from __future__ import annotations

import json
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.db.repository import ProfileRecord


def _normalize_name(value: Optional[str]) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(ascii_only.lower().split())


def _safe_json_loads(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, type(default)) else default
    except Exception:
        return default


class EnrichmentCache:
    """Thread-safe SQLite store for enriched profile fields and embeddings outside Git."""

    def __init__(self, db_path: str = "~/.cache/abelink/enrichment_cache.sqlite") -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles_cache (
                    profile_id TEXT PRIMARY KEY,
                    full_name_norm TEXT,
                    current_role TEXT,
                    current_company TEXT,
                    sector TEXT,
                    location TEXT,
                    linkedin_url TEXT,
                    photo_url TEXT,
                    bio TEXT,
                    experiences_json TEXT,
                    associations_json TEXT,
                    passions_json TEXT,
                    enrichment_source TEXT,
                    last_enriched_at TEXT,
                    embedding_json TEXT,
                    embedding_space TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_profiles_cache_name ON profiles_cache (full_name_norm)"
            )
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(profiles_cache)").fetchall()
            }
            if "photo_url" not in cols:
                conn.execute("ALTER TABLE profiles_cache ADD COLUMN photo_url TEXT")
            conn.commit()

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Return all cached profile payloads keyed by profile_id."""
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM profiles_cache").fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            emb_raw = _safe_json_loads(row["embedding_json"], [])
            embedding = [float(v) for v in emb_raw] if emb_raw else None
            result[row["profile_id"]] = {
                "profile_id": row["profile_id"],
                "full_name_norm": row["full_name_norm"] or "",
                "current_role": row["current_role"],
                "current_company": row["current_company"],
                "sector": row["sector"],
                "location": row["location"],
                "linkedin_url": row["linkedin_url"],
                "photo_url": row["photo_url"] if "photo_url" in row.keys() else None,
                "bio": row["bio"],
                "experiences": _safe_json_loads(row["experiences_json"], []),
                "associations": _safe_json_loads(row["associations_json"], []),
                "passions": _safe_json_loads(row["passions_json"], []),
                "enrichment_source": row["enrichment_source"] or "WEB_TAVILY",
                "last_enriched_at": row["last_enriched_at"],
                "embedding": embedding,
                "embedding_space": row["embedding_space"] or "deterministic",
                "updated_at": row["updated_at"],
            }
        return result

    def save_profile(self, profile: ProfileRecord) -> None:
        """Persist or update a single ProfileRecord and its embedding in SQLite."""
        now_iso = datetime.now(timezone.utc).isoformat()
        last_enriched_iso: Optional[str] = None
        if profile.last_enriched_at is not None:
            dt = profile.last_enriched_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            last_enriched_iso = dt.isoformat()

        emb_json = json.dumps([float(v) for v in profile.embedding]) if profile.embedding else None
        payload = (
            str(profile.id),
            _normalize_name(profile.full_name),
            profile.current_role,
            profile.current_company,
            profile.sector,
            profile.location,
            profile.linkedin_url,
            profile.photo_url,
            profile.bio,
            json.dumps(profile.experiences or [], ensure_ascii=False),
            json.dumps(profile.associations or [], ensure_ascii=False),
            json.dumps(profile.passions or [], ensure_ascii=False),
            profile.enrichment_source,
            last_enriched_iso,
            emb_json,
            profile.embedding_space,
            now_iso,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles_cache (
                    profile_id, full_name_norm, current_role, current_company, sector,
                    location, linkedin_url, photo_url, bio, experiences_json, associations_json,
                    passions_json, enrichment_source, last_enriched_at,
                    embedding_json, embedding_space, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    full_name_norm = excluded.full_name_norm,
                    current_role = excluded.current_role,
                    current_company = excluded.current_company,
                    sector = excluded.sector,
                    location = excluded.location,
                    linkedin_url = excluded.linkedin_url,
                    photo_url = excluded.photo_url,
                    bio = excluded.bio,
                    experiences_json = excluded.experiences_json,
                    associations_json = excluded.associations_json,
                    passions_json = excluded.passions_json,
                    enrichment_source = excluded.enrichment_source,
                    last_enriched_at = excluded.last_enriched_at,
                    embedding_json = excluded.embedding_json,
                    embedding_space = excluded.embedding_space,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            conn.commit()

    def count_enriched(self) -> int:
        """Count profiles stored in cache with a non-null enrichment timestamp."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM profiles_cache WHERE last_enriched_at IS NOT NULL"
            ).fetchone()
            return int(row["cnt"]) if row else 0
