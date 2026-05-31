from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    user_id        INTEGER,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_domain ON feedback(domain);

CREATE TABLE IF NOT EXISTS product_profiles (
    domain       TEXT    PRIMARY KEY,
    profile_json TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    product_type   TEXT DEFAULT '',
    target_users   TEXT DEFAULT '',
    business_model TEXT DEFAULT '',
    product_goal   TEXT DEFAULT '',
    keywords       TEXT DEFAULT '',
    digest_frequency TEXT DEFAULT 'weekly',
    digest_last_sent_at TEXT,
    created_at     TEXT NOT NULL
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
        # Migrate before running schema so indexes on new columns work
        cols = {row[1] for row in conn.execute("PRAGMA table_info(feedback)")}
        if cols and "user_id" not in cols:
            conn.execute("ALTER TABLE feedback ADD COLUMN user_id INTEGER")
        user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if user_cols and "digest_frequency" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN digest_frequency TEXT DEFAULT 'weekly'")
        if user_cols and "digest_last_sent_at" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN digest_last_sent_at TEXT")
        conn.executescript(_SCHEMA)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id)")
    log.info("History DB initialised")


def save_feedback(run_id: str, domain: str, item_headline: str, feedback_type: str, user_id: int | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback (run_id, domain, item_headline, feedback_type, user_id, created_at) VALUES (?,?,?,?,?,?)",
            (run_id, domain.strip().lower(), item_headline, feedback_type, user_id, now),
        )
    log.info(f"Feedback saved | domain={domain!r} type={feedback_type} headline={item_headline!r} user_id={user_id}")


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


def get_timeline(
    domain: str,
    days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Return snapshots for a domain, newest first.

    Each entry contains run_id, created_at, and a list of topics with
    headline, rank, weighted_evidence_score, confidence, classification,
    and source details (what_happened, why_it_matters, pm_action,
    podcast_evidence, reddit_evidence, source_links) pulled from report_json.
    """
    if start_date and end_date:
        start_bound = f"{start_date}T00:00:00+00:00"
        end_bound = f"{end_date}T23:59:59+00:00"
    else:
        start_bound = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        end_bound = None

    with _connect() as conn:
        if end_bound:
            rows = conn.execute(
                """
                SELECT run_id, created_at, topics_json, report_json
                FROM snapshots
                WHERE domain = ? AND created_at >= ? AND created_at <= ?
                ORDER BY created_at DESC
                """,
                (domain.strip().lower(), start_bound, end_bound),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT run_id, created_at, topics_json, report_json
                FROM snapshots
                WHERE domain = ? AND created_at >= ?
                ORDER BY created_at DESC
                """,
                (domain.strip().lower(), start_bound),
            ).fetchall()

    result = []
    for row in rows:
        topics_raw = json.loads(row["topics_json"])

        # Build a lookup from headline → full item details from report_json
        report_raw = json.loads(row["report_json"]) if row["report_json"] else {}
        report_items = {
            item["headline"]: item
            for item in report_raw.get("items", [])
            if "headline" in item
        }

        topics = []
        for t in topics_raw:
            headline = t.get("headline", "")
            item = report_items.get(headline, {})
            topics.append({
                "headline": headline,
                "rank": t.get("rank", 0),
                "weighted_evidence_score": t.get("weighted_evidence_score", 0.0),
                "confidence": t.get("confidence", "Low"),
                "classification": t.get("classification", "STABLE BUT IMPORTANT"),
                # Rich source details from report_json
                "what_happened": item.get("what_happened", ""),
                "why_it_matters": item.get("why_it_matters", ""),
                "pm_action": item.get("pm_action", t.get("pm_action", "")),
                "podcast_evidence": item.get("podcast_evidence", []),
                "reddit_evidence": item.get("reddit_evidence", []),
                "source_links": item.get("source_links", []),
            })

        result.append({
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "topics": topics,
        })
    return result


def save_trend_feedback(domain: str, item_headline: str, feedback_type: str, user_id: int | None = None) -> None:
    """Save relevant/not_relevant feedback for a trend item.

    run_id is stored as an empty string because trend feedback is not tied
    to a specific research run.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback (run_id, domain, item_headline, feedback_type, user_id, created_at) VALUES (?,?,?,?,?,?)",
            ("", domain.strip().lower(), item_headline, feedback_type, user_id, now),
        )
    log.info(f"Trend feedback saved | domain={domain!r} type={feedback_type} user_id={user_id}")


def get_user_feedback(user_id: int) -> list[dict]:
    """Return all feedback given by a specific user, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT domain, item_headline, feedback_type, created_at
            FROM feedback
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_liked_headlines(domain: str) -> list[str]:
    """Return headlines the user marked as relevant for a domain."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item_headline FROM feedback WHERE domain = ? AND feedback_type = 'relevant'",
            (domain.strip().lower(),),
        ).fetchall()
    return [r["item_headline"] for r in rows]


def create_user(data: dict) -> None:
    """Insert a new user. Raises ValueError if email already exists."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO users
                    (first_name, last_name, email, password_hash,
                     product_type, target_users, business_model,
                     product_goal, keywords, digest_frequency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["first_name"],
                    data["last_name"],
                    data["email"],
                    data["password_hash"],
                    data.get("product_type", ""),
                    data.get("target_users", ""),
                    data.get("business_model", ""),
                    data.get("product_goal", ""),
                    data.get("keywords", ""),
                    data.get("digest_frequency", "weekly"),
                    now,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"Email already registered: {data['email']}") from exc
    log.info(f"User created | email={data['email']!r}")


def get_user_by_id(user_id: int) -> dict | None:
    """Return user row as dict or None if not found."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_user(user_id: int, data: dict) -> None:
    """Update editable user fields."""
    fields = ["first_name", "last_name", "product_type", "target_users",
              "business_model", "product_goal", "keywords", "digest_frequency"]
    updates = {k: v for k, v in data.items() if k in fields}
    if not updates:
        return
    cols = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id = ?", (*updates.values(), user_id))


def get_user_by_email(email: str) -> dict | None:
    """Return user row as dict or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None


def verify_user(email: str, password_hash: str) -> dict | None:
    """Return user row if email + password_hash match, else None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND password_hash = ?",
            (email.strip().lower(), password_hash),
        ).fetchone()
    return dict(row) if row else None


def seed_demo_user() -> None:
    """Ensure the demo account exists. Safe to call on every startup."""
    import hashlib as _hl
    demo = {
        "first_name": "Demo",
        "last_name": "User",
        "email": "demo@trendlens.com",
        "password_hash": _hl.sha256(b"demo1234").hexdigest(),
        "product_type": "SaaS / Software",
        "target_users": "Product managers",
        "business_model": "B2B",
        "product_goal": "Surface market trends for PMs",
        "keywords": '["AI trends", "fintech", "developer tools"]',
        "digest_frequency": "weekly",
    }
    try:
        create_user(demo)
        log.info("Demo user seeded | email=demo@trendlens.com")
    except ValueError:
        pass  # already exists — fine


def list_digest_users(frequency: str | None = None) -> list[dict]:
    """Return users with email digests enabled, optionally filtered by frequency."""
    with _connect() as conn:
        if frequency:
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE digest_frequency = ?
                ORDER BY created_at DESC
                """,
                (frequency,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE COALESCE(digest_frequency, 'weekly') != 'off'
                ORDER BY created_at DESC
                """
            ).fetchall()
    return [dict(r) for r in rows]


def update_digest_last_sent(user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute("UPDATE users SET digest_last_sent_at = ? WHERE id = ?", (now, user_id))


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
