from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.db.repository import EdgeRecord, PostgresAlumniRepository, ProfileRecord


async def test_bundle_reuses_linkedin_profile_and_remaps_edges():
    existing_id, imported_id, new_id, edge_id = (uuid4() for _ in range(4))
    linkedin_url = "https://www.linkedin.com/in/example"

    inserted_profiles = MagicMock()
    inserted_profiles.scalars().all.return_value = [new_id]
    inserted_edges = MagicMock()
    inserted_edges.scalars().all.return_value = [edge_id]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[inserted_profiles, [(existing_id, linkedin_url)], inserted_edges])

    @asynccontextmanager
    async def session_factory():
        yield session

    repo = PostgresAlumniRepository(None, session_factory)
    records = iter([
        ProfileRecord(str(imported_id), "Existing profile", linkedin_url=linkedin_url),
        ProfileRecord(str(new_id), "New profile"),
        EdgeRecord(str(imported_id), str(new_id), "INFERRED_ASSO", 0.75, "Club", str(edge_id)),
    ])
    assert await repo.import_bundle_records(records) == (2, 1, 1)

    statement = session.execute.await_args_list[0].args[0]
    assert "ON CONFLICT DO NOTHING" in str(statement.compile(dialect=postgresql.dialect()))
    edges = session.execute.await_args_list[-1].args[1]
    assert [(edge["source_id"], edge["target_id"]) for edge in edges] == [(existing_id, new_id)]
