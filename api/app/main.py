from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from . import database
from .agent import delete_session, get_session, list_runs, list_sessions, run_agent
from .provider import OpenAICompatibleProvider
from .security import redact
from .settings import (
    get_agent_settings,
    get_model_settings,
    get_tool_settings,
    public_model_settings,
    runtime_model_settings,
    save_agent_settings,
    save_model_settings,
    save_tool_settings,
    validate_app_secret,
)
from .tools import TOOLS, decide_approval, list_tools
from .sandbox import router as sandbox_router, get_settings as get_sandbox_settings
from .mcp import router as mcp_router
from .a2a_runtime import router as a2a_router
from .a2a_runtime import list_agent_connections
from .mcp import list_mcp_servers
from .vector_memory import router as memory_router
from .vector_memory import get_memory_settings
from .auth import auth_middleware, current_tenant, current_user


class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


class ModelSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["demo", "openai-compatible"] | None = None
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    timeout_seconds: float | None = Field(default=None, ge=1, le=300)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)


class AgentSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    mode: Literal["react", "plan_execute", "self_critique"] | None = None
    max_tool_rounds: int | None = Field(default=None, ge=1, le=20)
    history_window: int | None = Field(default=None, ge=1, le=100)
    context_window_tokens: int | None = Field(default=None, ge=512, le=128000)


class ToolSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    permission: Literal["read", "write"] | None = None
    timeout_seconds: float | None = Field(default=None, ge=0.1, le=300)


def _audit(event_type: str, resource_type: str, resource_id: str | None, payload: dict[str, Any] | None = None) -> None:
    with database.connection() as db:
        database.add_audit_event(db, current_tenant(), event_type, resource_type, resource_id, payload, actor=current_user())


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    validate_app_secret()
    yield


app = FastAPI(title="Agent Foundry API", version="0.1.0", lifespan=lifespan)
app.middleware("http")(auth_middleware)
app.include_router(sandbox_router)
app.include_router(mcp_router)
app.include_router(a2a_router)
app.include_router(memory_router)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("WEB_ORIGIN", "http://localhost:5173")], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    model = public_model_settings()
    return {"status": "ok", "service": "agent-foundry", "mode": "connected" if model["provider"] != "demo" and model["api_key_configured"] else "demo"}


@app.get("/api/settings")
async def settings() -> dict[str, Any]:
    return {
        "model": public_model_settings(), "agent": get_agent_settings(), "tools": list_tools(),
        "sandbox": {**get_sandbox_settings(), "runtime_available": __import__("shutil").which("docker") is not None},
        "memory": get_memory_settings(), "mcp": {"servers": list_mcp_servers()},
        "a2a": {"agents": (await list_agent_connections())["items"]},
    }


@app.put("/api/settings/model")
async def update_model_settings(request: ModelSettingsRequest) -> dict[str, Any]:
    current = get_model_settings()
    updates = request.model_dump(exclude={"api_key", "clear_api_key"}, exclude_none=True)
    merged = {key: current.get(key) for key in ("provider", "base_url", "model", "timeout_seconds", "temperature", "max_tokens")}
    merged.update(updates)
    merged["base_url"] = (merged.get("base_url") or "").strip().rstrip("/")
    merged["model"] = (merged.get("model") or "").strip()
    if merged["provider"] == "openai-compatible" and not merged["base_url"]:
        raise HTTPException(422, "base_url is required for an OpenAI-compatible provider")
    if merged["provider"] == "openai-compatible":
        parsed_url = urlsplit(merged["base_url"])
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
            raise HTTPException(422, "base_url must be a valid HTTP or HTTPS endpoint URL")
        if not (request.api_key or "").strip() and not current.get("api_key_encrypted"):
            raise HTTPException(422, "An API key is required for an OpenAI-compatible provider")
        if request.clear_api_key:
            raise HTTPException(422, "An API key is required for an OpenAI-compatible provider")
    save_model_settings(merged, request.api_key.strip() if request.api_key is not None else None, request.clear_api_key)
    _audit("settings.model.updated", "settings", "model", {"provider": merged["provider"], "model": merged["model"]})
    return {"model": public_model_settings()}


@app.put("/api/settings/agent")
async def update_agent_settings(request: AgentSettingsRequest) -> dict[str, Any]:
    current = get_agent_settings()
    updates = request.model_dump(exclude_none=True)
    current.update(updates)
    saved = save_agent_settings(current)
    _audit("settings.agent.updated", "settings", "agent", {"mode": saved["mode"]})
    return {"agent": saved}


@app.patch("/api/settings/tools/{name}")
async def update_tool_settings(name: str, request: ToolSettingsRequest) -> dict[str, Any]:
    registered_names = {item["name"] for item in list_tools()}
    if name not in TOOLS and name not in registered_names:
        raise HTTPException(404, "Tool not found")
    current = get_tool_settings(name)
    current.update(request.model_dump(exclude_none=True))
    if current["permission"] not in {None, "read", "write"}:
        raise HTTPException(422, "Tool permission must be read or write")
    if name in TOOLS and TOOLS[name].permission == "write" and current["permission"] not in {None, "write"}:
        raise HTTPException(422, "Write tools must retain write permission")
    saved = save_tool_settings(name, {key: current[key] for key in ("enabled", "permission", "timeout_seconds")})
    _audit("settings.tool.updated", "tool", name, {"enabled": saved["enabled"], "permission": saved["permission"]})
    return {"tool": next(item for item in list_tools() if item["name"] == name)}


