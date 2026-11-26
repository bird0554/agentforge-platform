from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


POSTGRES_SCHEME_PREFIXES = ("postgresql://", "postgres://")


def _db_path() -> Path:
    value = os.getenv("DATABASE_URL", "sqlite:///./data/agent-platform.db")
    if value.startswith("sqlite:///"):
        return Path(value.removeprefix("sqlite:///"))
    raise RuntimeError("DATABASE_URL is not a SQLite URL")


def is_postgres() -> bool:
    return os.getenv("DATABASE_URL", "sqlite:///./data/agent-platform.db").lower().startswith(POSTGRES_SCHEME_PREFIXES)


class _Connection:
    """Small compatibility wrapper so the service keeps one SQL dialect in its modules."""

    def __init__(self, raw: Any, postgres: bool = False) -> None:
        self.raw = raw
        self.postgres = postgres

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.postgres else statement

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
        return self.raw.execute(self._sql(statement), parameters)

    def executescript(self, script: str) -> None:
        if not self.postgres:
            self.raw.executescript(script)
            return
        for statement in (part.strip() for part in script.split(";")):
            if statement:
                self.raw.execute(self._sql(statement))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)


@contextmanager
def connection() -> Iterator[_Connection]:
    if is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL DATABASE_URL requires the psycopg package") from exc
        raw = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
        db = _Connection(raw, postgres=True)
    else:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(path, timeout=10)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        db = _Connection(raw)
    try:
        yield db
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()


def init_db() -> None:
    with connection() as db:
        identity_type = "BIGSERIAL" if db.postgres else "INTEGER"
        autoincrement = "" if db.postgres else " AUTOINCREMENT"
        db.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS conversations_tenant_updated ON conversations(tenant_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS messages (
                id {identity_type} PRIMARY KEY{autoincrement},
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
            CREATE TABLE IF NOT EXISTS tool_runs (
                id {identity_type} PRIMARY KEY{autoincrement},
                tenant_id TEXT NOT NULL,
                conversation_id TEXT,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                response TEXT NOT NULL,
                steps TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS agent_runs_tenant_created ON agent_runs(tenant_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS approvals_tenant_status ON approvals(tenant_id, status, created_at DESC);
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id {identity_type} PRIMARY KEY{autoincrement},
                tenant_id TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'local-admin',
                event_type TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                payload TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS audit_events_tenant_created ON audit_events(tenant_id, created_at DESC);
            """
        )


def row_dict(row: Any | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def add_message(db: _Connection, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> int:
    cursor = db.execute(
        "INSERT INTO messages(conversation_id, role, content, metadata) VALUES (?, ?, ?, ?) RETURNING id",
        (conversation_id, role, content, json.dumps(metadata or {}, ensure_ascii=False)),
    )
    db.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
    row = cursor.fetchone()
    return int(row["id"] if isinstance(row, dict) else row[0])


def add_audit_event(
    db: _Connection,
    tenant_id: str,
    event_type: str,
    resource_type: str,
    resource_id: str | None = None,
    payload: dict[str, Any] | None = None,
    actor: str = "local-admin",
) -> None:
    db.execute(
        "INSERT INTO audit_events(tenant_id, actor, event_type, resource_type, resource_id, payload) VALUES (?, ?, ?, ?, ?, ?)",
        (tenant_id, actor, event_type, resource_type, resource_id, json.dumps(payload or {}, ensure_ascii=False)),
    )
