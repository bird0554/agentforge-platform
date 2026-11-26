from __future__ import annotations

import ast
import asyncio
import json
import operator
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from . import database
from .settings import get_tool_settings


class ToolError(ValueError):
    pass


def calculate(expression: str) -> str:
    tree = ast.parse(expression, mode="eval")
    operators: dict[type[ast.operator], Callable[[float, float], float]] = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    }

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if abs(node.value) > 1_000_000_000:
                raise ToolError("Numeric input is out of range")
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ToolError("Exponent is out of range")
            result = operators[type(node.op)](left, right)
            if abs(result) > 1_000_000_000:
                raise ToolError("Result is out of range")
            return result
        raise ToolError("Only basic arithmetic expressions are supported")

    return str(evaluate(tree.body))


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    permission: str
    handler: Callable[..., Any]

    def public_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def _knowledge_search(query: str) -> str:
    corpus = {
        "agent loop": "An agent loop alternates model decisions and tool execution until a final response or a step limit.",
        "mcp": "MCP standardizes discovery and invocation of tools and resources across model clients and servers.",
        "memory": "Conversation memory keeps a bounded recent window and can store summaries for longer-lived context.",
        "approval": "High-impact actions should pause for a human decision before the side effect is executed.",
    }
    hits = [value for key, value in corpus.items() if key in query.lower()]
    return "\n".join(hits) if hits else "No matching local knowledge snippets were found."


def _ticket_create(title: str, description: str, priority: str = "normal") -> dict[str, str]:
    return {"ticket_id": f"DEMO-{uuid.uuid4().hex[:6].upper()}", "title": title, "priority": priority, "status": "created"}


TOOLS = {
    "calculator": Tool("calculator", "Evaluate a basic arithmetic expression.", {
        "type": "object", "properties": {"expression": {"type": "string", "maxLength": 120}},
        "required": ["expression"], "additionalProperties": False,
    }, "read", calculate),
    "knowledge_search": Tool("knowledge_search", "Search the local Agent platform knowledge snippets.", {
        "type": "object", "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 300}},
        "required": ["query"], "additionalProperties": False,
    }, "read", _knowledge_search),
    "ticket_create": Tool("ticket_create", "Create a demo service ticket. Requires human approval.", {
        "type": "object", "properties": {
            "title": {"type": "string", "minLength": 3, "maxLength": 120},
            "description": {"type": "string", "minLength": 3, "maxLength": 1000},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
        }, "required": ["title", "description"], "additionalProperties": False,
    }, "write", _ticket_create),
    "code_sandbox": Tool("code_sandbox", "Run a short Python program in the isolated Docker sandbox.", {
        "type": "object", "properties": {"code": {"type": "string", "minLength": 1, "maxLength": 20000}},
        "required": ["code"], "additionalProperties": False,
    }, "read", lambda code: code),
}


def list_tools() -> list[dict[str, Any]]:
    items = []
    for tool in TOOLS.values():
        settings = get_tool_settings(tool.name)
        items.append({
            "name": tool.name,
            "description": tool.description,
            "permission": settings["permission"] or tool.permission,
            "default_permission": tool.permission,
            "enabled": settings["enabled"],
            "timeout_seconds": settings["timeout_seconds"],
            "parameters": tool.parameters,
            "schema": tool.public_schema(),
        })
    try:
        from .mcp import mcp_tool_schemas
        items.extend({
            "name": schema["function"]["name"], "description": schema["function"]["description"],
            "permission": get_tool_settings(schema["function"]["name"])["permission"] or "read",
            "default_permission": "read", "enabled": get_tool_settings(schema["function"]["name"])["enabled"],
            "timeout_seconds": get_tool_settings(schema["function"]["name"])["timeout_seconds"], "parameters": schema["function"]["parameters"], "schema": schema,
        } for schema in mcp_tool_schemas())
    except (ImportError, ValueError):
        pass
    try:
        from .a2a_runtime import a2a_tool_schemas
        items.extend({
            "name": schema["function"]["name"], "description": schema["function"]["description"],
            "permission": get_tool_settings(schema["function"]["name"])["permission"] or "read",
            "default_permission": "read", "enabled": get_tool_settings(schema["function"]["name"])["enabled"],
            "timeout_seconds": get_tool_settings(schema["function"]["name"])["timeout_seconds"], "parameters": schema["function"]["parameters"], "schema": schema,
        } for schema in a2a_tool_schemas())
    except (ImportError, ValueError):
        pass
    return items


def enabled_tool_schemas() -> list[dict[str, Any]]:
    schemas = [tool.public_schema() for tool in TOOLS.values() if get_tool_settings(tool.name)["enabled"]]
    try:
        from .mcp import mcp_tool_schemas
        schemas.extend(schema for schema in mcp_tool_schemas() if get_tool_settings(schema["function"]["name"])["enabled"])
    except (ImportError, ValueError):
        pass
    try:
        from .a2a_runtime import a2a_tool_schemas
        schemas.extend(schema for schema in a2a_tool_schemas() if get_tool_settings(schema["function"]["name"])["enabled"])
    except (ImportError, ValueError):
        pass
    return schemas


