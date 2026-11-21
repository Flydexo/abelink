"""Application configuration loaded via Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ENV = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Typed environment settings for the Abelink backend."""

    model_config = SettingsConfigDict(
        env_file=(".env", str(_BACKEND_ENV)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: Optional[str] = None
    google_cloud_project: str = "751082713943"
    google_cloud_location: str = "global"
    gemma_model: str = "google/gemma-4-26b-a4b-it-maas"
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 768

    tavily_api_key: Optional[str] = None
    prefer_free_search: bool = True
    enrichment_cache_path: str = "~/.cache/abelink/enrichment_cache.sqlite"

    auth_secret: str = "dev-secret-change-in-production"
    cors_origins: str = "http://localhost:5173,https://abelink.app,https://dev.abelink.app"
    allow_demo_auth: bool = True
    demo_mode: bool = False
    linkcs_data_path: Optional[str] = None
    linkedin_li_at: Optional[str] = None
    linkcs_import_token: Optional[str] = None
    public_api_url: str = "http://localhost:8000"

    default_demo_student_id: str = "11111111-1111-4111-8111-111111111111"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def normalized_database_url(self) -> Optional[str]:
        if not self.database_url:
            return None
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        if url.startswith("postgresql://") and "+psycopg" not in url and "+asyncpg" not in url:
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
