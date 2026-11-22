"""Synthetic tests for the protected LinkCS JSON upload and additive imports."""

import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import routes_linkcs
from app.config import Settings
from app.db.repository import InMemoryAlumniRepository
from app.main import create_app
from app.services.linkcs_loader import load_linkcs_rows
from app.services.llm import DeterministicLLMService

IMPORT_TOKEN = "synthetic-admin-token-for-tests-only"
HEADERS = {"X-LinkCS-Import-Token": IMPORT_TOKEN}
ROWS = [
    {
        "login": "import-camille-fictive",
        "nom_complet": "Camille Fictive",
        "promotion": 2024,
        "associations": ["Club Exemple [Présidente (2023)]"],
        "reseaux_sociaux": ["https://www.linkedin.com/in/camille-import-fictive/"],
        "biographie": "Profil fictif pour les tests.",
    },
    {
        "login": "import-alex-exemple",
        "prenom": "Alex",
        "nom": "Exemple",
        "promotion": 2024,
        "associations": ["Club Exemple"],
    },
]


@pytest.fixture()
def import_client(test_repo):
    settings = Settings(
        database_url=None, demo_mode=True, allow_demo_auth=False,
        linkcs_import_token=IMPORT_TOKEN,
    )
    app = create_app(settings=settings, repository=test_repo, llm_service=DeterministicLLMService())
    with TestClient(app) as client:
        yield client


def upload(client, rows=ROWS, *, headers=None, confirmed="true", filename="linkcs.json", raw=None):
    content = json.dumps(rows).encode() if raw is None else raw
    return client.post(
        "/api/v1/linkcs/import",
        headers=HEADERS if headers is None else headers,
        data={"confirmed": confirmed},
        files={"file": (filename, content, "application/json")},
    )


def test_import_adds_profiles_and_graph_without_ai_or_demo_student(import_client, test_repo):
    original_ids = set(test_repo.profiles)
    response = upload(import_client)
    assert response.status_code == 200
    assert response.json() == {
        "records_received": 2, "profiles_added": 2, "profiles_skipped": 0,
        "relationships_added": 1, "storage": "in_memory",
    }
    additions = [profile for key, profile in test_repo.profiles.items() if key not in original_ids]
    assert len(additions) == 2
    assert all(not profile.is_student and profile.embedding is None for profile in additions)
    assert all(profile.enrichment_source == "LINKCS_DB" for profile in additions)
    assert import_client.get("/health").json()["graph"]["nodes"] == len(test_repo.profiles)
    paths = import_client.app.state.container.graph_engine.find_connection_paths(
        additions[0].id, additions[1].id,
    )
    assert len(paths) == 1
    assert paths[0].total_probability == pytest.approx(0.70)


def test_repeat_import_preserves_existing_enrichment(import_client, test_repo):
    assert upload(import_client).status_code == 200
    profile_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "linkcs.import-camille-fictive"))
    profile = test_repo.profiles[profile_id]
    profile.bio = "Enrichissement à conserver."
    profile.current_company = "Entreprise Fictive"
    profile.last_enriched_at = datetime.now(timezone.utc)
    response = upload(import_client)
    assert response.status_code == 200
    assert response.json()["profiles_added"] == 0
    assert response.json()["relationships_added"] == 0
    assert response.json()["profiles_skipped"] == 2
    assert test_repo.profiles[profile_id].bio == "Enrichissement à conserver."
    assert test_repo.profiles[profile_id].current_company == "Entreprise Fictive"


def test_linkedin_match_preserves_existing_id_and_remaps_edges(import_client, test_repo):
    existing = test_repo.profiles["22222222-2222-4222-8222-222222222222"]
    rows = [
        {**ROWS[0], "reseaux_sociaux": [existing.linkedin_url]},
        ROWS[1],
    ]
    response = upload(import_client, rows)
    assert response.status_code == 200
    assert response.json()["profiles_added"] == 1
    assert response.json()["profiles_skipped"] == 1
    added_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "linkcs.import-alex-exemple"))
    source, target = sorted((existing.id, added_id))
    assert (source, target, "INFERRED_ASSO") in test_repo.edges
    assert test_repo.profiles[existing.id].full_name == "Alice Martin"
    assert test_repo.profiles[existing.id].current_company == "Mistral AI"


