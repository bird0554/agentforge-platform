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
}


def list_tools() -> list[dict[str, Any]]:
    return [{"name": tool.name, "description": tool.description, "permission": tool.permission,
             "parameters": tool.parameters, "schema": tool.public_schema()} for tool in TOOLS.values()]


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
        if not definition or not isinstance(value, str):
            raise ToolError(f"Invalid argument: {name}")
        if len(value) > definition.get("maxLength", 10000) or len(value) < definition.get("minLength", 0):
            raise ToolError(f"Argument length is invalid: {name}")
        if "enum" in definition and value not in definition["enum"]:
            raise ToolError(f"Unsupported value for: {name}")


async def execute_tool(name: str, arguments: dict[str, Any], tenant_id: str, conversation_id: str) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if not tool:
        raise ToolError("Tool is not registered")
    _validate_arguments(tool, arguments)
    if tool.permission == "write":
        approval_id = str(uuid.uuid4())
        with database.connection() as db:
            db.execute("INSERT INTO approvals(id, tenant_id, conversation_id, tool_name, arguments) VALUES (?, ?, ?, ?, ?)",
                       (approval_id, tenant_id, conversation_id, name, json.dumps(arguments, ensure_ascii=False)))
        return {"approval_required": True, "approval_id": approval_id, "message": "Waiting for a human approval decision."}
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(asyncio.to_thread(tool.handler, **arguments), timeout=3)
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


def decide_approval(approval_id: str, tenant_id: str, decision: str) -> dict[str, Any] | None:
    with database.connection() as db:
        row = db.execute("SELECT * FROM approvals WHERE id = ? AND tenant_id = ? AND status = 'pending'", (approval_id, tenant_id)).fetchone()
        if not row:
            return None
        if decision == "approve":
            tool = TOOLS.get(row["tool_name"])
            if not tool or tool.permission != "write":
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
    return {"id": approval_id, "status": status, "result": json.loads(result_json)}
