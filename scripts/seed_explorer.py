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

# Full report items with realistic sources for the expand panel
REPORT_ITEMS = [
    {
        "headline": "AI receipt scanning replacing manual entry in B2B finance tools",
        "what_happened": "Three major expense management platforms (Expensify, Ramp, and Brex) shipped AI-powered receipt scanning in the last 30 days. HN threads show 240%+ engagement growth on related discussions. GitHub activity on OCR and receipt-parsing open-source repos is up significantly.",
        "why_it_matters": "Manual receipt entry is the #1 friction point in your B2B expense flow. Competitors are shipping this now — if you don't, you'll lose deals to tools that do.",
        "pm_action": "Audit your receipt flow for AI integration opportunities.",
        "confidence": "High",
        "grounded": True,
        "evidence_count": 17,
        "weighted_evidence_score": 4.2,
        "unique_domain_count": 9,
        "freshness_score": 1.0,
        "novelty_score": 0.8,
        "first_seen_at": "",
        "last_seen_at": "",
        "podcast_evidence": [
            {"text": "The Changelog ep 612 — AI in finance tooling", "url": "https://changelog.com/podcast/612"},
            {"text": "Acquired FM — Ramp's product strategy deep dive", "url": "https://www.acquired.fm/episodes/ramp"},
        ],
        "reddit_evidence": [
            {"text": "r/Accounting — \"Finally tried Expensify's AI scanning, blew my mind\"", "url": "https://reddit.com/r/Accounting/comments/ai_receipt"},
            {"text": "r/smallbusiness — Comparing Ramp vs Brex receipt features", "url": "https://reddit.com/r/smallbusiness/comments/ramp_brex"},
            {"text": "r/fintech — OCR accuracy benchmarks for expense tools 2026", "url": "https://reddit.com/r/fintech/comments/ocr_benchmark"},
        ],
        "source_links": [
            "https://techcrunch.com/2026/05/ramp-ai-receipts",
            "https://news.ycombinator.com/item?id=39901234",
            "https://github.com/anthropics/receipt-ocr",
            "https://www.infoq.com/news/2026/05/ai-expense-scanning",
        ],
    },
    {
        "headline": "Multi-currency support becoming table stakes for finance teams",
        "what_happened": "Reddit threads across r/Accounting and r/fintech show growing frustration with single-currency expense tools. Smaller vendors are shipping multi-currency as a differentiator, with 11 sources mentioning it as a deal-breaker in tool evaluations.",
        "why_it_matters": "For finance teams operating across borders, single-currency tools are being ruled out at the evaluation stage. This is a retention risk for your enterprise segment.",
        "pm_action": "Add currency selector to expense submission form.",
        "confidence": "Medium",
        "grounded": True,
        "evidence_count": 11,
        "weighted_evidence_score": 2.1,
        "unique_domain_count": 5,
        "freshness_score": 0.7,
        "novelty_score": 0.3,
        "first_seen_at": "",
        "last_seen_at": "",
        "podcast_evidence": [
            {"text": "CFO Thought Leader ep 88 — Global finance stack for SMBs", "url": "https://cfothoughtleader.com/episode/88"},
        ],
        "reddit_evidence": [
            {"text": "r/Accounting — \"We had to switch tools because no multi-currency\"", "url": "https://reddit.com/r/Accounting/comments/multicurrency"},
            {"text": "r/fintech — Multi-currency expense management comparison 2026", "url": "https://reddit.com/r/fintech/comments/currency_comparison"},
        ],
        "source_links": [
            "https://www.g2.com/categories/expense-management",
            "https://www.capterra.com/expense-report-software/",
            "https://techcrunch.com/2026/04/multicurrency-expense",
        ],
    },
    {
        "headline": "Per-diem reimbursement models losing ground to real-time cards",
        "what_happened": "6 sources signal a slow but consistent shift away from per-diem reimbursement toward real-time corporate card spending. Reddit discussions suggest finance managers prefer cards for auditability.",
        "why_it_matters": "If your product is built around per-diem workflows, usage may decline as corporate cards become the default. Worth tracking over the next quarter.",
        "pm_action": "Survey users on per-diem vs corporate card preference.",
        "confidence": "Low",
        "grounded": True,
        "evidence_count": 6,
        "weighted_evidence_score": 0.9,
        "unique_domain_count": 3,
        "freshness_score": 0.5,
        "novelty_score": 0.2,
        "first_seen_at": "",
        "last_seen_at": "",
        "podcast_evidence": [],
        "reddit_evidence": [
            {"text": "r/Accounting — \"Is per-diem still relevant in 2026?\"", "url": "https://reddit.com/r/Accounting/comments/perdiem_2026"},
        ],
        "source_links": [
            "https://www.theregister.com/2026/03/corporate-cards-replace-perdiem",
            "https://hbr.org/2026/04/corporate-travel-expense-trends",
        ],
    },
]

REPORT = {
    "config": {"domain": DOMAIN, "max_items": 3, "time_window_days": 7, "competitors": [], "target_users": "", "geographic_market": ""},
    "items": REPORT_ITEMS,
    "generated_at": "",
    "search_sources": [],
    "raw_cluster_canonical_ids": [],
    "run_id": "",
    "delta": None,
    "is_baseline": True,
    "delta_unavailable_reason": "",
}


def seed_run(days_ago: int) -> None:
    run_id = str(uuid.uuid4())
    REPORT["run_id"] = run_id
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
        (run_id, DOMAIN, json.dumps(config), json.dumps(REPORT), json.dumps(TRENDS), created_at),
    )
    conn.commit()
    conn.close()
    print(f"  Seeded run {run_id[:8]}… ({days_ago} days ago)")


if __name__ == "__main__":
    # Clear old seeded data first
    import sqlite3
    history_db.init_db()
    td_db.init_db()
    conn = sqlite3.connect(history_db.DB_PATH)
    conn.execute("DELETE FROM snapshots WHERE domain = ?", (DOMAIN,))
    conn.commit()
    conn.close()

    td_db.add_domain(DOMAIN)
    print(f"Seeding domain: '{DOMAIN}'")
    for days_ago in [0, 1, 3, 7, 14]:
        seed_run(days_ago)
    print("\nDone! Now run:")
    print("  make run")
    print("  Open http://localhost:8000 → click 'Trend Explorer'")
