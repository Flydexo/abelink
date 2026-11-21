"""Integration tests for FastAPI REST endpoints, OpenAPI GPT Actions schema, SSE, Auth tokens, and FastMCP."""

import io
import json
import zipfile


def _build_linkedin_zip_for_api() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        connections_csv = (
            "Notes:\n"
            "Export\n\n"
            "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
            "Sarah,Cohen,https://www.linkedin.com/in/sarah-cohen/,sarah@partech.com,Partech,Investment Associate,2025\n"
        )
        zf.writestr("Connections.csv", connections_csv.encode("utf-8"))
    return buf.getvalue()


def test_health_and_openapi_gpt_actions_metadata(client):
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["graph"]["nodes"] >= 7
    assert body["graph"]["edges"] >= 6

    schema_res = client.get("/openapi.json")
    assert schema_res.status_code == 200
    openapi = schema_res.json()
    assert openapi["info"]["title"] == "Abelink Alumni Graph API"
    assert openapi["servers"][0]["url"] == "http://testserver"

    action_op = openapi["paths"]["/api/v1/search/action-plan"]["post"]
    assert action_op["operationId"] == "recommend_alumni_action_plan"
    assert "UNE SEULE requête" in action_op["description"]

    profile_op = openapi["paths"]["/api/v1/profiles/{profile_id}"]["get"]
    assert profile_op["operationId"] == "get_profile_details"

    graph_op = openapi["paths"]["/api/v1/graph/path"]["get"]
    assert graph_op["operationId"] == "get_connection_graph_path"


