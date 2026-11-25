from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def _db_path() -> Path:
    value = os.getenv("DATABASE_URL", "sqlite:///./data/agent-platform.db")
    if value.startswith("sqlite:///"):
        return Path(value.removeprefix("sqlite:///"))
    raise RuntimeError("This MVP supports SQLite DATABASE_URL values only")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
            CREATE TABLE IF NOT EXISTS tool_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            """
        )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def add_message(db: sqlite3.Connection, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> int:
    cursor = db.execute(
        "INSERT INTO messages(conversation_id, role, content, metadata) VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, json.dumps(metadata or {}, ensure_ascii=False)),
    )
    db.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
    return int(cursor.lastrowid)
