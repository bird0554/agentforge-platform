"""Configurable MCP client and management routes.

The client implements the MCP JSON-RPC lifecycle over HTTP.  It accepts both
normal JSON responses and Server-Sent Events responses used by MCP servers.
Remote tool schemas are persisted as non-secret metadata so they can be
exposed to the Agent without contacting every server during each model turn.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import database
from .auth import current_tenant, current_user
from .security import redact
from .settings import decrypt_secret, encrypt_secret, get_tool_settings


MCP_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
_SETTING_KEY = "mcp:servers"
_MAX_BODY = 2_000_000
_MAX_SCHEMA_CHARS = 64_000


class MCPServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=2000)
    transport: str = Field(default="streamable_http", pattern="^(streamable_http|sse)$")
    headers: dict[str, str] = Field(default_factory=dict)
    clear_headers: bool = False
    timeout_seconds: float = Field(default=20, ge=1, le=300)
    enabled: bool = True


class MCPToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)


def _validate_endpoint(endpoint: str) -> str:
    value = endpoint.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("MCP endpoint must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("MCP endpoint must not contain credentials or fragments")
    if len(value) > 2000:
        raise ValueError("MCP endpoint is too long")
    return value


def _validate_headers(headers: dict[str, str]) -> dict[str, str]:
    if len(headers) > 32:
        raise ValueError("MCP supports at most 32 custom headers")
    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        name = key.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}", name):
            raise ValueError(f"Invalid MCP header name: {name}")
        if len(value) > 4096:
            raise ValueError(f"MCP header is too long: {name}")
        cleaned[name] = str(value)
    return cleaned


def _read_servers() -> dict[str, dict[str, Any]]:
    with database.connection() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key = ?", (_SETTING_KEY,)).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_servers(value: dict[str, dict[str, Any]]) -> None:
    with database.connection() as db:
        db.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (_SETTING_KEY, json.dumps(value, ensure_ascii=False)),
        )


def _stored_headers(record: dict[str, Any]) -> dict[str, str]:
    encrypted = record.get("headers_encrypted", "")
    if not encrypted:
        return {}
    try:
        value = json.loads(decrypt_secret(encrypted))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("Stored MCP credentials cannot be decrypted. Check APP_SECRET.")
    return _validate_headers(value) if isinstance(value, dict) else {}


def _public_server(name: str, record: dict[str, Any]) -> dict[str, Any]:
    tools = record.get("tools", [])
    if not isinstance(tools, list):
        tools = []
    return {
        "name": name,
        "endpoint": record.get("endpoint", ""),
        "transport": record.get("transport", "streamable_http"),
        "enabled": bool(record.get("enabled", True)),
        "timeout_seconds": float(record.get("timeout_seconds", 20)),
        "headers_configured": bool(record.get("headers_encrypted")),
        "tools": tools,
        "last_discovered_at": record.get("last_discovered_at"),
        "last_error": record.get("last_error"),
    }


def list_mcp_servers() -> list[dict[str, Any]]:
    return [_public_server(name, record) for name, record in _read_servers().items()]


def _server(name: str) -> dict[str, Any]:
    record = _read_servers().get(name)
    if not record:
        raise KeyError(name)
    return record


def _save_server(name: str, record: dict[str, Any]) -> None:
    servers = _read_servers()
    servers[name] = record
    _write_servers(servers)


def _audit(event_type: str, resource_id: str, payload: dict[str, Any] | None = None) -> None:
    with database.connection() as db:
        database.add_audit_event(db, current_tenant(), event_type, "mcp_server", resource_id, payload)


@dataclass
class MCPClient:
    name: str
    endpoint: str
    transport: str
    headers: dict[str, str]
    timeout_seconds: float
    session_endpoint: str | None = None
    session_id: str | None = None

    @classmethod
    def from_record(cls, name: str, record: dict[str, Any]) -> "MCPClient":
        return cls(
            name=name,
            endpoint=_validate_endpoint(str(record.get("endpoint", ""))),
            transport=str(record.get("transport", "streamable_http")),
            headers=_stored_headers(record),
            timeout_seconds=max(1, min(float(record.get("timeout_seconds", 20)), 300)),
        )

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.transport == "sse":
            await self._ensure_sse_endpoint()
        request_id = str(uuid.uuid4())
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        headers = self._request_headers()
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(self.session_endpoint or self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            self.session_id = response.headers.get("mcp-session-id") or self.session_id
            if len(response.content) > _MAX_BODY:
                raise ValueError("MCP response exceeds the configured size limit")
            return _parse_rpc_response(response, request_id)

    async def initialize(self) -> dict[str, Any]:
        result = await self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "agent-forge", "version": "0.1.0"},
        })
        # MCP servers expect this notification after the initialize response.
        await self._notification("notifications/initialized")
        return result

    async def _notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self.transport == "sse":
            await self._ensure_sse_endpoint()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        headers = self._request_headers()
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(self.session_endpoint or self.endpoint, headers=headers, json=payload)
            response.raise_for_status()

    def _request_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **self.headers}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def _ensure_sse_endpoint(self) -> None:
        if self.session_endpoint:
            return
        headers = {"Accept": "text/event-stream", **self.headers}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            async with client.stream("GET", self.endpoint, headers=headers) as response:
                response.raise_for_status()
                event_name = ""
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif not line and event_name == "endpoint" and data_lines:
                        endpoint = "".join(data_lines).strip()
                        if endpoint:
                            self.session_endpoint = urljoin(f"{self.endpoint}/", endpoint)
                            return
                        event_name, data_lines = "", []
        raise ValueError("MCP SSE stream did not provide a session endpoint")

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.initialize()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(100):
            params = {"cursor": cursor} if cursor else None
            result = await self._request("tools/list", params)
            page = result.get("result") or {}
            page_tools = page.get("tools") or []
            if not isinstance(page_tools, list):
                raise ValueError("MCP tools/list returned an invalid tools array")
            tools.extend(_public_tool(item) for item in page_tools if isinstance(item, dict))
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self.initialize()
        result = await self._request("tools/call", {"name": tool_name, "arguments": arguments})
        return result.get("result") or {}


def _parse_rpc_response(response: httpx.Response, request_id: str) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").lower()
    if "text/event-stream" not in content_type:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("MCP response must be a JSON object")
        return _check_rpc_error(value, request_id)
    candidates: list[dict[str, Any]] = []
    for block in response.text.split("\n\n"):
        data = "\n".join(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
        if not data or data == "[DONE]":
            continue
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    for value in candidates:
        if str(value.get("id")) == request_id or "error" in value:
            return _check_rpc_error(value, request_id)
    raise ValueError("MCP SSE response did not contain the JSON-RPC request result")


def _check_rpc_error(value: dict[str, Any], request_id: str) -> dict[str, Any]:
    if value.get("id") not in {None, request_id}:
        raise ValueError("MCP response id did not match the request")
    if value.get("error"):
        error = value["error"]
        message = str(error.get("message", "MCP request failed")) if isinstance(error, dict) else "MCP request failed"
        raise ValueError(message[:300])
    return value


def _public_tool(value: dict[str, Any]) -> dict[str, Any]:
    name = str(value.get("name", "")).strip()
    if not name or len(name) > 128:
        raise ValueError("MCP tool has an invalid name")
    schema = value.get("inputSchema") or {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    if len(json.dumps(schema, ensure_ascii=False)) > _MAX_SCHEMA_CHARS:
        raise ValueError("MCP tool input schema exceeds the size limit")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError("MCP tool has an invalid JSON Schema") from exc
    return {
        "name": name,
        "description": str(value.get("description", ""))[:1000],
        "inputSchema": schema,
        "annotations": value.get("annotations") if isinstance(value.get("annotations"), dict) else {},
    }


def _tool_key(server: str, tool: str) -> str:
    return f"mcp__{server}__{tool}"


def mcp_tool_schemas() -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for server in list_mcp_servers():
        if not server["enabled"]:
            continue
        for tool in server["tools"]:
            schemas.append({"type": "function", "function": {
                "name": _tool_key(server["name"], tool["name"]),
                "description": f"MCP {server['name']} tool: {tool.get('description', tool['name'])}",
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            }})
    return schemas


async def execute_mcp_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not name.startswith("mcp__"):
        raise ValueError("Not an MCP tool")
    parts = name.split("__", 2)
    if len(parts) != 3:
        raise ValueError("Invalid MCP tool name")
    server_name, tool_name = parts[1], parts[2]
    record = _server(server_name)
    if not record.get("enabled", True):
        raise ValueError("MCP server is disabled")
    tool = next((item for item in record.get("tools", []) if isinstance(item, dict) and item.get("name") == tool_name), None)
    if tool is None:
        raise ValueError("MCP tool is not discovered")
    _validate_tool_arguments(tool.get("inputSchema") or {}, arguments)
    result = await MCPClient.from_record(server_name, record).call_tool(tool_name, arguments)
    return {"result": redact(result), "status": "failed" if result.get("isError") else "success"}


def _validate_tool_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    try:
        Draft202012Validator(schema).validate(arguments)
    except (SchemaError, ValidationError) as exc:
        raise ValueError("MCP tool arguments do not match the discovered input schema") from exc


router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
async def get_servers() -> dict[str, Any]:
    return {"items": list_mcp_servers()}


@router.put("/servers/{name}")
async def put_server(name: str, request: MCPServerRequest) -> dict[str, Any]:
    if not _SERVER_NAME.fullmatch(name):
        raise HTTPException(422, "MCP server name must contain only letters, numbers, dot, dash, or underscore")
    try:
        endpoint = _validate_endpoint(request.endpoint)
        headers = _validate_headers(request.headers)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = _read_servers().get(name, {})
    if request.clear_headers:
        encrypted_headers = ""
    elif headers:
        encrypted_headers = encrypt_secret(json.dumps(headers, ensure_ascii=False))
    else:
        encrypted_headers = existing.get("headers_encrypted", "")
    record = {
        "endpoint": endpoint,
        "transport": request.transport,
        "timeout_seconds": request.timeout_seconds,
        "enabled": request.enabled,
        "headers_encrypted": encrypted_headers,
        "tools": existing.get("tools", []),
        "last_discovered_at": existing.get("last_discovered_at"),
        "last_error": None,
    }
    _save_server(name, record)
    _audit("mcp.server.updated", name, {"endpoint": endpoint, "transport": request.transport})
    return {"server": _public_server(name, record)}


@router.delete("/servers/{name}")
async def remove_server(name: str) -> dict[str, Any]:
    servers = _read_servers()
    if name not in servers:
        raise HTTPException(404, "MCP server not found")
    del servers[name]
    _write_servers(servers)
    _audit("mcp.server.deleted", name)
    return {"name": name, "deleted": True}


@router.post("/servers/{name}/discover")
async def discover_server(name: str) -> dict[str, Any]:
    try:
        record = _server(name)
        tools = await MCPClient.from_record(name, record).list_tools()
    except KeyError as exc:
        raise HTTPException(404, "MCP server not found") from exc
    except (httpx.HTTPError, ValueError) as exc:
        record = _server(name)
        record["last_error"] = str(exc)[:300]
        _save_server(name, record)
        raise HTTPException(502, "MCP discovery failed") from exc
    record["tools"] = tools
    record["last_error"] = None
    record["last_discovered_at"] = datetime.now(timezone.utc).isoformat()
    _save_server(name, record)
    _audit("mcp.server.discovered", name, {"tools": len(tools)})
    return {"server": _public_server(name, record), "tools": tools}


@router.get("/tools")
async def get_mcp_tools() -> dict[str, Any]:
    return {"items": mcp_tool_schemas()}


@router.post("/servers/{name}/tools/{tool_name}/call")
async def call_server_tool(name: str, tool_name: str, request: MCPToolCallRequest) -> dict[str, Any]:
    try:
        record = _server(name)
        if not record.get("enabled", True):
            raise HTTPException(403, "MCP server is disabled")
        known_tools = {
            item.get("name"): item for item in record.get("tools", [])
            if isinstance(item, dict)
        }
        tool = known_tools.get(tool_name)
        if tool is None:
            raise HTTPException(404, "MCP tool is not discovered")
        policy = get_tool_settings(_tool_key(name, tool_name))
        if not policy["enabled"]:
            raise HTTPException(403, "MCP tool is disabled by policy")
        _validate_tool_arguments(tool.get("inputSchema") or {}, request.arguments)
        if policy["permission"] == "write":
            approval_id = str(uuid.uuid4())
            with database.connection() as db:
                db.execute(
                    "INSERT INTO approvals(id, tenant_id, conversation_id, tool_name, arguments) VALUES (?, ?, ?, ?, ?)",
                    (approval_id, current_tenant(), f"direct-mcp:{name}", _tool_key(name, tool_name), json.dumps(request.arguments, ensure_ascii=False)),
                )
                database.add_audit_event(db, current_tenant(), "approval.requested", "tool", _tool_key(name, tool_name), {"approval_id": approval_id}, actor=current_user())
            return {"approval_required": True, "approval_id": approval_id, "message": "Waiting for a human approval decision."}
        result = await MCPClient.from_record(name, record).call_tool(tool_name, request.arguments)
    except KeyError as exc:
        raise HTTPException(404, "MCP server not found") from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "MCP tool call failed") from exc
    _audit("mcp.tool.called", name, {"tool": tool_name})
    return {"result": redact(result), "is_error": bool(result.get("isError"))}
