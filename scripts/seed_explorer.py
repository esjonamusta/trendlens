#!/usr/bin/env python3
"""Seed history.db with fake trend data for Trend Explorer demo.

Run:  python scripts/seed_explorer.py
Then: make run  → open http://localhost:8000 → Trend Explorer tab
"""
from __future__ import annotations
import json, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db import history as history_db
from app.db import tracked_domains as td_db

DOMAIN = "expense management"

TRENDS = [
    {
        "rank": 1,
        "headline": "AI receipt scanning replacing manual entry in B2B finance tools",
        "keywords": ["ai", "receipt", "scanning", "expense"],
        "confidence": "High",
        "source_count": 17,
        "sources": [],
        "pm_action": "Audit your receipt flow for AI integration opportunities.",
        "weighted_evidence_score": 4.2,
        "classification": "SPIKING VS LAST RUN",
        "canonical_topic_id": "abc001",
        "freshness_score": 1.0,
        "novelty_score": 0.8,
        "first_seen_at": "",
        "last_seen_at": "",
        "matched_url_count": 5,
        "matched_domains": [],
        "llm_reported_source_count": 17,
    },
    {
        "rank": 2,
        "headline": "Multi-currency support becoming table stakes for finance teams",
        "keywords": ["multi-currency", "finance", "teams"],
        "confidence": "Medium",
        "source_count": 11,
        "sources": [],
        "pm_action": "Add currency selector to expense submission form.",
        "weighted_evidence_score": 2.1,
        "classification": "STABLE BUT IMPORTANT",
        "canonical_topic_id": "abc002",
        "freshness_score": 0.7,
        "novelty_score": 0.3,
        "first_seen_at": "",
        "last_seen_at": "",
        "matched_url_count": 3,
        "matched_domains": [],
        "llm_reported_source_count": 11,
    },
    {
        "rank": 3,
        "headline": "Per-diem reimbursement models losing ground to real-time cards",
        "keywords": ["per-diem", "reimbursement", "corporate-cards"],
        "confidence": "Low",
        "source_count": 6,
        "sources": [],
        "pm_action": "Survey users on per-diem vs corporate card preference.",
        "weighted_evidence_score": 0.9,
        "classification": "DECLINING",
        "canonical_topic_id": "abc003",
        "freshness_score": 0.5,
        "novelty_score": 0.2,
        "first_seen_at": "",
        "last_seen_at": "",
        "matched_url_count": 1,
        "matched_domains": [],
        "llm_reported_source_count": 6,
    },
]


def seed_run(days_ago: int) -> None:
    run_id = str(uuid.uuid4())
    created_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    config = {
        "domain": DOMAIN,
        "max_items": 3,
        "time_window_days": 7,
        "competitors": [],
        "target_users": "",
        "geographic_market": "",
    }
    import sqlite3
    conn = sqlite3.connect(history_db.DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO snapshots "
        "(run_id, domain, config_json, report_json, topics_json, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, DOMAIN, json.dumps(config), "{}", json.dumps(TRENDS), created_at),
    )
    conn.commit()
    conn.close()
    print(f"  Seeded run {run_id[:8]}… ({days_ago} days ago)")


if __name__ == "__main__":
    history_db.init_db()
    td_db.init_db()
    td_db.add_domain(DOMAIN)
    print(f"Seeding domain: '{DOMAIN}'")
    for days_ago in [0, 1, 3, 7, 14]:
        seed_run(days_ago)
    print("\nDone! Now run:")
    print("  make run")
    print("  Open http://localhost:8000 → click 'Trend Explorer'")