@app.post("/api/settings/model/test")
async def test_model_settings(request: ModelSettingsRequest) -> dict[str, Any]:
    try:
        current = runtime_model_settings()
    except ValueError:
        return {
            "status": "failed",
            "provider": "unknown",
            "message": "Saved model configuration is unavailable. Save the model settings again.",
        }
    updates = request.model_dump(exclude={"api_key", "clear_api_key"}, exclude_none=True)
    current.update(updates)
    if request.clear_api_key:
        current["api_key"] = ""
    elif request.api_key and request.api_key.strip():
        current["api_key"] = request.api_key.strip()
    current["base_url"] = (current.get("base_url") or "").strip().rstrip("/")
    if current.get("provider") == "openai-compatible":
        parsed_url = urlsplit(current["base_url"])
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
            raise HTTPException(422, "base_url must be a valid HTTP or HTTPS endpoint URL")
    provider = OpenAICompatibleProvider(current)
    if provider.provider == "demo":
        return {"status": "ok", "provider": "demo", "message": "Demo provider is ready"}
    try:
        await provider.test_connection()
    except httpx.HTTPStatusError as exc:
        detail = f"Model endpoint returned HTTP {exc.response.status_code}"
        return {"status": "failed", "provider": provider.provider, "message": detail}
    except httpx.TimeoutException:
        detail = "Model endpoint request timed out"
        return {"status": "failed", "provider": provider.provider, "message": detail}
    except httpx.HTTPError:
        detail = "Unable to connect to model endpoint"
        return {"status": "failed", "provider": provider.provider, "message": detail}
    except ValueError:
        detail = "Model endpoint returned an invalid response or configuration"
        return {"status": "failed", "provider": provider.provider, "message": detail}
    return {"status": "ok", "provider": provider.provider, "model": provider.model, "message": "Model endpoint is reachable"}


@app.get("/api/agents/sessions")
async def sessions() -> dict[str, Any]:
    return {"items": list_sessions()}


@app.get("/api/agents/sessions/{session_id}")
async def session_detail(session_id: str) -> dict[str, Any]:
    item = get_session(session_id)
    if not item:
        raise HTTPException(404, "Session not found")
    return item


@app.delete("/api/agents/sessions/{session_id}")
async def remove_session(session_id: str) -> dict[str, Any]:
    if not delete_session(session_id):
        raise HTTPException(404, "Session not found")
    _audit("session.deleted", "conversation", session_id)
    return {"id": session_id, "deleted": True}


@app.get("/api/tools")
async def tools() -> dict[str, Any]:
    return {"items": list_tools()}


@app.post("/api/agents/runs")
async def create_run(request: RunRequest) -> dict[str, Any]:
    try:
        return await run_agent(request.message, request.session_id)
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/agents/runs")
async def runs(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return {"items": list_runs(limit, offset)}


@app.get("/api/agents/runs/{run_id}")
async def run_detail(run_id: str) -> dict[str, Any]:
    with database.connection() as db:
        row = db.execute("SELECT id, conversation_id, status, response, steps FROM agent_runs WHERE id = ? AND tenant_id = ?", (run_id, current_tenant())).fetchone()
    if not row:
        raise HTTPException(404, "Run not found")
    return {"id": row["id"], "session_id": row["conversation_id"], "status": row["status"], "response": row["response"], "steps": json.loads(row["steps"])}


@app.get("/api/approvals")
async def approvals() -> dict[str, Any]:
    with database.connection() as db:
        rows = db.execute("SELECT id, tool_name, arguments, status, created_at, reviewed_at FROM approvals WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 50", (current_tenant(),)).fetchall()
    return {"items": [{**dict(row), "arguments": redact(json.loads(row["arguments"]))} for row in rows]}


@app.post("/api/approvals/{approval_id}/decision")
async def approval_decision(approval_id: str, request: ApprovalDecision) -> dict[str, Any]:
    result = await decide_approval(approval_id, current_tenant(), request.decision)
    if not result:
        raise HTTPException(404, "Pending approval not found")
    return result


@app.get("/api/metrics/summary")
async def metrics() -> dict[str, Any]:
    with database.connection() as db:
        tool_runs = db.execute("SELECT COUNT(*) AS count FROM tool_runs WHERE tenant_id = ?", (current_tenant(),)).fetchone()["count"]
        success = db.execute("SELECT COUNT(*) AS count FROM tool_runs WHERE tenant_id = ? AND status IN ('success', 'approved')", (current_tenant(),)).fetchone()["count"]
        pending = db.execute("SELECT COUNT(*) AS count FROM approvals WHERE tenant_id = ? AND status = 'pending'", (current_tenant(),)).fetchone()["count"]
    return {"tool_runs": tool_runs, "successful_runs": success, "pending_approvals": pending, "success_rate": round(success / tool_runs, 3) if tool_runs else 0}