def test_duplicates_in_same_file_are_ignored(import_client):
    duplicate_url = {**ROWS[0], "login": "another-login-for-same-profile"}
    response = upload(import_client, [*ROWS, ROWS[0], duplicate_url])
    assert response.status_code == 200
    assert response.json()["records_received"] == 4
    assert response.json()["profiles_added"] == 2
    assert response.json()["profiles_skipped"] == 2


@pytest.mark.parametrize("headers", [{}, {"X-Demo-User-Id": "11111111-1111-4111-8111-111111111111"}, {"X-LinkCS-Import-Token": "wrong"}])
def test_administration_key_required_even_with_demo_identity(import_client, test_repo, headers):
    before = len(test_repo.profiles)
    assert upload(import_client, headers=headers).status_code == 401
    assert len(test_repo.profiles) == before


def test_disabled_unless_import_key_is_configured(import_client, test_repo):
    import_client.app.state.container.settings.linkcs_import_token = None
    before = len(test_repo.profiles)
    assert upload(import_client).status_code == 503
    assert len(test_repo.profiles) == before


def test_consent_required(import_client):
    assert upload(import_client, confirmed="false").status_code == 400


@pytest.mark.parametrize("raw", [b"", b"not json", b"\xff", b"{}", b"[]", b"[1]", b"[null]", b"[{}]"])
def test_invalid_json_has_no_side_effects(import_client, test_repo, raw):
    before = (len(test_repo.profiles), len(test_repo.edges))
    response = upload(import_client, raw=raw)
    assert response.status_code == 400
    assert (len(test_repo.profiles), len(test_repo.edges)) == before


def test_json_extension_required(import_client):
    assert upload(import_client, filename="dump.csv").status_code == 400


def test_utf8_bom_is_accepted(import_client):
    response = upload(import_client, raw=b"\xef\xbb\xbf" + json.dumps(ROWS).encode())
    assert response.status_code == 200


def test_upload_size_and_record_limits(import_client, test_repo, monkeypatch):
    before = len(test_repo.profiles)
    monkeypatch.setattr(routes_linkcs, "MAX_UPLOAD_BYTES", 4)
    assert upload(import_client).status_code == 413
    monkeypatch.setattr(routes_linkcs, "MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(routes_linkcs, "MAX_RECORDS", 1)
    assert upload(import_client).status_code == 413
    assert len(test_repo.profiles) == before


def test_graph_expansion_limit_has_no_side_effects(import_client, test_repo, monkeypatch):
    before = (len(test_repo.profiles), len(test_repo.edges))
    monkeypatch.setattr(routes_linkcs, "MAX_RELATIONSHIPS", 0)
    assert upload(import_client).status_code == 400
    assert (len(test_repo.profiles), len(test_repo.edges)) == before


def test_bootstrap_empty_database_without_student_authentication():
    repository = InMemoryAlumniRepository()
    settings = Settings(demo_mode=True, allow_demo_auth=False, linkcs_import_token=IMPORT_TOKEN)
    app = create_app(settings=settings, repository=repository, llm_service=DeterministicLLMService())
    with TestClient(app) as client:
        assert client.get("/api/v1/me").status_code == 401
        assert upload(client).json()["profiles_added"] == 2
        assert len(repository.profiles) == 2


@pytest.mark.asyncio
async def test_invalid_memory_import_is_atomic():
    repository = InMemoryAlumniRepository()
    profiles, edges = load_linkcs_rows(ROWS)
    with pytest.raises(ValueError):
        await repository.import_linkcs_records(profiles[:1], edges)
    assert not repository.profiles
    assert not repository.edges
