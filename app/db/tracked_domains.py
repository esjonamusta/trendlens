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
    domain      TEXT    NOT NULL UNIQUE,
    added_at    TEXT    NOT NULL,
    last_run_at TEXT,
    status      TEXT    NOT NULL DEFAULT 'pending'
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    log.info("Tracked domains table initialised")


def add_domain(domain: str) -> dict:
    """Add a domain to the watch list. Returns the row. No-ops if already tracked."""
    now = datetime.now(timezone.utc).isoformat()
    domain_key = domain.strip().lower()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tracked_domains (domain, added_at, status) VALUES (?, ?, 'pending')",
            (domain_key, now),
        )
        row = conn.execute(
            "SELECT * FROM tracked_domains WHERE domain = ?", (domain_key,)
        ).fetchone()
    return dict(row)


def list_domains() -> list[dict]:
    """Return all tracked domains, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tracked_domains ORDER BY added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_domains() -> list[str]:
    """Return domain strings for the scheduler to iterate over."""
    with _connect() as conn:
        rows = conn.execute("SELECT domain FROM tracked_domains").fetchall()
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
