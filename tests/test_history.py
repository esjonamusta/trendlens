"""Tests for the history DB layer (app/db/history.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.db.history as history_module
from app.db.history import (
    find_previous_snapshot,
    init_db,
    list_snapshots,
    save_snapshot,
)


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all DB operations to a fresh temp file for each test."""
    monkeypatch.setattr(history_module, "DB_PATH", tmp_path / "test.db")
    init_db()


def _ts(days_ago: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def _save(
    run_id: str,
    domain: str = "developer experience",
    days_ago: float = 0.0,
    topics: list[dict] | None = None,
) -> None:
    save_snapshot(
        run_id=run_id,
        domain=domain,
        config={"domain": domain},
        report={"items": []},
        topics=topics or [{"rank": 1, "headline": "Test headline", "keywords": [], "confidence": "High", "source_count": 3, "sources": ["web"], "pm_action": "Watch."}],
        created_at=_ts(days_ago),
    )


# ── Baseline behaviour ────────────────────────────────────────────────────────

def test_first_run_returns_no_previous():
    """find_previous_snapshot returns None when DB is empty."""
    result = find_previous_snapshot("developer experience", before_run_id="run-1")
    assert result is None


def test_save_and_retrieve():
    """A saved snapshot can be retrieved via list_snapshots."""
    _save("run-1", days_ago=0)
    rows = list_snapshots("developer experience")
    assert len(rows) == 1
    assert rows[0].run_id == "run-1"


# ── 7-day comparison selection ────────────────────────────────────────────────

def test_prefers_7_day_snapshot_over_most_recent():
    """When both a recent and a 7-day snapshot exist, prefer the 7-day one."""
    _save("run-recent", days_ago=1)
    _save("run-7day", days_ago=7)

    result = find_previous_snapshot("developer experience", before_run_id="run-current")
    assert result is not None
    assert result.run_id == "run-7day"


def test_7_day_window_is_6_to_8_days():
    """A snapshot 6.5 days ago is closer to 7 days than one 2 days ago."""
    _save("run-close", days_ago=2)
    _save("run-near-7", days_ago=6.5)

    result = find_previous_snapshot("developer experience", before_run_id="run-current")
    assert result is not None
    assert result.run_id == "run-near-7"


# ── Fallback to most recent ───────────────────────────────────────────────────

def test_falls_back_to_most_recent_when_no_7day():
    """Falls back to the most recent snapshot when no 7-day snapshot exists."""
    _save("run-3day", days_ago=3)
    _save("run-1day", days_ago=1)

    # Neither is near 7 days — should return the one closest to 7 days
    # run-3day is closer to 7 than run-1day
    result = find_previous_snapshot("developer experience", before_run_id="run-current")
    assert result is not None
    assert result.run_id == "run-3day"


def test_excludes_current_run_id():
    """The before_run_id run itself is never returned as the previous snapshot."""
    _save("run-only", days_ago=7)

    result = find_previous_snapshot("developer experience", before_run_id="run-only")
    assert result is None


# ── Domain isolation ──────────────────────────────────────────────────────────

def test_domain_isolation():
    """Snapshots from different domains are kept separate."""
    _save("run-devex", domain="developer experience", days_ago=7)
    _save("run-fintech", domain="fintech compliance", days_ago=7)

    result = find_previous_snapshot("developer experience", before_run_id="run-current")
    assert result is not None
    assert result.run_id == "run-devex"

    result2 = find_previous_snapshot("fintech compliance", before_run_id="run-current")
    assert result2 is not None
    assert result2.run_id == "run-fintech"


# ── list_snapshots ────────────────────────────────────────────────────────────

def test_list_snapshots_ordered_newest_first():
    _save("run-old", days_ago=10)
    _save("run-mid", days_ago=5)
    _save("run-new", days_ago=0)

    rows = list_snapshots("developer experience")
    assert [r.run_id for r in rows] == ["run-new", "run-mid", "run-old"]


def test_list_snapshots_limit():
    for i in range(5):
        _save(f"run-{i}", days_ago=float(i))

    rows = list_snapshots("developer experience", limit=3)
    assert len(rows) == 3


# ── Minimum gap enforcement ───────────────────────────────────────────────────

def test_min_gap_excludes_snapshot_within_gap():
    """A snapshot newer than min_gap_hours should not be returned."""
    _save("run-recent", days_ago=0.5)  # 12 hours ago

    result = find_previous_snapshot(
        "developer experience",
        before_run_id="run-current",
        min_gap_hours=24,
    )
    assert result is None


def test_min_gap_allows_snapshot_outside_gap():
    """A snapshot older than min_gap_hours should be returned."""
    _save("run-old-enough", days_ago=2)  # 48 hours ago

    result = find_previous_snapshot(
        "developer experience",
        before_run_id="run-current",
        min_gap_hours=24,
    )
    assert result is not None
    assert result.run_id == "run-old-enough"


def test_min_gap_skips_recent_prefers_older():
    """When one snapshot is within the gap and one is outside, return the older one."""
    _save("run-too-recent", days_ago=0.25)   # 6 hours ago — within 24h gap
    _save("run-eligible", days_ago=3)         # 3 days ago — outside gap

    result = find_previous_snapshot(
        "developer experience",
        before_run_id="run-current",
        min_gap_hours=24,
    )
    assert result is not None
    assert result.run_id == "run-eligible"
