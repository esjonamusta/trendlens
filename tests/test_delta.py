"""Tests for the delta engine (app/services/delta.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.delta import (
    _DECLINE_THRESHOLD,
    _SPIKE_THRESHOLD,
    COOLING_AFTER_MISSING_RUNS,
    DISAPPEARED_AFTER_DAYS,
    DORMANT_AFTER_DAYS,
    DORMANT_AFTER_MISSING_RUNS,
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


def _run_delta_with_history(
    current_topics,
    previous_topics,
    days_apart: float = 7.0,
    snapshot_history: list[dict] | None = None,
    raw_cluster_ids: set[str] | None = None,
):
    return compute_delta(
        current_topics=current_topics,
        previous_topics=previous_topics,
        previous_run_id="prev-run",
        previous_created_at=_ts(days_ago=days_apart),
        current_created_at=_ts(days_ago=0),
        snapshot_history=snapshot_history or [],
        raw_cluster_ids=raw_cluster_ids or set(),
    )


def _make_snap(topics: list, days_ago: float) -> dict:
    return {
        "topics": [t.model_dump() for t in topics],
        "created_at": _ts(days_ago=days_ago),
    }


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
    """A previous topic with no match ends up in lifecycle, not in disappeared (needs 14+ days for that)."""
    current = [make_topic("Agent infrastructure tooling grows", rank=1)]
    previous = [
        make_topic("Agent infrastructure tooling grows", rank=1),
        make_topic("Blockchain payments regulation news", rank=2),
    ]

    result = _run_delta(current, previous)
    # With no snapshot_history, 1 missed run → NOT_DETECTED_THIS_RUN (not DISAPPEARED)
    assert result.disappeared == []
    assert any("Blockchain" in lc.topic_headline for lc in result.lifecycle)
    blockchain_lc = next(lc for lc in result.lifecycle if "Blockchain" in lc.topic_headline)
    assert blockchain_lc.status == "NOT_DETECTED_THIS_RUN"


def test_no_false_disappeared_when_matched():
    """Matched topics should not appear in disappeared or lifecycle."""
    topic = make_topic("Open source agent infrastructure tooling", rank=1)
    result = _run_delta([topic], [topic])
    assert result.disappeared == []
    assert result.lifecycle == []


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
    # Unmatched previous topic enters lifecycle as NOT_DETECTED_THIS_RUN (1 miss, needs 14+ days for DISAPPEARED)
    assert len(result.lifecycle) == 1
    assert result.lifecycle[0].status == "NOT_DETECTED_THIS_RUN"


# ── Freshness and novelty guards ──────────────────────────────────────────────

def test_stale_only_topic_not_classified_new():
    """A topic with stale-only freshness that has no previous match must not be NEW THIS RUN."""
    current = [make_topic(
        "AI compliance tools 2023 guide",
        rank=1,
        freshness_score=0.2,  # all sources are stale
        keywords=["compliance", "tools", "guide"],
    )]
    previous = [make_topic("Fintech payment solutions blockchain", rank=1)]
    result = _run_delta(current, previous)
    assert result.insights[0].classification != "NEW THIS RUN", (
        "Stale-only content reappearing should not be classified as a new trend"
    )


def test_stale_only_topic_cannot_spike():
    """A topic where all evidence is stale must not be classified SPIKING even with high delta."""
    previous = [make_topic(
        "Agent workflow tooling", rank=3, source_count=5, confidence="Medium",
        freshness_score=0.2,
    )]
    current = [make_topic(
        "Agent workflow tooling", rank=1, source_count=20, confidence="High",
        freshness_score=0.2,  # all stale
    )]
    result = _run_delta(current, previous)
    assert result.insights[0].classification != "SPIKING VS LAST RUN", (
        "A topic whose growth comes from stale repeated content must not spike"
    )


def test_fresh_topic_can_be_classified_new():
    """A topic with fresh evidence and no previous match is NEW THIS RUN."""
    current = [make_topic(
        "Brand new AI framework launched today",
        rank=1,
        freshness_score=1.0,
        keywords=["framework", "launched", "today"],
    )]
    previous = [make_topic("Fintech compliance regulation banking", rank=1)]
    result = _run_delta(current, previous)
    assert result.insights[0].classification == "NEW THIS RUN"


def test_fresh_topic_can_spike():
    """A topic with fresh evidence and strong growth is SPIKING."""
    previous = [make_topic(
        "Agent workflow tooling", rank=3, source_count=5, confidence="Medium",
        freshness_score=1.0,
    )]
    current = [make_topic(
        "Agent workflow tooling", rank=1, source_count=20, confidence="High",
        freshness_score=1.0,
    )]
    result = _run_delta(current, previous)
    assert result.insights[0].classification == "SPIKING VS LAST RUN"


# ── Lifecycle classification ──────────────────────────────────────────────────

def test_lifecycle_not_detected_this_run():
    """An unmatched previous topic with no history → NOT_DETECTED_THIS_RUN."""
    current = [make_topic("Agent infrastructure tooling grows", rank=1)]
    previous = [
        make_topic("Agent infrastructure tooling grows", rank=1),
        make_topic("Blockchain payments news", rank=2, canonical_topic_id="abc123"),
    ]
    result = _run_delta_with_history(current, previous, snapshot_history=[])
    assert len(result.lifecycle) == 1
    assert result.lifecycle[0].status == "NOT_DETECTED_THIS_RUN"
    assert result.lifecycle[0].consecutive_missing_runs == 1


def test_lifecycle_cooling_after_2_misses():
    """2 consecutive missed runs → COOLING."""
    blockchain = make_topic("Blockchain payments news", rank=2, canonical_topic_id="abc123")
    current = [make_topic("Agent infrastructure tooling grows", rank=1)]
    previous = [
        make_topic("Agent infrastructure tooling grows", rank=1),
        blockchain,
    ]
    # snapshot_history[0] (1 day ago): no blockchain; snapshot_history[1] (2 days ago): has it
    history = [
        _make_snap([make_topic("Agent infrastructure tooling", rank=1)], days_ago=1.0),
        _make_snap([blockchain], days_ago=2.0),
    ]
    result = _run_delta_with_history(current, previous, days_apart=2.0, snapshot_history=history)
    blockchain_lc = next(lc for lc in result.lifecycle if "Blockchain" in lc.topic_headline)
    assert blockchain_lc.status == "COOLING"
    assert blockchain_lc.consecutive_missing_runs == COOLING_AFTER_MISSING_RUNS


def test_lifecycle_dormant_after_5_misses():
    """5 consecutive missed runs → DORMANT."""
    blockchain = make_topic("Blockchain payments news", rank=1, canonical_topic_id="abc123")
    current = [make_topic("Agent infrastructure tooling", rank=1)]
    previous = [blockchain]
    # 4 history snapshots without the topic, then the 5th has it
    history = [
        _make_snap([make_topic("Unrelated topic alpha", rank=1)], days_ago=1.0),
        _make_snap([make_topic("Unrelated topic beta", rank=1)], days_ago=2.0),
        _make_snap([make_topic("Unrelated topic gamma", rank=1)], days_ago=3.0),
        _make_snap([make_topic("Unrelated topic delta", rank=1)], days_ago=4.0),
        _make_snap([blockchain], days_ago=5.0),
    ]
    result = _run_delta_with_history(current, previous, days_apart=5.0, snapshot_history=history)
    lc = result.lifecycle[0]
    assert lc.status == "DORMANT"
    assert lc.consecutive_missing_runs >= DORMANT_AFTER_MISSING_RUNS


def test_lifecycle_dormant_after_7_days():
    """7+ days since last_seen_at triggers DORMANT even with few consecutive misses."""
    old_topic = make_topic(
        "Blockchain payments news", rank=1,
        canonical_topic_id="abc123",
        last_seen_at=_ts(days_ago=8.0),
    )
    current = [make_topic("Agent infrastructure tooling", rank=1)]
    previous = [old_topic]
    # Single snapshot 8 days ago with the topic
    history = [_make_snap([old_topic], days_ago=8.0)]
    result = _run_delta_with_history(current, previous, days_apart=8.0, snapshot_history=history)
    lc = result.lifecycle[0]
    assert lc.status == "DORMANT"
    assert lc.days_since_last_seen >= DORMANT_AFTER_DAYS


def test_lifecycle_disappeared_after_14_days():
    """14+ days since last_seen_at → DISAPPEARED, and it appears in disappeared list."""
    old_topic = make_topic(
        "Blockchain payments news", rank=1,
        canonical_topic_id="abc123",
        last_seen_at=_ts(days_ago=15.0),
    )
    current = [make_topic("Agent infrastructure tooling", rank=1)]
    previous = [old_topic]
    history = [_make_snap([old_topic], days_ago=15.0)]
    result = _run_delta_with_history(current, previous, days_apart=15.0, snapshot_history=history)
    lc = result.lifecycle[0]
    assert lc.status == "DISAPPEARED"
    assert lc.days_since_last_seen >= DISAPPEARED_AFTER_DAYS
    assert any("Blockchain" in h for h in result.disappeared)


def test_lifecycle_not_detected_when_in_raw_clusters():
    """Topic in raw_cluster_ids → NOT_DETECTED_THIS_RUN even with long absence."""
    old_topic = make_topic(
        "Blockchain payments news", rank=1,
        canonical_topic_id="abc123",
        last_seen_at=_ts(days_ago=20.0),
    )
    current = [make_topic("Agent infrastructure tooling", rank=1)]
    previous = [old_topic]
    result = _run_delta_with_history(
        current, previous,
        days_apart=20.0,
        snapshot_history=[],
        raw_cluster_ids={"abc123"},  # still detected in clustering this run
    )
    lc = result.lifecycle[0]
    assert lc.status == "NOT_DETECTED_THIS_RUN"
    assert result.disappeared == []


def test_disappeared_field_only_contains_truly_disappeared():
    """The disappeared list must not include COOLING, DORMANT, or NOT_DETECTED topics."""
    cooling = make_topic("Cooling topic here", rank=2, canonical_topic_id="cool01")
    old = make_topic(
        "Truly gone topic here", rank=3,
        canonical_topic_id="gone01",
        last_seen_at=_ts(days_ago=16.0),
    )
    current = [make_topic("Agent infrastructure tooling", rank=1)]
    previous = [make_topic("Agent infrastructure tooling", rank=1), cooling, old]
    history = [
        _make_snap([cooling], days_ago=1.0),
        _make_snap([old], days_ago=16.0),
    ]
    result = _run_delta_with_history(current, previous, days_apart=7.0, snapshot_history=history)
    # Only the truly disappeared topic should be in disappeared
    assert len(result.disappeared) == 1
    assert "Truly gone" in result.disappeared[0]
    # Both should be in lifecycle
    statuses = {lc.topic_headline: lc.status for lc in result.lifecycle}
    assert any("Cooling" in h for h in statuses)
    assert any("Truly gone" in h for h in statuses)


def test_new_subtopic_reclassified_new_when_novelty_high():
    """A matched topic with novelty_score >= 0.7 should surface as NEW, not STABLE."""
    previous = [make_topic(
        "AI compliance tools enterprise",
        rank=1, source_count=5, confidence="High",
        keywords=["compliance", "tools", "enterprise"],
    )]
    current = [make_topic(
        "AI compliance tools small business",
        rank=1, source_count=5, confidence="High",
        keywords=["compliance", "tools", "small", "business"],
        novelty_score=0.8,   # high — introduces new subtopic angle
        freshness_score=0.8,
    )]
    result = _run_delta(current, previous)
    assert result.insights[0].classification == "NEW THIS RUN", (
        "High-novelty topics matched to an old canonical should surface as NEW"
    )