def _validate_arguments(tool: Tool, arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ToolError("Tool arguments must be a JSON object")
    properties = tool.parameters["properties"]
    if tool.parameters.get("additionalProperties") is False and set(arguments) - set(properties):
        raise ToolError("Unknown tool argument")
    for name in tool.parameters.get("required", []):
        if name not in arguments:
            raise ToolError(f"Missing required argument: {name}")
    for name, value in arguments.items():
        definition = properties.get(name)
        if not definition:
            raise ToolError(f"Invalid argument: {name}")
        expected_type = definition.get("type")
        valid_type = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
        }.get(expected_type, False)
        if not valid_type:
            raise ToolError(f"Invalid argument: {name}")
        if isinstance(value, str) and (len(value) > definition.get("maxLength", 10000) or len(value) < definition.get("minLength", 0)):
            raise ToolError(f"Argument length is invalid: {name}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in definition and value < definition["minimum"]:
                raise ToolError(f"Argument is below minimum: {name}")
            if "maximum" in definition and value > definition["maximum"]:
                raise ToolError(f"Argument is above maximum: {name}")
        if "enum" in definition and value not in definition["enum"]:
            raise ToolError(f"Unsupported value for: {name}")


async def execute_tool(name: str, arguments: dict[str, Any], tenant_id: str, conversation_id: str, *, bypass_approval: bool = False) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None and (name.startswith("mcp__") or name.startswith("a2a__")):
        settings = get_tool_settings(name)
        if not settings["enabled"]:
            return {"error": "Tool is disabled by policy", "status": "failed"}
        if settings["permission"] == "write" and not bypass_approval:
            approval_id = str(uuid.uuid4())
            with database.connection() as db:
                db.execute("INSERT INTO approvals(id, tenant_id, conversation_id, tool_name, arguments) VALUES (?, ?, ?, ?, ?)",
                           (approval_id, tenant_id, conversation_id, name, json.dumps(arguments, ensure_ascii=False)))
                database.add_audit_event(db, tenant_id, "approval.requested", "tool", name, {"approval_id": approval_id})
            return {"approval_required": True, "approval_id": approval_id, "message": "Waiting for a human approval decision."}
    if tool is None and name.startswith("mcp__"):
        from .mcp import execute_mcp_tool
        settings = get_tool_settings(name)
        if not settings["enabled"]:
            return {"error": "Tool is disabled by policy", "status": "failed"}
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(execute_mcp_tool(name, arguments), timeout=float(settings["timeout_seconds"]))
            status, error = "success", None
            return {"result": result, "status": status}
        except Exception as exc:
            status, error = "failed", str(exc)[:300]
            return {"error": error, "status": status}
        finally:
            with database.connection() as db:
                db.execute("INSERT INTO tool_runs(tenant_id, conversation_id, tool_name, status, duration_ms, error) VALUES (?, ?, ?, ?, ?, ?)",
                           (tenant_id, conversation_id, name, status, int((time.monotonic() - started) * 1000), error))
                database.add_audit_event(db, tenant_id, f"tool.{status}", "mcp_tool", name, {"conversation_id": conversation_id})
    if tool is None and name.startswith("a2a__"):
        from .a2a_runtime import execute_a2a_tool
        settings = get_tool_settings(name)
        if not settings["enabled"]:
            return {"error": "Tool is disabled by policy", "status": "failed"}
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(execute_a2a_tool(name, arguments), timeout=float(settings["timeout_seconds"]))
            status, error = "success", None
            return result
        except Exception as exc:
            status, error = "failed", str(exc)[:300]
            return {"error": error, "status": status}
        finally:
            with database.connection() as db:
                db.execute("INSERT INTO tool_runs(tenant_id, conversation_id, tool_name, status, duration_ms, error) VALUES (?, ?, ?, ?, ?, ?)",
                           (tenant_id, conversation_id, name, status, int((time.monotonic() - started) * 1000), error))
                database.add_audit_event(db, tenant_id, f"tool.{status}", "a2a_tool", name, {"conversation_id": conversation_id})
    if not tool:
        raise ToolError("Tool is not registered")
    settings = get_tool_settings(name)
    if not settings["enabled"]:
        raise ToolError("Tool is disabled by policy")
    _validate_arguments(tool, arguments)
    if name == "code_sandbox":
        from .sandbox import run_code
        started = time.monotonic()
        try:
            result = await run_code(arguments["code"])
            status, error = "success", None
            return {"result": result, "status": status}
        except Exception as exc:
            status, error = "failed", str(exc)[:300]
            return {"error": error, "status": status}
        finally:
            with database.connection() as db:
                db.execute("INSERT INTO tool_runs(tenant_id, conversation_id, tool_name, status, duration_ms, error) VALUES (?, ?, ?, ?, ?, ?)",
                           (tenant_id, conversation_id, name, status, int((time.monotonic() - started) * 1000), error))
                database.add_audit_event(db, tenant_id, f"tool.{status}", "sandbox", name, {"conversation_id": conversation_id})
    permission = settings["permission"] or tool.permission
    if permission == "write":
        approval_id = str(uuid.uuid4())
        with database.connection() as db:
            db.execute("INSERT INTO approvals(id, tenant_id, conversation_id, tool_name, arguments) VALUES (?, ?, ?, ?, ?)",
                       (approval_id, tenant_id, conversation_id, name, json.dumps(arguments, ensure_ascii=False)))
            database.add_audit_event(db, tenant_id, "approval.requested", "tool", name, {"approval_id": approval_id})
        return {"approval_required": True, "approval_id": approval_id, "message": "Waiting for a human approval decision."}
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(asyncio.to_thread(tool.handler, **arguments), timeout=float(settings["timeout_seconds"]))
        status, error = "success", None
        return {"result": result, "status": status}
    except (TimeoutError, ToolError, ZeroDivisionError, TypeError) as exc:
        status, error = "failed", str(exc)[:300]
        return {"error": error, "status": status}
    finally:
        duration = int((time.monotonic() - started) * 1000)
        with database.connection() as db:
            db.execute("INSERT INTO tool_runs(tenant_id, conversation_id, tool_name, status, duration_ms, error) VALUES (?, ?, ?, ?, ?, ?)",
                       (tenant_id, conversation_id, name, status, duration, error))
            database.add_audit_event(db, tenant_id, f"tool.{status}", "tool", name, {"conversation_id": conversation_id})


async def decide_approval(approval_id: str, tenant_id: str, decision: str) -> dict[str, Any] | None:
    with database.connection() as db:
        pending = db.execute("SELECT * FROM approvals WHERE id = ? AND tenant_id = ? AND status = 'pending'", (approval_id, tenant_id)).fetchone()
    if not pending:
        return None
    if pending["tool_name"].startswith(("mcp__", "a2a__")):
        tool_name = pending["tool_name"]
        settings = get_tool_settings(tool_name)
        if decision == "approve" and (settings["permission"] != "write" or not settings["enabled"]):
            return None
        if decision == "approve":
            with database.connection() as db:
                claimed = db.execute(
                    "UPDATE approvals SET status = 'processing' WHERE id = ? AND tenant_id = ? AND status = 'pending'",
                    (approval_id, tenant_id),
                )
            if not claimed.rowcount:
                return None
            arguments = json.loads(pending["arguments"])
            result = await execute_tool(tool_name, arguments, tenant_id, pending["conversation_id"], bypass_approval=True)
            status = "approved" if result.get("status") == "success" else "failed"
        else:
            result = {"message": "Human reviewer rejected this action."}
            status = "rejected"
        result_json = json.dumps(result, ensure_ascii=False)
        with database.connection() as db:
            expected_status = "processing" if decision == "approve" else "pending"
            cursor = db.execute("UPDATE approvals SET status = ?, result = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ? AND tenant_id = ? AND status = ?",
                                (status, result_json, approval_id, tenant_id, expected_status))
            if not cursor.rowcount:
                return None
            database.add_audit_event(db, tenant_id, f"approval.{status}", "approval", approval_id, {"tool_name": tool_name})
        return {"id": approval_id, "status": status, "result": result}
    with database.connection() as db:
        row = db.execute("SELECT * FROM approvals WHERE id = ? AND tenant_id = ? AND status = 'pending'", (approval_id, tenant_id)).fetchone()
        if not row:
            return None
        if decision == "approve":
            tool = TOOLS.get(row["tool_name"])
            settings = get_tool_settings(row["tool_name"])
            if not tool or (settings["permission"] or tool.permission) != "write" or not settings["enabled"]:
                return None
            arguments = json.loads(row["arguments"])
            try:
                result = tool.handler(**arguments)
                status = "approved"
                result_json = json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                status = "failed"
                result_json = json.dumps({"error": str(exc)[:300]})
        else:
            status, result_json = "rejected", json.dumps({"message": "Human reviewer rejected this action."})
        db.execute("UPDATE approvals SET status = ?, result = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (status, result_json, approval_id))
        db.execute("INSERT INTO tool_runs(tenant_id, conversation_id, tool_name, status, error) VALUES (?, ?, ?, ?, ?)",
                   (tenant_id, row["conversation_id"], row["tool_name"], status, None if status != "failed" else "Tool execution failed"))
        database.add_audit_event(db, tenant_id, f"approval.{status}", "approval", approval_id, {"tool_name": row["tool_name"]})
    return {"id": approval_id, "status": status, "result": json.loads(result_json)}
