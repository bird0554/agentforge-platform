import os

os.environ["DATABASE_URL"] = "sqlite:///./test-agent.db"

import pytest
from fastapi.testclient import TestClient

from app.main import app


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
