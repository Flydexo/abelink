"""Async SQLAlchemy engine, session factory, and migration runner."""

from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def create_db_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def run_sql_migrations(engine: AsyncEngine) -> None:
    """Execute idempotent SQL migrations from migrations/*.sql."""
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with engine.begin() as conn:
        for path in migration_files:
            sql_text = path.read_text(encoding="utf-8")
            await conn.exec_driver_sql(sql_text)


async def check_db_health(engine: Optional[AsyncEngine]) -> bool:
    if engine is None:
        return False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
