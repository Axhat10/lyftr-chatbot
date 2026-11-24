import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config

DB_PATH = config.DATABASE_URL.replace("sqlite:///", "", 1)


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                system_prompt TEXT,
                created_at TEXT NOT NULL
            )"""
        )


def db_ok() -> bool:
    try:
        with _conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


def get_session_system_prompt(session_id: str):
    with _conn() as c:
        row = c.execute(
            "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return row["system_prompt"] if row else None


def get_history(session_id: str) -> list[dict]:
    """Messages in the shape the LLM expects (no metadata)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def session_exists(session_id: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (session_id,)
        ).fetchone()
    return row is not None


def get_messages(session_id: str) -> list[dict]:
    """Messages for the history endpoint, with metadata on assistant replies."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        item = {"role": r["role"], "content": r["content"]}
        if r["metadata"]:
            item["metadata"] = json.loads(r["metadata"])
        out.append(item)
    return out


def save_exchange(session_id, user_text, reply, metadata, system_prompt=None) -> None:
    """Save the user message and the assistant reply together, only after success."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """INSERT INTO sessions (session_id, system_prompt, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt)""",
            (session_id, system_prompt, now),
        )
        c.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) "
            "VALUES (?, 'user', ?, NULL, ?)",
            (session_id, user_text, now),
        )
        c.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) "
            "VALUES (?, 'assistant', ?, ?, ?)",
            (session_id, reply, json.dumps(metadata), now),
        )