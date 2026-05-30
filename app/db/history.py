from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(settings.history_db_path)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    UNIQUE NOT NULL,
    domain      TEXT    NOT NULL,
    config_json TEXT    NOT NULL,
    report_json TEXT    NOT NULL,
    topics_json TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_domain     ON snapshots(domain);
CREATE INDEX IF NOT EXISTS idx_snapshots_created_at ON snapshots(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL,
    domain         TEXT    NOT NULL,
    item_headline  TEXT    NOT NULL,
    feedback_type  TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_domain ON feedback(domain);

CREATE TABLE IF NOT EXISTS product_profiles (
    domain       TEXT    PRIMARY KEY,
    profile_json TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
"""


@dataclass
class StoredSnapshot:
    run_id: str
    domain: str
    config: dict
    report: dict
    topics: list[dict]
    created_at: str


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    log.info("History DB initialised")


def save_feedback(run_id: str, domain: str, item_headline: str, feedback_type: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback (run_id, domain, item_headline, feedback_type, created_at) VALUES (?,?,?,?,?)",
            (run_id, domain.strip().lower(), item_headline, feedback_type, now),
        )
    log.info(f"Feedback saved | domain={domain!r} type={feedback_type} headline={item_headline!r}")


def get_incorrect_headlines(domain: str) -> list[str]:
    """Return headlines previously marked incorrect for this domain."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT item_headline FROM feedback WHERE domain = ? AND feedback_type = 'incorrect'",
            (domain.strip().lower(),),
        ).fetchall()
    return [r["item_headline"] for r in rows]


def purge_old_snapshots(retention_days: int) -> int:
    """Delete snapshots older than retention_days. Returns the number of rows deleted."""
    if retention_days <= 0:
        return 0
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM snapshots WHERE created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        deleted = cursor.rowcount
    if deleted:
        log.info(f"Purged {deleted} snapshot(s) older than {retention_days} days")
    return deleted


def save_snapshot(
    run_id: str,
    domain: str,
    config: dict,
    report: dict,
    topics: list[dict],
    created_at: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO snapshots
                (run_id, domain, config_json, report_json, topics_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                domain.strip().lower(),
                json.dumps(config),
                json.dumps(report),
                json.dumps(topics),
                created_at,
            ),
        )
    log.info(f"Snapshot saved | run_id={run_id} domain={domain!r}")


def find_previous_snapshot(
    domain: str,
    before_run_id: str,
    target_days: int = 7,
    min_gap_hours: int = 6,
) -> StoredSnapshot | None:
    """Return the snapshot whose age is closest to target_days, excluding before_run_id.

    Snapshots newer than min_gap_hours are ignored — they represent noise from
    rapid re-runs, not real trend movement.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE domain = ? AND run_id != ? ORDER BY created_at DESC",
            (domain.strip().lower(), before_run_id),
        ).fetchall()

    if not rows:
        return None

    now = datetime.now(timezone.utc)
    target_seconds = target_days * 86400
    min_gap_seconds = min_gap_hours * 3600

    best_row, best_score = None, float("inf")
    for row in rows:
        try:
            ts = datetime.fromisoformat(row["created_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age = (now - ts).total_seconds()
        if age < min_gap_seconds:
            continue  # too recent — skip
        score = abs(age - target_seconds)
        if score < best_score:
            best_score, best_row = score, row

    if best_row is None:
        return None

    return StoredSnapshot(
        run_id=best_row["run_id"],
        domain=best_row["domain"],
        config=json.loads(best_row["config_json"]),
        report=json.loads(best_row["report_json"]),
        topics=json.loads(best_row["topics_json"]),
        created_at=best_row["created_at"],
    )


def upsert_profile(domain: str, profile: dict) -> None:
    """Insert or replace a product profile for the given domain."""
    now = datetime.now(timezone.utc).isoformat()
    domain_key = domain.strip().lower()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM product_profiles WHERE domain = ?", (domain_key,)
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT OR REPLACE INTO product_profiles (domain, profile_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (domain_key, json.dumps(profile), created_at, now),
        )
    log.info(f"Profile saved | domain={domain_key!r}")


def get_profile(domain: str) -> dict | None:
    """Return the stored product profile for a domain, or None if not set."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT profile_json FROM product_profiles WHERE domain = ?",
            (domain.strip().lower(),),
        ).fetchone()
    return json.loads(row["profile_json"]) if row else None


def get_timeline(domain: str, days: int = 30) -> list[dict]:
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT run_id, created_at, topics_json
            FROM snapshots
            WHERE domain = ? AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (domain.strip().lower(), cutoff),
        ).fetchall()

    result = []
    for row in rows:
        topics_raw = json.loads(row["topics_json"])
        topics = [
            {
                "headline": t.get("headline", ""),
                "rank": t.get("rank", 0),
                "weighted_evidence_score": t.get("weighted_evidence_score", 0.0),
                "confidence": t.get("confidence", "Low"),
                "classification": t.get("classification", "STABLE BUT IMPORTANT"),
            }
            for t in topics_raw
        ]
        result.append({
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "topics": topics,
        })
    return result


def save_trend_feedback(domain: str, item_headline: str, feedback_type: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback (run_id, domain, item_headline, feedback_type, created_at) VALUES (?,?,?,?,?)",
            ("", domain.strip().lower(), item_headline, feedback_type, now),
        )
    log.info(f"Trend feedback saved | domain={domain!r} type={feedback_type}")


def get_liked_headlines(domain: str) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item_headline FROM feedback WHERE domain = ? AND feedback_type = 'relevant'",
            (domain.strip().lower(),),
        ).fetchall()
    return [r["item_headline"] for r in rows]


def list_snapshots(domain: str, limit: int = 20) -> list[StoredSnapshot]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE domain = ? ORDER BY created_at DESC LIMIT ?",
            (domain.strip().lower(), limit),
        ).fetchall()
    return [
        StoredSnapshot(
            run_id=r["run_id"],
            domain=r["domain"],
            config=json.loads(r["config_json"]),
            report=json.loads(r["report_json"]),
            topics=json.loads(r["topics_json"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]
