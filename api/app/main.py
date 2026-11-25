from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import database
from .agent import get_session, list_sessions, run_agent
from .security import redact
from .tools import decide_approval, list_tools


class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Agent Foundry API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("WEB_ORIGIN", "http://localhost:5173")], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "agent-foundry", "mode": "connected" if os.getenv("LLM_API_KEY") else "demo"}


@app.get("/api/agents/sessions")
async def sessions() -> dict[str, Any]:
    return {"items": list_sessions()}


@app.get("/api/agents/sessions/{session_id}")
async def session_detail(session_id: str) -> dict[str, Any]:
    item = get_session(session_id)
    if not item:
        raise HTTPException(404, "Session not found")
    return item


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


@app.get("/api/agents/runs/{run_id}")
async def run_detail(run_id: str) -> dict[str, Any]:
    with database.connection() as db:
        row = db.execute("SELECT id, conversation_id, status, response, steps FROM agent_runs WHERE id = ? AND tenant_id = ?", (run_id, "demo-tenant")).fetchone()
    if not row:
        raise HTTPException(404, "Run not found")
    return {"id": row["id"], "session_id": row["conversation_id"], "status": row["status"], "response": row["response"], "steps": json.loads(row["steps"])}


@app.get("/api/approvals")
async def approvals() -> dict[str, Any]:
    with database.connection() as db:
        rows = db.execute("SELECT id, tool_name, arguments, status, created_at, reviewed_at FROM approvals WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 50", ("demo-tenant",)).fetchall()
    return {"items": [{**dict(row), "arguments": redact(json.loads(row["arguments"]))} for row in rows]}


@app.post("/api/approvals/{approval_id}/decision")
async def approval_decision(approval_id: str, request: ApprovalDecision) -> dict[str, Any]:
    result = decide_approval(approval_id, "demo-tenant", request.decision)
    if not result:
        raise HTTPException(404, "Pending approval not found")
    return result


@app.get("/api/metrics/summary")
async def metrics() -> dict[str, Any]:
    with database.connection() as db:
        tool_runs = db.execute("SELECT COUNT(*) AS count FROM tool_runs WHERE tenant_id = ?", ("demo-tenant",)).fetchone()["count"]
        success = db.execute("SELECT COUNT(*) AS count FROM tool_runs WHERE tenant_id = ? AND status IN ('success', 'approved')", ("demo-tenant",)).fetchone()["count"]
        pending = db.execute("SELECT COUNT(*) AS count FROM approvals WHERE tenant_id = ? AND status = 'pending'", ("demo-tenant",)).fetchone()["count"]
    return {"tool_runs": tool_runs, "successful_runs": success, "pending_approvals": pending, "success_rate": round(success / tool_runs, 3) if tool_runs else 0}