def test_rest_search_sse_profile_and_graph_path(client):
    res = client.post(
        "/api/v1/search/action-plan",
        json={"query": "Je cherche un alumni dans l'IA générative chez Mistral AI", "limit": 2},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["solutions"][0]["target"]["full_name"] == "Alice Martin"

    # SSE stream emits all 5 lifecycle events
    with client.stream(
        "POST",
        "/api/v1/search/action-plan/stream",
        json={"query": "Je cherche un alumni chez Mistral AI", "limit": 2},
    ) as stream_res:
        assert stream_res.status_code == 200
        raw_stream = "".join(stream_res.iter_text())

    for ev_name in ("parsing", "hybrid_search", "enrichment", "pathfinding", "final_result"):
        assert f"event: {ev_name}" in raw_stream

    # Profile directory & details endpoints
    dir_res = client.get("/api/v1/profiles?q=Alice&limit=5")
    assert dir_res.status_code == 200
    dir_items = dir_res.json()
    assert len(dir_items) == 1 and dir_items[0]["full_name"] == "Alice Martin"

    alice_id = "22222222-2222-4222-8222-222222222222"
    prof_res = client.get(f"/api/v1/profiles/{alice_id}")
    assert prof_res.status_code == 200
    assert prof_res.json()["current_company"] == "Mistral AI"

    # Draft message endpoint
    draft_rest = client.post(
        "/api/v1/search/draft-message",
        json={
            "first_hop_id": "33333333-3333-4333-8333-333333333333",
            "target_id": alice_id,
            "context": "stage de césure en ML",
        },
    )
    assert draft_rest.status_code == 200
    assert "Thomas" in draft_rest.json()["message"]

    # Graph path visualization endpoint
    graph_res = client.get(f"/api/v1/graph/path?target_id={alice_id}")
    assert graph_res.status_code == 200
    graph_data = graph_res.json()
    assert len(graph_data["paths"]) >= 1
    assert any(n["kind"] == "student" for n in graph_data["nodes"])
    assert any(n["kind"] == "target" and n["id"] == alice_id for n in graph_data["nodes"])
    assert any(e["is_primary"] for e in graph_data["edges"])


def test_linkedin_import_updates_live_graph(client):
    zip_bytes = _build_linkedin_zip_for_api()
    res = client.post(
        "/api/v1/linkedin/import",
        files={"file": ("LinkedIn.zip", zip_bytes, "application/zip")},
        data={"full_name": "Léo Bernard", "promo_year": "2026"},
    )
    assert res.status_code == 200
    summary = res.json()
    assert summary["connections_parsed"] == 1
    assert summary["profiles_matched"] == 1
    assert summary["explicit_edges_created"] == 1

    # Now Sarah Cohen has direct 0.95 LinkedIn edge from Léo -> Alice via Sarah becomes 0.95 * 0.60 = 0.57!
    graph_res = client.get("/api/v1/graph/path?target_id=22222222-2222-4222-8222-222222222222")
    assert graph_res.status_code == 200
    top_path = graph_res.json()["paths"][0]
    assert top_path["hops"][0]["to_name"] == "Sarah Cohen"
    assert top_path["hops"][0]["probability"] == 0.95


def test_bearer_token_lifecycle_and_mcp_streamable_http(client):
    # 1. Create personal Bearer token
    create_res = client.post("/api/v1/tokens", json={"label": "Claude Desktop"})
    assert create_res.status_code == 201
    token_payload = create_res.json()
    raw_token = token_payload["token"]
    token_id = token_payload["id"]
    assert raw_token.startswith("abk_")

    # 2. Authenticate REST /api/v1/me using Bearer token
    me_res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["full_name"] == "Léo Bernard"

    # 3. Invalid Bearer token returns 401
    bad_res = client.get("/api/v1/me", headers={"Authorization": "Bearer abk_invalid"})
    assert bad_res.status_code == 401

    # 4. Call mounted FastMCP Streamable HTTP server (/mcp) with Bearer token
    mcp_headers = {
        "Authorization": f"Bearer {raw_token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    init_res = client.post(
        "/mcp",
        headers=mcp_headers,
        follow_redirects=False,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pytest-mcp", "version": "1.0"},
            },
        },
    )
    assert init_res.status_code == 200

    list_res = client.post(
        "/mcp/",
        headers=mcp_headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert list_res.status_code == 200
    tool_names = {t["name"] for t in list_res.json()["result"]["tools"]}
    assert tool_names == {
        "search_alumni_action_plan",
        "get_more_connections",
        "draft_outreach_message",
    }

    call_res = client.post(
        "/mcp/",
        headers=mcp_headers,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_alumni_action_plan",
                "arguments": {"query": "Je cherche un alumni chez Mistral AI", "limit": 2},
            },
        },
    )
    assert call_res.status_code == 200
    call_result = call_res.json()["result"]
    assert not call_result.get("isError", False)
    payload_text = call_result["content"][0]["text"]
    parsed_payload = json.loads(payload_text)
    assert parsed_payload["student_id"] == "11111111-1111-4111-8111-111111111111"
    assert parsed_payload["solutions"][0]["target"]["full_name"] == "Alice Martin"

    # Secondary MCP tools
    more_res = client.post(
        "/mcp/",
        headers=mcp_headers,
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_more_connections",
                "arguments": {"target_id": "22222222-2222-4222-8222-222222222222"},
            },
        },
    )
    assert more_res.status_code == 200
    more_data = json.loads(more_res.json()["result"]["content"][0]["text"])
    assert len(more_data["paths"]) >= 1

    draft_res = client.post(
        "/mcp/",
        headers=mcp_headers,
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "draft_outreach_message",
                "arguments": {
                    "first_hop_id": "33333333-3333-4333-8333-333333333333",
                    "target_id": "22222222-2222-4222-8222-222222222222",
                    "context": "demande de césure",
                },
            },
        },
    )
    assert draft_res.status_code == 200
    draft_data = json.loads(draft_res.json()["result"]["content"][0]["text"])
    assert "Thomas" in draft_data["message"]

    # 5. Revoke token -> subsequent Bearer auth fails
    del_res = client.delete(f"/api/v1/tokens/{token_id}")
    assert del_res.status_code == 204
    revoked_res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw_token}"})
    assert revoked_res.status_code == 401
