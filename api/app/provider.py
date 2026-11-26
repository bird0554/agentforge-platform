from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .settings import runtime_model_settings


@dataclass
class ModelTurn:
    content: str
    tool_calls: list[dict[str, Any]]


class OpenAICompatibleProvider:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        saved = config if config is not None else runtime_model_settings()
        self.provider = saved.get("provider", "demo")
        self.base_url = (saved.get("base_url") or "").rstrip("/")
        self.api_key = saved.get("api_key", "")
        self.model = saved.get("model", "gpt-4o-mini")
        self.timeout = float(saved.get("timeout_seconds", 25))
        self.temperature = float(saved.get("temperature", 0.2))
        self.max_tokens = int(saved.get("max_tokens", 1200))

    @property
    def configured(self) -> bool:
        return self.provider != "demo" and bool(self.base_url and self.api_key)

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        if not self.configured:
            return self._demo_turn(messages)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]["message"]
        calls = []
        for call in choice.get("tool_calls") or []:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = None
            calls.append({"id": call.get("id", ""), "name": function.get("name", ""), "arguments": arguments})
        return ModelTurn(content=choice.get("content") or "", tool_calls=calls)

    async def test_connection(self) -> None:
        if not self.configured:
            raise ValueError("An OpenAI-compatible endpoint and API key are required")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "temperature": self.temperature,
                    "max_tokens": min(self.max_tokens, 32),
                },
            )
            response.raise_for_status()
            payload = response.json()
        if not payload.get("choices"):
            raise ValueError("The model endpoint returned no choices")

    @staticmethod
    def _demo_turn(messages: list[dict[str, Any]]) -> ModelTurn:
        if messages and messages[-1]["role"] == "tool":
            try:
                tool_result = json.loads(messages[-1]["content"])
            except (json.JSONDecodeError, TypeError):
                tool_result = {}
            if "result" in tool_result:
                return ModelTurn(f"Tool result: {tool_result['result']}", [])
        latest = next((message["content"] for message in reversed(messages) if message["role"] == "user"), "")
        lower = latest.lower()
        if "ticket" in lower or "工单" in latest:
            title = latest[:100].strip() or "Demo ticket"
            args = {"title": title[:120], "description": f"Created from the request: {latest[:500]}", "priority": "normal"}
            return ModelTurn("", [{"id": "demo-ticket-create", "name": "ticket_create", "arguments": args}])
        if any(word in lower or word in latest for word in ["calculate", "计算", "多少", "+", "*"]):
            import re
            match = re.search(r"\d+(?:\.\d+)?(?:\s*[+*/%-]\s*\d+(?:\.\d+)?)+", latest)
            if match:
                return ModelTurn("", [{"id": "demo-calculate", "name": "calculator", "arguments": {"expression": match.group(0)}}])
        if any(word in lower or word in latest for word in ["mcp", "memory", "记忆", "agent loop", "智能体循环"]):
            return ModelTurn("", [{"id": "demo-search", "name": "knowledge_search", "arguments": {"query": latest[:300]}}])
        return ModelTurn("Demo mode is active. Connect an OpenAI-compatible model in the environment settings for full natural-language reasoning. I can answer calculations, search the local knowledge base, and request approval before creating a demo ticket.", [])
