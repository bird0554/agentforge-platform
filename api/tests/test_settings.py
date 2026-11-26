from __future__ import annotations

from fastapi.testclient import TestClient

from app import settings as settings_store
from app.main import app
from app.provider import OpenAICompatibleProvider


def test_model_settings_encrypt_key_and_never_return_it(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("APP_SECRET", "test-secret-with-more-than-thirty-two-characters")

    with TestClient(app) as client:
        response = client.put("/api/settings/model", json={
            "provider": "openai-compatible",
            "base_url": "https://models.example.test/v1",
            "model": "example-model",
            "api_key": "private-api-key-value",
            "timeout_seconds": 12,
            "temperature": 0.4,
            "max_tokens": 2048,
        })

        assert response.status_code == 200
        assert response.json()["model"]["api_key_configured"] is True
        assert "private-api-key-value" not in response.text
        stored = settings_store.get_model_settings()
        assert stored["api_key_encrypted"] != "private-api-key-value"
        assert settings_store.runtime_model_settings()["api_key"] == "private-api-key-value"


def test_agent_settings_are_persisted_and_validated(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")

    with TestClient(app) as client:
        response = client.put("/api/settings/agent", json={
            "name": "Operations Assistant",
            "mode": "self_critique",
            "max_tool_rounds": 7,
            "history_window": 12,
            "context_window_tokens": 4096,
        })
        assert response.status_code == 200
        assert response.json()["agent"]["mode"] == "self_critique"
        assert client.put("/api/settings/agent", json={"max_tool_rounds": 21}).status_code == 422
        assert client.get("/api/settings").json()["agent"]["context_window_tokens"] == 4096


def test_model_test_uses_temporary_values_without_saving(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    captured = {}

    async def fake_test_connection(provider):
        captured["provider"] = provider

    monkeypatch.setattr(OpenAICompatibleProvider, "test_connection", fake_test_connection)

    with TestClient(app) as client:
        saved_before = settings_store.public_model_settings()
        response = client.post("/api/settings/model/test", json={
            "provider": "openai-compatible",
            "base_url": "https://temporary.example.test/v1",
            "model": "temporary-model",
            "api_key": "temporary-secret",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert captured["provider"].model == "temporary-model"
        assert captured["provider"].api_key == "temporary-secret"
        assert settings_store.public_model_settings() == saved_before


def test_tool_policy_updates_and_session_delete(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")

    with TestClient(app) as client:
        disabled = client.patch("/api/settings/tools/calculator", json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json()["tool"]["enabled"] is False
        tools = client.get("/api/tools").json()["items"]
        assert next(tool for tool in tools if tool["name"] == "calculator")["enabled"] is False
        assert client.patch("/api/settings/tools/ticket_create", json={"permission": "read"}).status_code == 422

        run = client.post("/api/agents/runs", json={"message": "hello"}).json()
        assert run["session_id"]
        assert client.get("/api/agents/runs").json()["items"][0]["id"] == run["id"]
        assert client.delete(f"/api/agents/sessions/{run['session_id']}").json()["deleted"] is True
        assert client.get(f"/api/agents/sessions/{run['session_id']}").status_code == 404
