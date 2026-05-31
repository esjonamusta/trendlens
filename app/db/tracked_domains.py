"""SQLite CRUD for tracked domains (auto-scheduled research targets)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

_DB_PATH = Path(settings.history_db_path)  # same file as history.db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_domains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT    NOT NULL,
    user_id     INTEGER,
    added_at    TEXT    NOT NULL,
    last_run_at TEXT,
    status      TEXT    NOT NULL DEFAULT 'pending',
    UNIQUE(domain, user_id)
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(tracked_domains)").fetchall()}
        if not existing:
            conn.executescript(_SCHEMA)
        elif "user_id" not in existing:
            # Migrate: recreate table to add user_id column and fix unique constraint
            conn.executescript("""
                ALTER TABLE tracked_domains RENAME TO _td_old;
                CREATE TABLE tracked_domains (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain      TEXT    NOT NULL,
                    user_id     INTEGER,
                    added_at    TEXT    NOT NULL,
                    last_run_at TEXT,
                    status      TEXT    NOT NULL DEFAULT 'pending',
                    UNIQUE(domain, user_id)
                );
                INSERT INTO tracked_domains (id, domain, added_at, last_run_at, status)
                    SELECT id, domain, added_at, last_run_at, status FROM _td_old;
                DROP TABLE _td_old;
            """)
    log.info("Tracked domains table initialised")


def add_domain(domain: str, user_id: int | None = None) -> dict:
    """Add a domain to the watch list for a user. Returns the row."""
    now = datetime.now(timezone.utc).isoformat()
    domain_key = domain.strip().lower()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tracked_domains (domain, user_id, added_at, status) VALUES (?, ?, ?, 'pending')",
            (domain_key, user_id, now),
        )
        row = conn.execute(
            "SELECT * FROM tracked_domains WHERE domain = ? AND user_id IS ?",
            (domain_key, user_id),
        ).fetchone()
    return dict(row)


def list_domains(user_id: int | None = None) -> list[dict]:
    """Return tracked domains newest first. If user_id given, return only that user's."""
    with _connect() as conn:
        if user_id is not None:
            rows = conn.execute(
                "SELECT * FROM tracked_domains WHERE user_id = ? ORDER BY added_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tracked_domains ORDER BY added_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_all_domains() -> list[str]:
    """Return distinct domain strings for the scheduler to iterate over."""
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT domain FROM tracked_domains").fetchall()
    return [r["domain"] for r in rows]


def set_status(domain: str, status: str, last_run_at: str | None = None) -> None:
    domain_key = domain.strip().lower()
    if last_run_at:
        with _connect() as conn:
            conn.execute(
                "UPDATE tracked_domains SET status = ?, last_run_at = ? WHERE domain = ?",
                (status, last_run_at, domain_key),
            )
    else:
        with _connect() as conn:
            conn.execute(
                "UPDATE tracked_domains SET status = ? WHERE domain = ?",
                (status, domain_key),
            )
