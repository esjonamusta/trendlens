"""Tests for the delta engine (app/services/delta.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.delta import (
    _DECLINE_THRESHOLD,
    _SPIKE_THRESHOLD,
    compute_delta,
    compute_trend_delta_score,
)
from tests.conftest import make_topic


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(days_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _run_delta(current_topics, previous_topics, days_apart: float = 7.0):
    return compute_delta(
        current_topics=current_topics,
        previous_topics=previous_topics,
        previous_run_id="prev-run",
        previous_created_at=_ts(days_ago=days_apart),
        current_created_at=_ts(days_ago=0),
    )


# ── New topic detection ───────────────────────────────────────────────────────

def test_new_topic_detected():
    """A topic in the current run with no match in the previous run is NEW THIS RUN."""
    current = [make_topic("Quantum computing enters enterprise", rank=1)]
    previous = [make_topic("Fintech compliance regulation", rank=1)]

    result = _run_delta(current, previous)
    assert result.insights[0].classification == "NEW THIS RUN"
    assert result.insights[0].previous_rank is None


def test_new_topic_has_no_previous_source_count():
    current = [make_topic("Brand-new topic nobody discussed before", rank=1)]
    previous = [make_topic("Completely unrelated previous story here", rank=1)]

    result = _run_delta(current, previous)
    new_insights = [i for i in result.insights if i.classification == "NEW THIS RUN"]
    assert len(new_insights) == 1
    assert new_insights[0].previous_source_count is None


# ── Disappeared topic detection ───────────────────────────────────────────────

def test_disappeared_topic_detected():
    """A previous topic with no match in the current run appears in disappeared."""
    current = [make_topic("Agent infrastructure tooling grows", rank=1)]
    previous = [
        make_topic("Agent infrastructure tooling grows", rank=1),
        make_topic("Blockchain payments regulation news", rank=2),
    ]

    result = _run_delta(current, previous)
    assert any("Blockchain" in h for h in result.disappeared)


def test_no_false_disappeared_when_matched():
    """Matched topics should not appear in disappeared."""
    topic = make_topic("Open source agent infrastructure tooling", rank=1)
    result = _run_delta([topic], [topic])
    assert result.disappeared == []


# ── Spike detection ───────────────────────────────────────────────────────────

def test_spike_detected_on_large_source_growth():
    """A topic whose source count grows significantly should be SPIKING."""
    previous = [make_topic("Agent workflow tooling", rank=3, source_count=5, confidence="Medium")]
    current = [make_topic("Agent workflow tooling", rank=1, source_count=20, confidence="High")]

    result = _run_delta(current, previous)
    assert result.insights[0].classification == "SPIKING VS LAST RUN"
    assert result.insights[0].trend_delta_score >= _SPIKE_THRESHOLD


# ── Declining topic detection ─────────────────────────────────────────────────

def test_declining_detected_on_source_drop():
    """A topic whose source count drops significantly should be DECLINING."""
    previous = [make_topic("Fintech compliance changes", rank=1, source_count=20, confidence="High")]
    current = [make_topic("Fintech compliance changes", rank=3, source_count=3, confidence="Low")]

    result = _run_delta(current, previous)
    assert result.insights[0].classification == "DECLINING"
    assert result.insights[0].trend_delta_score <= _DECLINE_THRESHOLD


# ── Ranking by delta significance ─────────────────────────────────────────────

def test_insights_ranked_by_significance():
    """NEW and SPIKING topics should appear before STABLE ones."""
    current = [
        make_topic("Open source agent infrastructure tooling", rank=1, source_count=5, confidence="High"),
        make_topic("Brand-new AI research breakthrough today", rank=2, source_count=3, confidence="Medium"),
    ]
    previous = [
        make_topic("Open source agent infrastructure tooling", rank=1, source_count=5, confidence="High"),
        # No match for the second current topic → NEW
    ]

    result = _run_delta(current, previous)
    classifications = [i.classification for i in result.insights]
    # NEW should come before STABLE
    assert classifications.index("NEW THIS RUN") < classifications.index("STABLE BUT IMPORTANT")


def test_spiking_ranked_before_stable():
    current = [
        make_topic("Stable topic unchanged", rank=1, source_count=5, confidence="High"),
        make_topic("Spiking agent workflow tooling", rank=2, source_count=18, confidence="High"),
    ]
    previous = [
        make_topic("Stable topic unchanged", rank=1, source_count=5, confidence="High"),
        make_topic("Spiking agent workflow tooling", rank=3, source_count=5, confidence="Medium"),
    ]

    result = _run_delta(current, previous)
    classifications = [i.classification for i in result.insights]
    assert classifications.index("SPIKING VS LAST RUN") < classifications.index("STABLE BUT IMPORTANT")


# ── Comparison type ───────────────────────────────────────────────────────────

def test_comparison_type_7_day():
    topic = make_topic("Some topic", rank=1)
    result = _run_delta([topic], [topic], days_apart=7.0)
    assert result.comparison_type == "7_day"


def test_comparison_type_most_recent():
    topic = make_topic("Some topic", rank=1)
    result = _run_delta([topic], [topic], days_apart=2.0)
    assert result.comparison_type == "most_recent"


def test_days_apart_stored_correctly():
    topic = make_topic("Some topic", rank=1)
    result = _run_delta([topic], [topic], days_apart=7.0)
    assert abs(result.days_apart - 7.0) < 0.1


# ── Delta score ───────────────────────────────────────────────────────────────

def test_score_positive_when_rank_and_sources_improve():
    prev = make_topic("Agent infrastructure", rank=3, source_count=5, confidence="Medium")
    cur = make_topic("Agent infrastructure", rank=1, source_count=15, confidence="High")
    score = compute_trend_delta_score(cur, prev)
    assert score > 0


def test_score_negative_when_rank_and_sources_decline():
    prev = make_topic("Agent infrastructure", rank=1, source_count=15, confidence="High")
    cur = make_topic("Agent infrastructure", rank=3, source_count=5, confidence="Low")
    score = compute_trend_delta_score(cur, prev)
    assert score < 0


def test_score_near_zero_when_unchanged():
    topic = make_topic("Agent infrastructure", rank=2, source_count=8, confidence="Medium")
    score = compute_trend_delta_score(topic, topic)
    assert abs(score) < 0.05


# ── Near-duplicate deduplication ─────────────────────────────────────────────

def test_near_duplicate_headlines_match_as_same_topic():
    """Two headlines about the same story should be matched, not treated as new."""
    current = [make_topic(
        "Open-source agent infrastructure grows rapidly",
        rank=1, keywords=["open", "source", "agent", "infrastructure", "grows"],
    )]
    previous = [make_topic(
        "Agent infrastructure open source tooling sees rapid developer adoption",
        rank=2, keywords=["agent", "infrastructure", "open", "source", "tooling", "developer"],
    )]

    result = _run_delta(current, previous)
    # Should be matched (not NEW), so no NEW THIS RUN classification
    classifications = [i.classification for i in result.insights]
    assert "NEW THIS RUN" not in classifications
    assert result.disappeared == []


# ── Grounded scoring (matched_url_count / matched_domains) ────────────────────

def test_delta_uses_matched_url_count_over_source_count():
    """When matched_url_count is set, it drives the score — not source_count."""
    previous = make_topic("Agent workflow tooling", rank=1, source_count=100,
                          matched_url_count=5)
    current = make_topic("Agent workflow tooling", rank=1, source_count=100,
                         matched_url_count=15)
    # source_count unchanged (both 100), but matched_url_count grew → positive score
    score = compute_trend_delta_score(current, previous)
    assert score > 0


def test_delta_falls_back_to_source_count_when_matched_is_zero():
    """When matched_url_count is 0, source_count is used as before."""
    previous = make_topic("Agent workflow tooling", rank=1, source_count=5,
                          matched_url_count=0)
    current = make_topic("Agent workflow tooling", rank=1, source_count=15,
                         matched_url_count=0)
    score = compute_trend_delta_score(current, previous)
    assert score > 0


def test_delta_diversity_uses_matched_domains_when_available():
    """More unique matched domains → positive diversity contribution."""
    previous = make_topic("Developer tools trends", rank=1,
                          matched_domains=["techcrunch.com"])
    current = make_topic("Developer tools trends", rank=1,
                         matched_domains=["techcrunch.com", "infoq.com", "reddit.com"])
    score = compute_trend_delta_score(current, previous)
    # Two new domains added → diversity contribution is positive
    assert score > 0


def test_delta_diversity_falls_back_to_sources_when_no_domains():
    """When matched_domains is empty, falls back to source type tags for diversity."""
    previous = make_topic("Developer tools trends", rank=1,
                          sources=["web"], matched_domains=[])
    current = make_topic("Developer tools trends", rank=1,
                         sources=["web", "reddit", "podcast"], matched_domains=[])
    score = compute_trend_delta_score(current, previous)
    assert score > 0


# ── Unrelated headlines ───────────────────────────────────────────────────────

def test_unrelated_headlines_not_matched():
    """Two completely unrelated headlines should NOT be matched."""
    current = [make_topic(
        "Quantum computing enterprise adoption",
        rank=1, keywords=["quantum", "computing", "enterprise", "adoption"],
    )]
    previous = [make_topic(
        "Fintech compliance regulation banking",
        rank=1, keywords=["fintech", "compliance", "regulation", "banking"],
    )]

    result = _run_delta(current, previous)
    classifications = [i.classification for i in result.insights]
    assert "NEW THIS RUN" in classifications
    assert len(result.disappeared) == 1
