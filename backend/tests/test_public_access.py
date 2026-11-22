"""Public dev access without Google credentials, user tokens, or external calls."""

import json

import pytest
from fastapi.testclient import TestClient

from app.auth import PUBLIC_VISITOR_ID
from app.config import Settings
from app.db.repository import InMemoryAlumniRepository
from app.main import create_app
from app.services.enrichment import NullWebSearchClient
from app.services.llm import DeterministicLLMService


def public_app(repository, *, enabled=True):
    return create_app(
        settings=Settings(
            database_url=None, demo_mode=False, allow_demo_auth=False,
            allow_public_access=enabled, linkcs_import_token=None,
        ),
        repository=repository,
        llm_service=DeterministicLLMService(),
        web_client=NullWebSearchClient(),
    )


@pytest.fixture()
def public_client(test_repo):
    with TestClient(public_app(test_repo)) as client:
        yield client


def test_public_me_uses_shared_visitor_without_a_token(public_client):
    response = public_client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json()["id"] == PUBLIC_VISITOR_ID
    assert response.json()["full_name"] == "Visiteur public"
    assert public_client.get("/health").json()["public_access"] is True
    assert public_client.get("/api/v1/profiles").status_code == 200
    assert public_client.get("/api/v1/me", headers={"Authorization": "Bearer obsolete"}).status_code == 200


def test_public_context_selection_is_not_authentication(public_client):
    student_id = "11111111-1111-4111-8111-111111111111"
    response = public_client.get("/api/v1/me", headers={"X-Profile-Id": student_id})
    assert response.status_code == 200
    assert response.json()["id"] == student_id
    assert public_client.get("/api/v1/me", headers={"X-Profile-Id": "missing"}).status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/chat", "/api/v1/chat/stream"])
def test_public_chat_without_authorization(public_client, path):
    response = public_client.post(path, json={"messages": [{"role": "user", "content": "Bonjour"}]})
    assert response.status_code == 200
    if path.endswith("/stream"):
        assert "final_result" in response.text
    else:
        assert response.json()["intro_text"]


def test_public_linkcs_import_keeps_consent_and_validation(public_client):
    dump = json.dumps([{"login": "public-example", "nom_complet": "Exemple Public"}])
    files = {"file": ("linkcs.json", dump, "application/json")}
    assert public_client.post("/api/v1/linkcs/import", files=files).status_code == 400
    response = public_client.post("/api/v1/linkcs/import", files=files, data={"confirmed": "true"})
    assert response.status_code == 200
    assert response.json()["profiles_added"] == 1
    assert public_client.post(
        "/api/v1/linkcs/import", files={"file": ("linkcs.json", "invalid", "application/json")},
        data={"confirmed": "true"},
    ).status_code == 400


def test_public_mcp_search_without_bearer_or_user_identity(public_client):
    headers = {"Accept": "application/json, text/event-stream"}
    response = public_client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    })
    assert response.status_code == 200
    assert len(response.json()["result"]["tools"]) == 3
    response = public_client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "search_alumni_action_plan", "arguments": {
            "query": "Je cherche un alumni chez Mistral AI", "limit": 2,
        }},
    })
    assert response.status_code == 200
    result = response.json()["result"]
    assert not result.get("isError")
    assert json.loads(result["content"][0]["text"])["student_id"] == PUBLIC_VISITOR_ID


def test_public_startup_bootstraps_only_one_visitor_on_empty_database():
    repository = InMemoryAlumniRepository()
    for _ in range(2):
        with TestClient(public_app(repository)) as client:
            assert client.get("/api/v1/me").status_code == 200
            assert client.post("/api/v1/chat", json={
                "messages": [{"role": "user", "content": "Bonjour"}],
            }).status_code == 200
    assert list(repository.profiles) == [PUBLIC_VISITOR_ID]


@pytest.mark.parametrize("tool,arguments", [
    ("get_more_connections", {"target_id": "22222222-2222-4222-8222-222222222222"}),
    ("draft_outreach_message", {
        "first_hop_id": "33333333-3333-4333-8333-333333333333",
        "target_id": "22222222-2222-4222-8222-222222222222", "context": "stage",
    }),
])
def test_other_public_mcp_tools_accept_profile_context_without_a_token(public_client, tool, arguments):
    response = public_client.post("/mcp/", headers={"Accept": "application/json, text/event-stream"}, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": tool, "arguments": {
                **arguments, "user_email_or_id": "11111111-1111-4111-8111-111111111111",
            },
        },
    })
    assert response.status_code == 200
    assert not response.json()["result"].get("isError")


def test_public_schema_does_not_request_authentication_or_expose_token_management(public_client):
    schema = public_client.get("/openapi.json").json()
    assert "/api/v1/tokens" not in schema["paths"]
    assert not schema.get("security")
    for path in ("/api/v1/chat", "/api/v1/linkcs/import"):
        assert not schema["paths"][path]["post"].get("security")
    assert public_client.post("/api/v1/tokens", json={"label": "unused"}).status_code == 404


def test_public_access_stays_opt_in_for_other_deployments(test_repo):
    assert Settings().allow_public_access is False
    with TestClient(public_app(test_repo, enabled=False)) as client:
        assert client.get("/api/v1/me").status_code == 401
        assert client.post("/api/v1/chat", json={
            "messages": [{"role": "user", "content": "Bonjour"}],
        }).status_code == 401
        assert client.post("/api/v1/linkcs/import", files={
            "file": ("linkcs.json", "[]", "application/json"),
        }).status_code == 503
