from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import a2a_runtime, database, settings


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("APP_SECRET", "test-secret-with-more-than-thirty-two-characters")
    database.init_db()
    app = FastAPI()
    app.include_router(a2a_runtime.router)
    return TestClient(app)


def test_a2a_connection_persists_without_returning_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.post("/api/a2a/agents", json={
            "name": "Research agent",
            "url": "https://agent.example.test",
            "bearer_token": "secret-token",
        })
        assert response.status_code == 200
        payload = response.json()["agent"]
        assert payload["bearer_token_configured"] is True
        assert "secret-token" not in response.text
        stored = settings._read("a2a", {})["agents"][0]
        assert stored["bearer_token_encrypted"] != "secret-token"
        assert client.get("/api/a2a/agents").json()["items"][0]["id"] == payload["id"]


def test_a2a_url_validation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.post("/api/a2a/agents", json={"name": "x", "url": "file:///tmp/a"}).status_code == 422
        assert client.post("/api/a2a/agents", json={"name": "x", "url": "https://user:pass@example.test"}).status_code == 422


def test_a2a_discovery_and_task_delegation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        created = client.post("/api/a2a/agents", json={"name": "Remote", "url": "https://agent.example.test"}).json()["agent"]

        async def fake_discovery(agent, path):
            assert path == "/.well-known/agent-card.json"
            return {"name": "Remote", "version": "1", "skills": [{"id": "research"}]}

        async def fake_rpc(agent, method, params):
            assert method == "message/send"
            assert params["message"]["parts"][0]["text"] == "Find the answer"
            return {"id": "task-1", "status": {"state": "working"}}

        monkeypatch.setattr(a2a_runtime, "_get_json", fake_discovery)
        monkeypatch.setattr(a2a_runtime, "_rpc", fake_rpc)
        discovered = client.post(f"/api/a2a/agents/{created['id']}/discover")
        assert discovered.status_code == 200
        assert discovered.json()["agent_card"]["name"] == "Remote"
        delegated = client.post(f"/api/a2a/agents/{created['id']}/tasks", json={"message": "Find the answer"})
        assert delegated.status_code == 200
        assert delegated.json()["result"]["id"] == "task-1"


def test_disabled_a2a_connection_cannot_query_tasks(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        created = client.post("/api/a2a/agents", json={
            "name": "Remote", "url": "https://agent.example.test", "enabled": False,
        }).json()["agent"]
        response = client.get(f"/api/a2a/agents/{created['id']}/tasks/task-1")
        assert response.status_code == 403
