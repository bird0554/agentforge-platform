from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterator

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    roles: frozenset[str]


_principal: ContextVar[Principal] = ContextVar(
    "agentforge_principal",
    default=Principal("demo-tenant", "local-admin", frozenset({"admin"})),
)


def current_principal() -> Principal:
    return _principal.get()


def current_tenant() -> str:
    return current_principal().tenant_id


def current_user() -> str:
    return current_principal().user_id


@contextmanager
def use_principal(value: Principal) -> Iterator[None]:
    token = _principal.set(value)
    try:
        yield
    finally:
        _principal.reset(token)


def _decode_segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _jwt_principal(token: str) -> Principal:
    try:
        header, payload, signature = token.split(".", 2)
        header_obj = json.loads(_decode_segment(header))
        claims = json.loads(_decode_segment(payload))
        if header_obj.get("alg") != "HS256" or header_obj.get("typ", "JWT") != "JWT":
            raise ValueError("unsupported algorithm")
        secret = (os.getenv("AUTH_JWT_SECRET") or os.getenv("APP_SECRET", "")).encode()
        if len(secret) < 32:
            raise ValueError("authentication secret is too short")
        expected = hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode_segment(signature)):
            raise ValueError("invalid signature")
        expiry = claims.get("exp")
        if expiry is not None and datetime.now(UTC).timestamp() >= float(expiry):
            raise ValueError("expired token")
        tenant_id = str(claims.get("tenant_id") or claims.get("tid") or "").strip()
        user_id = str(claims.get("sub") or "").strip()
        if not tenant_id or not user_id:
            raise ValueError("tenant_id and sub are required")
        raw_roles = claims.get("roles", [])
        roles = frozenset(raw_roles if isinstance(raw_roles, list) else [str(raw_roles)])
        return Principal(tenant_id[:200], user_id[:200], roles)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(401, "Invalid bearer token") from exc


def principal_from_request(request: Request) -> Principal:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return _jwt_principal(authorization[7:].strip())
    environment = os.getenv("APP_ENV", "development").lower()
    if environment in {"production", "prod"} and os.getenv("AUTH_ALLOW_DEV_PRINCIPAL", "false").lower() != "true":
        raise HTTPException(401, "Bearer authentication is required")
    tenant = request.headers.get("x-tenant-id", os.getenv("DEFAULT_TENANT_ID", "demo-tenant")).strip()
    user = request.headers.get("x-user-id", os.getenv("DEFAULT_USER_ID", "local-admin")).strip()
    return Principal(tenant[:200] or "demo-tenant", user[:200] or "local-admin", frozenset({"admin"}))


async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in {"/api/health", "/api/ready"} or not request.url.path.startswith("/api/"):
        return await call_next(request)
    value = principal_from_request(request)
    request.state.principal = value
    with use_principal(value):
        return await call_next(request)


def require_admin() -> Principal:
    value = current_principal()
    if "admin" not in value.roles:
        raise HTTPException(403, "Administrator role is required")
    return value
