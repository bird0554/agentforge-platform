"""Request-scoped runtime identity helpers.

The HTTP application uses these small helpers from its middleware while the
feature modules consume the richer identity API in :mod:`app.auth`. Keeping
both surfaces backed by the same context variable prevents tenant and user
scope from diverging during a request.
"""

from __future__ import annotations

import os
from contextvars import Token

from fastapi import HTTPException

from . import auth


def authentication_required() -> bool:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    return environment in {"prod", "production"} and os.getenv(
        "AUTH_ALLOW_DEV_PRINCIPAL", "false"
    ).strip().lower() != "true"


def principal() -> auth.Principal:
    return auth.current_principal()


def current_tenant() -> str:
    return auth.current_tenant()


def current_user() -> str:
    return auth.current_user()


def has_role(role: str) -> bool:
    return role in auth.current_principal().roles


def decode_bearer(token: str) -> auth.Principal | None:
    if not token:
        return None
    try:
        return auth._jwt_principal(token)
    except HTTPException:
        return None


def set_principal(value: auth.Principal) -> Token[auth.Principal]:
    return auth._principal.set(value)


def reset_principal(token: Token[auth.Principal]) -> None:
    auth._principal.reset(token)
