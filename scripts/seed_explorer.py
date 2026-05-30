#!/usr/bin/env python3
"""Seed history.db with sourced trend data for the Trend Explorer demo.

Run:  python scripts/seed_explorer.py
Then: make run -> open http://localhost:8000/app
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import history as history_db
from app.db import tracked_domains as td_db


DOMAIN = "expense management"

CONFIG = {
    "domain": DOMAIN,
    "max_items": 3,
    "time_window_days": 7,
    "competitors": ["Ramp", "Brex", "Expensify", "SAP Concur"],
    "target_users": "finance teams and operations managers",
    "geographic_market": "US",
}


TREND_LIBRARY = {
    "zero_touch": {
        "headline": "AI pushes expense reporting toward zero-touch workflows",
        "keywords": ["ai", "zero-touch", "receipt", "coding", "expense"],
        "confidence": "High",
        "sources": ["podcast", "reddit", "web"],
        "canonical_topic_id": "expense-zero-touch-ai",
        "pm_action": "Prototype receipt capture that extracts merchant, amount, tax, category, and GL code before the user opens the form.",
        "what_happened": (
            "Recent practitioner discussions and vendor coverage point to expense tools moving from receipt upload to automated capture, coding, "
            "approval routing, and ERP sync. The strongest signals are mobile receipt capture, AI OCR, and automatic GL categorization."
        ),
        "why_it_matters": (
            "Manual entry is becoming the visible failure point in expense products. PMs can differentiate by reducing the workflow to review and exception handling."
        ),
        "podcast_evidence": [
            {
                "text": "Tearsheet Podcast - Ramp's AI-powered push to automate expense management",
                "url": "https://podcasts.apple.com/us/podcast/ramps-ai-powered-push-to-automate-expense-management/id423234173?i=1000696750396",
            },
            {
                "text": "Maintenance Care podcast - expense management and corporate card platform discussion",
                "url": "https://www.maintenancecare.com/podcast-s03e07-mitchell-fratrik",
            },
        ],
        "reddit_evidence": [
            {
                "text": "r/Accounting - receipt management discussion highlights text-based receipt capture and OCR automation",
                "url": "https://www.reddit.com/r/Accounting/comments/1sziu5i/receipt_management/",
            },
            {
                "text": "r/corporatetravel - expense management software thread compares automation, receipt capture, GL coding, and ERP sync",
                "url": "https://www.reddit.com/r/corporatetravel/comments/1sn7iyv/best_expense_management_software_what_actually/",
            },
        ],
        "source_links": [
            "https://www.mobilexpense.com/en/blog/expense-management-trends-2026",
            "https://payhawk.com/en-us/podcast",
            "https://expenseanywhere.com/zero-touch-expense-reporting-ai-automated-expense-management-2026/",
        ],
        "unique_domain_count": 6,
    },
    "card_first": {
        "headline": "Corporate-card-first platforms keep displacing reimbursements",
        "keywords": ["corporate-card", "reimbursement", "virtual-card", "spend-control"],
        "confidence": "High",
        "sources": ["reddit", "web", "podcast"],
        "canonical_topic_id": "expense-card-first",
        "pm_action": "Map the reimbursement journey against a card-first flow and identify where policy controls can move before purchase.",
        "what_happened": (
            "Reddit and industry coverage show finance teams comparing reimbursement-heavy processes with card-first products from Ramp, Brex, Payhawk, "
            "Rippling, BILL Spend & Expense, and similar platforms."
        ),
        "why_it_matters": (
            "The buying criterion is shifting from expense report UX to real-time card controls, receipt matching, policy enforcement, and accounting sync."
        ),
        "podcast_evidence": [
            {
                "text": "Tearsheet Podcast - Ramp CPO discusses AI and unified financial operations",
                "url": "https://podcasts.apple.com/us/podcast/ramps-ai-powered-push-to-automate-expense-management/id423234173?i=1000696750396",
            }
        ],
        "reddit_evidence": [
            {
                "text": "r/Accounting - reimbursement delays thread surfaces pain from personal-card spend and missing receipts",
                "url": "https://www.reddit.com/r/Accounting/comments/1ohn91k/all_of_our_expense_reimbursements_are_taking_3/",
            },
            {
                "text": "r/corporatetravel - thread compares Ramp, Expensify, Brex, cards, and virtual cards",
                "url": "https://www.reddit.com/r/corporatetravel/comments/1sn7iyv/best_expense_management_software_what_actually/",
            },
        ],
        "source_links": [
            "https://www.techradar.com/best/best-expense-trackers",
            "https://payhawk.com/en-us/podcast",
            "https://www.businesstravelexecutive.com/news/blockskye-adds-ai-powered-expense-tracking-and-reimbursement-solution/",
        ],
        "unique_domain_count": 5,
    },
    "receipt_fraud": {
        "headline": "AI-generated receipts turn expense fraud into a product problem",
        "keywords": ["ai-generated", "receipt", "fraud", "verification", "audit"],
        "confidence": "High",
        "sources": ["web", "reddit"],
        "canonical_topic_id": "expense-receipt-fraud",
        "pm_action": "Add receipt authenticity checks, card/merchant matching, and exception review before expanding AI-assisted submissions.",
        "what_happened": (
            "New discussions around fake receipt generation and receipt forensics are converging with expense platforms' push toward automation. "
            "The same AI that reduces filing friction also raises the bar for verification and audit trails."
        ),
        "why_it_matters": (
            "If users can submit polished fake receipts, a faster workflow can amplify fraud. Trust, auditability, and card-data matching should be roadmap items."
        ),
        "podcast_evidence": [
            {
                "text": "Winners' Circle podcast - Oversight CEO discusses AI monitoring across card spend and T&E",
                "url": "https://www.iheart.com/podcast/269-winners-circle-329296562/episode/your-company-is-bleeding-money-right-329296571/",
            }
        ],
        "reddit_evidence": [
            {
                "text": "r/Dynamics365 - practitioners discuss AI-generated fake expense receipts",
                "url": "https://www.reddit.com/r/Dynamics365/comments/1q7etqk/have_aigenerated_fake_expense_receipts_come_up_at/",
            },
            {
                "text": "r/smallbusiness - fake expense reports thread discusses controls and card-based systems",
                "url": "https://www.reddit.com/r/smallbusiness/comments/1pdax88/i_caught_an_employee_submitting_fake_expense/",
            },
        ],
        "source_links": [
            "https://news.ycombinator.com/item?id=45790677",
            "https://arxiv.org/abs/2603.11442",
            "https://www.digitaltransactions.net/wp-content/uploads/2026/05/DT_0526_FINAL.pdf",
            "https://expensevisor.com/how-ai-is-transforming-expense-management/",
        ],
        "unique_domain_count": 6,
    },
    "open_source_receipts": {
        "headline": "Open-source AI receipt tooling gives teams a build-vs-buy option",
        "keywords": ["open-source", "receipt", "ocr", "self-hosted", "ai"],
        "confidence": "Medium",
        "sources": ["web"],
        "canonical_topic_id": "expense-open-source-receipts",
        "pm_action": "Benchmark self-hosted receipt OCR projects before committing to a vendor-only extraction roadmap.",
        "what_happened": (
            "GitHub results show active interest in self-hosted receipt scanning, AI categorization, and document intelligence for invoices and receipts."
        ),
        "why_it_matters": (
            "Enterprise buyers may ask for privacy-preserving or self-hosted extraction paths. Open-source tools also raise the baseline for commodity OCR features."
        ),
        "podcast_evidence": [],
        "reddit_evidence": [],
        "source_links": [
            "https://github.com/vas3k/TaxHacker",
            "https://github.com/1oannis/budget-lens",
            "https://github.com/Receipt-Wrangler",
            "https://github.com/opencollective/opencollective/issues/6865",
            "https://github.com/renefichtmueller/PaperCortex",
        ],
        "unique_domain_count": 2,
    },
    "mobile_receipts": {
        "headline": "Mobile-first receipt capture remains the adoption wedge",
        "keywords": ["mobile", "receipt", "capture", "employee", "adoption"],
        "confidence": "Medium",
        "sources": ["reddit", "web"],
        "canonical_topic_id": "expense-mobile-receipts",
        "pm_action": "Design the receipt flow around instant mobile prompts instead of monthly report assembly.",
        "what_happened": (
            "User discussions repeatedly frame receipt capture as an employee-compliance problem, not just a finance workflow problem. "
            "The strongest products collect receipts at the point of spend."
        ),
        "why_it_matters": (
            "Finance teams care about complete records, but employees care about avoiding extra work. Mobile prompts can improve compliance before audit time."
        ),
        "podcast_evidence": [],
        "reddit_evidence": [
            {
                "text": "r/Accounting - receipt management thread emphasizes employee friction and timely submission",
                "url": "https://www.reddit.com/r/Accounting/comments/1sziu5i/receipt_management/",
            },
            {
                "text": "r/smallbusiness - users ask for corporate-card-integrated apps and mobile upload",
                "url": "https://www.reddit.com/r/smallbusiness/comments/1kn9pzo/expense_management_softwares/",
            },
        ],
        "source_links": [
            "https://www.mobilexpense.com/en/blog/expense-management-trends-2026",
            "https://payhawk.com/en-us/podcast",
        ],
        "unique_domain_count": 4,
    },
}


RUNS = [
    {
        "days_ago": 14,
        "topics": [
            ("mobile_receipts", "STABLE BUT IMPORTANT", 1, 8, 1.6, 0.55),
            ("card_first", "STABLE BUT IMPORTANT", 2, 7, 1.4, 0.55),
            ("open_source_receipts", "WEAK SIGNAL TO WATCH", 3, 4, 0.8, 0.45),
            ("zero_touch", "WEAK SIGNAL TO WATCH", 4, 3, 0.6, 0.45),
            ("receipt_fraud", "WEAK SIGNAL TO WATCH", 5, 2, 0.4, 0.40),
        ],
    },
    {
        "days_ago": 7,
        "topics": [
            ("card_first", "SPIKING VS LAST RUN", 1, 13, 2.7, 0.65),
            ("zero_touch", "NEW THIS RUN", 2, 10, 2.3, 0.70),
            ("open_source_receipts", "STABLE BUT IMPORTANT", 3, 6, 1.2, 0.55),
            ("mobile_receipts", "STABLE BUT IMPORTANT", 4, 5, 1.0, 0.55),
            ("receipt_fraud", "WEAK SIGNAL TO WATCH", 5, 3, 0.7, 0.50),
        ],
    },
    {
        "days_ago": 3,
        "topics": [
            ("zero_touch", "SPIKING VS LAST RUN", 1, 18, 4.3, 0.82),
            ("card_first", "STABLE BUT IMPORTANT", 2, 14, 2.8, 0.68),
            ("receipt_fraud", "NEW THIS RUN", 3, 8, 2.0, 0.90),
            ("mobile_receipts", "STABLE BUT IMPORTANT", 4, 6, 1.1, 0.58),
            ("open_source_receipts", "WEAK SIGNAL TO WATCH", 5, 4, 0.9, 0.52),
        ],
    },
    {
        "days_ago": 1,
        "topics": [
            ("zero_touch", "STABLE BUT IMPORTANT", 1, 19, 4.4, 0.84),
            ("receipt_fraud", "SPIKING VS LAST RUN", 2, 14, 3.5, 0.95),
            ("card_first", "STABLE BUT IMPORTANT", 3, 13, 2.5, 0.70),
            ("open_source_receipts", "STABLE BUT IMPORTANT", 4, 7, 1.4, 0.60),
            ("mobile_receipts", "DECLINING", 5, 5, 0.9, 0.55),
        ],
    },
    {
        "days_ago": 0,
        "topics": [
            ("receipt_fraud", "SPIKING VS LAST RUN", 1, 18, 4.6, 0.98),
            ("zero_touch", "STABLE BUT IMPORTANT", 2, 17, 4.0, 0.86),
            ("card_first", "DECLINING", 3, 10, 2.0, 0.66),
            ("open_source_receipts", "STABLE BUT IMPORTANT", 4, 7, 1.5, 0.62),
            ("mobile_receipts", "WEAK SIGNAL TO WATCH", 5, 5, 1.0, 0.58),
        ],
    },
]


def _confidence_source_count(confidence: str, default: int) -> int:
    if confidence == "High":
        return max(default, 3)
    if confidence == "Medium":
        return max(default, 2)
    return max(default, 1)


def build_item(key: str, evidence_count: int, weighted_score: float, freshness: float) -> dict:
    base = deepcopy(TREND_LIBRARY[key])
    base["evidence_count"] = evidence_count
    base["weighted_evidence_score"] = weighted_score
    base["freshness_score"] = freshness
    base["novelty_score"] = 0.6
    base["grounded"] = True
    return {
        "headline": base["headline"],
        "what_happened": base["what_happened"],
        "why_it_matters": base["why_it_matters"],
        "podcast_evidence": base["podcast_evidence"],
        "reddit_evidence": base["reddit_evidence"],
        "source_links": base["source_links"],
        "confidence": base["confidence"],
        "pm_action": base["pm_action"],
        "grounded": base["grounded"],
        "evidence_count": base["evidence_count"],
        "weighted_evidence_score": base["weighted_evidence_score"],
        "unique_domain_count": base["unique_domain_count"],
        "freshness_score": base["freshness_score"],
        "novelty_score": base["novelty_score"],
        "first_seen_at": "",
        "last_seen_at": "",
    }


def build_topic(
    key: str,
    classification: str,
    rank: int,
    source_count: int,
    weighted_score: float,
    freshness: float,
) -> dict:
    base = TREND_LIBRARY[key]
    return {
        "rank": rank,
        "headline": base["headline"],
        "keywords": base["keywords"],
        "confidence": base["confidence"],
        "source_count": _confidence_source_count(base["confidence"], source_count),
        "sources": base["sources"],
        "pm_action": base["pm_action"],
        "weighted_evidence_score": weighted_score,
        "classification": classification,
        "canonical_topic_id": base["canonical_topic_id"],
        "freshness_score": freshness,
        "novelty_score": 0.7 if classification == "NEW THIS RUN" else 0.35,
        "first_seen_at": "",
        "last_seen_at": "",
        "matched_url_count": min(source_count, len(base["source_links"]) + len(base["reddit_evidence"]) + len(base["podcast_evidence"])),
        "matched_domains": [],
        "llm_reported_source_count": source_count,
    }


def build_search_sources(items: list[dict]) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()
    for item in items:
        for ev in item["podcast_evidence"]:
            if ev["url"] not in seen:
                seen.add(ev["url"])
                sources.append({"url": ev["url"], "title": ev["text"], "type": "podcast", "snippet": ""})
        for ev in item["reddit_evidence"]:
            if ev["url"] not in seen:
                seen.add(ev["url"])
                sources.append({"url": ev["url"], "title": ev["text"], "type": "reddit", "snippet": ""})
        for url in item["source_links"]:
            if url not in seen:
                seen.add(url)
                sources.append({"url": url, "title": url, "type": "web", "snippet": ""})
    return sources


def seed_run(run: dict) -> None:
    run_id = str(uuid.uuid4())
    created_at = (datetime.now(timezone.utc) - timedelta(days=run["days_ago"])).isoformat()

    topics = [
        build_topic(key, classification, rank, source_count, weighted_score, freshness)
        for key, classification, rank, source_count, weighted_score, freshness in run["topics"]
    ]
    items = [
        build_item(key, source_count, weighted_score, freshness)
        for key, _classification, _rank, source_count, weighted_score, freshness in run["topics"]
    ]
    for item in items:
        item["first_seen_at"] = created_at
        item["last_seen_at"] = created_at
    for topic in topics:
        topic["first_seen_at"] = created_at
        topic["last_seen_at"] = created_at

    report = {
        "config": CONFIG,
        "items": items,
        "generated_at": created_at,
        "search_sources": build_search_sources(items),
        "raw_cluster_canonical_ids": [topic["canonical_topic_id"] for topic in topics],
        "run_id": run_id,
        "delta": None,
        "is_baseline": run["days_ago"] == 14,
        "delta_unavailable_reason": "",
    }

    with sqlite3.connect(history_db.DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO snapshots "
            "(run_id, domain, config_json, report_json, topics_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, DOMAIN, json.dumps(CONFIG), json.dumps(report), json.dumps(topics), created_at),
        )
    print(f"  Seeded sourced run {run_id[:8]} ({run['days_ago']} days ago)")


if __name__ == "__main__":
    history_db.init_db()
    td_db.init_db()

    with sqlite3.connect(history_db.DB_PATH) as conn:
        conn.execute("DELETE FROM snapshots WHERE domain = ?", (DOMAIN,))

    td_db.add_domain(DOMAIN)
    print(f"Seeding sourced demo domain: {DOMAIN!r}")
    for demo_run in RUNS:
        seed_run(demo_run)

    print("\nDone. Now run:")
    print("  make run")
    print("  Open http://localhost:8000/app")
