from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import database
from .auth import current_tenant
from .settings import _read, _write, decrypt_secret, encrypt_secret


router = APIRouter(prefix="/api/a2a", tags=["A2A"])
_SETTINGS_KEY = "a2a"
_MAX_RESPONSE_BYTES = 1_000_000


class AgentConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=1000)
    bearer_token: str | None = Field(default=None, max_length=4096)
    clear_bearer_token: bool = False
    timeout_seconds: float = Field(default=20, ge=1, le=120)
    enabled: bool = True


class DelegateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    context_id: str | None = Field(default=None, max_length=200)


def _validate_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(422, "Agent URL must use HTTP or HTTPS and include a hostname")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(422, "Agent URL cannot contain credentials, query parameters, or a fragment")
    return url


def _load_agents() -> list[dict[str, Any]]:
    agents = _read(_SETTINGS_KEY, {"agents": []}).get("agents", [])
    return agents if isinstance(agents, list) else []


def _public_agent(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": agent["id"],
        "name": agent["name"],
        "url": agent["url"],
        "timeout_seconds": agent["timeout_seconds"],
        "bearer_token_configured": bool(agent.get("bearer_token_encrypted")),
        "agent_card": agent.get("agent_card"),
        "enabled": agent.get("enabled", True),
    }


def _get_agent(agent_id: str) -> dict[str, Any]:
    agent = next((item for item in _load_agents() if item.get("id") == agent_id), None)
    if not agent:
        raise HTTPException(404, "A2A agent connection not found")
    return agent


def _save_agents(agents: list[dict[str, Any]]) -> None:
    _write(_SETTINGS_KEY, {"agents": agents})


def _audit(event: str, resource_id: str, payload: dict[str, Any]) -> None:
    with database.connection() as db:
        database.add_audit_event(db, current_tenant(), event, "a2a_agent", resource_id, payload)


def _headers(agent: dict[str, Any]) -> dict[str, str]:
    encrypted = agent.get("bearer_token_encrypted", "")
    if not encrypted:
        return {"Content-Type": "application/json"}
    try:
        token = decrypt_secret(encrypted)
    except ValueError as exc:
        raise HTTPException(409, "Saved A2A credential cannot be decrypted. Save the connection again.") from exc
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


async def _get_json(agent: dict[str, Any], path: str) -> Any:
    try:
        async with httpx.AsyncClient(timeout=float(agent["timeout_seconds"]), follow_redirects=False) as client:
            response = await client.get(f"{agent['url']}{path}", headers=_headers(agent))
            response.raise_for_status()
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise HTTPException(502, "A2A agent response exceeds the size limit")
            return response.json()
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "A2A agent request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"A2A agent returned HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "Unable to read a valid JSON response from the A2A agent") from exc


async def _rpc(agent: dict[str, Any], method: str, params: dict[str, Any]) -> Any:
    request_id = str(uuid.uuid4())
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    try:
        async with httpx.AsyncClient(timeout=float(agent["timeout_seconds"]), follow_redirects=False) as client:
            response = await client.post(f"{agent['url']}", headers=_headers(agent), json=body)
            response.raise_for_status()
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise HTTPException(502, "A2A agent response exceeds the size limit")
            payload = response.json()
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "A2A task request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"A2A agent returned HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "Unable to read a valid JSON-RPC response from the A2A agent") from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise HTTPException(502, "A2A agent returned an invalid JSON-RPC envelope")
    if payload.get("id") != request_id:
        raise HTTPException(502, "A2A JSON-RPC response id did not match the request")
    if payload.get("error"):
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else "unknown"
        raise HTTPException(502, f"A2A agent rejected {method} (error {code})")
    if "result" not in payload:
        raise HTTPException(502, "A2A JSON-RPC response is missing result")
    return payload["result"]


@router.get("/agents")
async def list_agent_connections() -> dict[str, Any]:
    return {"items": [_public_agent(agent) for agent in _load_agents()]}


@router.post("/agents")
async def create_agent_connection(request: AgentConnectionRequest) -> dict[str, Any]:
    agent_id = str(uuid.uuid4())
    agent = {
        "id": agent_id,
        "name": request.name.strip(),
        "url": _validate_url(request.url),
        "timeout_seconds": request.timeout_seconds,
        "enabled": request.enabled,
        "bearer_token_encrypted": encrypt_secret(request.bearer_token.strip()) if request.bearer_token and request.bearer_token.strip() else "",
        "agent_card": None,
    }
    agents = _load_agents()
    agents.append(agent)
    _save_agents(agents)
    _audit("a2a.connection.created", agent_id, {"name": agent["name"], "url": agent["url"]})
    return {"agent": _public_agent(agent)}


