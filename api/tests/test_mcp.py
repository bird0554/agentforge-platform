from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app import mcp
from app import settings


def _app() -> FastAPI:
    application = FastAPI()
    application.include_router(mcp.router)
    return application


def test_mcp_server_config_encrypts_headers_and_hides_values(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("APP_SECRET", "test-secret-with-more-than-thirty-two-characters")
    database.init_db()

    with TestClient(_app()) as client:
        response = client.put("/api/mcp/servers/support", json={
            "endpoint": "https://mcp.example.test/rpc",
            "headers": {"Authorization": "Bearer private-token"},
            "timeout_seconds": 7,
        })
        assert response.status_code == 200
        assert response.json()["server"]["headers_configured"] is True
        assert "private-token" not in response.text
        stored = next(value for key, value in mcp._read_servers().items() if key == "support")
        assert "private-token" not in json.dumps(stored)


def test_mcp_client_initializes_discovers_and_calls(monkeypatch):
    responses = [
        {"result": {"protocolVersion": "2024-11-05"}},
        {"result": {"tools": [{
            "name": "lookup", "description": "Lookup a record", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
        }]}},
        {"result": {"protocolVersion": "2024-11-05"}},
        {"result": {"content": [{"type": "text", "text": "found"}]}},
    ]

    class Response:
        headers = {"content-type": "application/json"}
        content = b"{}"
        text = "{}"

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            request = kwargs["json"]
            if "id" not in request:
                return Response({})
            payload = responses.pop(0)
            return Response({"jsonrpc": "2.0", "id": request["id"], **payload})

    monkeypatch.setattr(mcp.httpx, "AsyncClient", Client)
    client = mcp.MCPClient("support", "https://mcp.example.test/rpc", "streamable_http", {}, 3)
    tools = asyncio.run(client.list_tools())
    assert tools[0]["name"] == "lookup"
    result = asyncio.run(client.call_tool("lookup", {"id": "42"}))
    assert result["content"][0]["text"] == "found"


def test_direct_mcp_call_requires_enabled_discovered_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("APP_SECRET", "test-secret-with-more-than-thirty-two-characters")
    database.init_db()

    with TestClient(_app()) as client:
        client.put("/api/mcp/servers/support", json={
            "endpoint": "https://mcp.example.test/rpc", "enabled": False,
        })
        disabled = client.post("/api/mcp/servers/support/tools/lookup/call", json={})
        assert disabled.status_code == 403

        client.put("/api/mcp/servers/support", json={
            "endpoint": "https://mcp.example.test/rpc", "enabled": True,
        })
        undiscovered = client.post("/api/mcp/servers/support/tools/lookup/call", json={})
        assert undiscovered.status_code == 404


def test_mcp_tool_schema_is_validated_and_write_tools_require_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("APP_SECRET", "test-secret-with-more-than-thirty-two-characters")
    database.init_db()
    mcp._save_server("support", {
        "endpoint": "https://mcp.example.test/rpc", "transport": "streamable_http",
        "timeout_seconds": 7, "enabled": True, "headers_encrypted": "", "tools": [{
            "name": "update", "description": "Update a record",
            "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"], "additionalProperties": False},
        }],
    })

    async def fake_call(self, tool_name, arguments):
        return {"content": [{"type": "text", "text": "updated"}]}

    monkeypatch.setattr(mcp.MCPClient, "call_tool", fake_call)
    with TestClient(_app()) as client:
        invalid = client.post("/api/mcp/servers/support/tools/update/call", json={"arguments": {}})
        assert invalid.status_code == 422
        settings.save_tool_settings("mcp__support__update", {"permission": "write", "enabled": True, "timeout_seconds": 4})
        pending = client.post("/api/mcp/servers/support/tools/update/call", json={"arguments": {"id": "42"}})
        assert pending.status_code == 200
        assert pending.json()["approval_required"] is True
