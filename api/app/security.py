from __future__ import annotations

import re
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
]
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"reveal\s+(the\s+)?system\s+prompt", re.I),
    re.compile(r"忽略.{0,8}(之前|以上|所有).{0,8}(指令|规则)"),
    re.compile(r"泄露.{0,8}(系统提示词|系统指令)"),
]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if re.search(r"(?i)(api[_-]?key|token|password|secret)", key) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value[:12000]
    return value


def injection_detected(text: str) -> bool:
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)
