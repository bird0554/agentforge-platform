import asyncio
import os

os.environ["DATABASE_URL"] = "sqlite:///./test-agent.db"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import mcp
from app.tools import execute_tool


@pytest.fixture(autouse=True)
def reset_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")


def test_demo_calculation_and_approval():
    with TestClient(app) as client:
        response = client.post("/api/agents/runs", json={"message": "Calculate 12 * 3"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert "36" in payload["steps"][0]["result"]

        ticket = client.post("/api/agents/runs", json={"message": "Create a ticket for a broken sync"}).json()
        assert ticket["status"] == "awaiting_approval"
        approval_id = ticket["approval_id"]
        approved = client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "approve"})
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"


def test_remote_write_tool_requires_approval_and_runs_after_approval(monkeypatch):
    with TestClient(app) as client:
        configured = client.put("/api/mcp/servers/records", json={
            "endpoint": "https://mcp.example.test/rpc",
        })
        assert configured.status_code == 200
        server = mcp._read_servers()["records"]
        server["tools"] = [{
            "name": "update_record",
            "description": "Update a record",
            "inputSchema": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        }]
        mcp._save_server("records", server)
        tool_name = "mcp__records__update_record"
        policy = client.patch(f"/api/settings/tools/{tool_name}", json={
            "enabled": True,
            "permission": "write",
            "timeout_seconds": 5,
        })
        assert policy.status_code == 200

        pending = asyncio.run(execute_tool(tool_name, {"id": "42"}, "demo-tenant", "conversation-1"))
        assert pending["approval_required"] is True
        called = []

        async def call_remote(name, arguments):
            called.append((name, arguments))
            return {"result": {"updated": True}, "status": "success"}

        monkeypatch.setattr(mcp, "execute_mcp_tool", call_remote)
        approved = client.post(f"/api/approvals/{pending['approval_id']}/decision", json={"decision": "approve"})
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert called == [(tool_name, {"id": "42"})]

        disabled = client.patch(f"/api/settings/tools/{tool_name}", json={"enabled": False})
        assert disabled.status_code == 200
        result = asyncio.run(execute_tool(tool_name, {"id": "43"}, "demo-tenant", "conversation-1"))
        assert result["status"] == "failed"
        assert len(called) == 1
