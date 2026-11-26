from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import database


DEFAULT_SANDBOX_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "runtime": "docker",
    "image": "python:3.12-alpine",
    "timeout_seconds": 10,
    "memory_mb": 256,
    "cpu_limit": 0.5,
    "pids_limit": 64,
    "max_output_chars": 12000,
}


class SandboxSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    runtime: str | None = Field(default=None, pattern="^docker$")
    image: str | None = Field(default=None, min_length=1, max_length=200)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    memory_mb: int | None = Field(default=None, ge=64, le=2048)
    cpu_limit: float | None = Field(default=None, gt=0, le=4)
    pids_limit: int | None = Field(default=None, ge=16, le=512)
    max_output_chars: int | None = Field(default=None, ge=1000, le=100000)


class SandboxRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=20000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)


def get_settings() -> dict[str, Any]:
    with database.connection() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key = ?", ("sandbox",)).fetchone()
    if not row:
        return dict(DEFAULT_SANDBOX_SETTINGS)
    try:
        value = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return dict(DEFAULT_SANDBOX_SETTINGS)
    return {**DEFAULT_SANDBOX_SETTINGS, **value} if isinstance(value, dict) else dict(DEFAULT_SANDBOX_SETTINGS)


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = get_settings()
    current.update(updates)
    with database.connection() as db:
        db.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            ("sandbox", json.dumps(current, ensure_ascii=False)),
        )
    return current


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _run_container(code: str, config: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    if not _docker_available():
        raise RuntimeError("Docker runtime is unavailable")
    run_id = str(uuid.uuid4())
    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", str(config["pids_limit"]),
        "--memory", f"{config['memory_mb']}m", "--cpus", str(config["cpu_limit"]),
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
        "-i", config["image"], "python", "-I", "-c", code,
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            input="",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env={"PATH": os.getenv("PATH", "")},
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "id": run_id, "status": "timeout", "stdout": (exc.stdout or "")[: config["max_output_chars"]],
            "stderr": "Sandbox execution timed out", "duration_ms": int((time.monotonic() - started) * 1000),
        }
    output_limit = int(config["max_output_chars"])
    stdout, stderr = completed.stdout[:output_limit], completed.stderr[:output_limit]
    return {
        "id": run_id,
        "status": "completed" if completed.returncode == 0 else "failed",
        "return_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": len(completed.stdout) > output_limit or len(completed.stderr) > output_limit,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


async def run_code(code: str, timeout_seconds: int | None = None) -> dict[str, Any]:
    config = get_settings()
    if not config["enabled"]:
        raise PermissionError("Code sandbox is disabled by policy")
    timeout = timeout_seconds or int(config["timeout_seconds"])
    timeout = min(timeout, int(config["timeout_seconds"]))
    try:
        return await asyncio.to_thread(_run_container, code, config, timeout)
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc


router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


@router.get("/settings")
async def sandbox_settings() -> dict[str, Any]:
    return {"sandbox": get_settings(), "runtime_available": _docker_available()}


@router.put("/settings")
async def update_sandbox_settings(request: SandboxSettingsRequest) -> dict[str, Any]:
    return {"sandbox": save_settings(request.model_dump(exclude_none=True))}


@router.post("/run")
async def sandbox_run(request: SandboxRunRequest) -> dict[str, Any]:
    try:
        return await run_code(request.code, request.timeout_seconds)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