@router.put("/agents/{agent_id}")
async def update_agent_connection(agent_id: str, request: AgentConnectionRequest) -> dict[str, Any]:
    agents = _load_agents()
    agent = next((item for item in agents if item.get("id") == agent_id), None)
    if not agent:
        raise HTTPException(404, "A2A agent connection not found")
    agent.update({"name": request.name.strip(), "url": _validate_url(request.url), "timeout_seconds": request.timeout_seconds, "enabled": request.enabled})
    if request.clear_bearer_token:
        agent["bearer_token_encrypted"] = ""
    elif request.bearer_token and request.bearer_token.strip():
        agent["bearer_token_encrypted"] = encrypt_secret(request.bearer_token.strip())
    agents[agents.index(next(item for item in agents if item.get("id") == agent_id))] = agent
    _save_agents(agents)
    _audit("a2a.connection.updated", agent_id, {"name": agent["name"], "url": agent["url"]})
    return {"agent": _public_agent(agent)}


@router.delete("/agents/{agent_id}")
async def delete_agent_connection(agent_id: str) -> dict[str, Any]:
    agents = _load_agents()
    remaining = [item for item in agents if item.get("id") != agent_id]
    if len(remaining) == len(agents):
        raise HTTPException(404, "A2A agent connection not found")
    _save_agents(remaining)
    _audit("a2a.connection.deleted", agent_id, {})
    return {"id": agent_id, "deleted": True}


@router.post("/agents/{agent_id}/discover")
async def discover_agent(agent_id: str) -> dict[str, Any]:
    agent = _get_agent(agent_id)
    card = await _get_json(agent, "/.well-known/agent-card.json")
    if not isinstance(card, dict) or not isinstance(card.get("name"), str):
        raise HTTPException(502, "The remote endpoint did not return a valid A2A Agent Card")
    agents = _load_agents()
    saved = next(item for item in agents if item.get("id") == agent_id)
    saved["agent_card"] = card
    _save_agents(agents)
    return {"agent": _public_agent(saved), "agent_card": card}


@router.post("/agents/{agent_id}/tasks")
async def delegate_task(agent_id: str, request: DelegateRequest) -> dict[str, Any]:
    agent = _get_agent(agent_id)
    if not agent.get("enabled", True):
        raise HTTPException(403, "A2A agent connection is disabled")
    from .tools import execute_tool

    tool_name = f"a2a__{agent_id}__delegate"
    result = await execute_tool(
        tool_name,
        request.model_dump(exclude_none=True),
        current_tenant(),
        f"direct-a2a:{agent_id}",
    )
    if result.get("approval_required"):
        return {"agent_id": agent_id, **result}
    if result.get("status") != "success":
        raise HTTPException(502, "A2A task delegation failed")
    return {"agent_id": agent_id, "result": result.get("result")}


@router.get("/agents/{agent_id}/tasks/{task_id}")
async def get_remote_task(agent_id: str, task_id: str) -> dict[str, Any]:
    agent = _get_agent(agent_id)
    if not agent.get("enabled", True):
        raise HTTPException(403, "A2A agent connection is disabled")
    result = await _rpc(agent, "tasks/get", {"id": task_id})
    return {"agent_id": agent_id, "result": result}


def a2a_tool_schemas() -> list[dict[str, Any]]:
    """Expose enabled configured A2A connections as model-callable delegation tools."""
    return [{
        "type": "function",
        "function": {
            "name": f"a2a__{agent['id']}__delegate",
            "description": f"Delegate a task to the configured A2A agent {agent['name']}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "minLength": 1, "maxLength": 8000},
                    "context_id": {"type": "string", "maxLength": 200},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    } for agent in _load_agents() if agent.get("enabled", True)]


async def execute_a2a_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    parts = name.split("__", 2)
    if len(parts) != 3 or parts[0] != "a2a" or parts[2] != "delegate":
        raise ValueError("Invalid A2A tool name")
    try:
        validated = DelegateRequest.model_validate(arguments)
    except Exception as exc:
        raise ValueError("A2A delegation arguments are invalid") from exc
    agent = _get_agent(parts[1])
    if not agent.get("enabled", True):
        raise ValueError("A2A agent connection is disabled")
    message = {"messageId": str(uuid.uuid4()), "role": "user", "parts": [{"kind": "text", "text": validated.message}]}
    if validated.context_id:
        message["contextId"] = validated.context_id
    result = await _rpc(agent, "message/send", {"message": message})
    _audit("a2a.tool.delegated", agent["id"], {"tool": name})
    return {"result": result, "status": "success"}
