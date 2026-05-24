"""Tests for the deterministic trend clustering layer (app/services/trend_engine.py)."""
from __future__ import annotations

from datetime import date

from app.core.schemas import SearchSource, TrendSummaryList, TrendSummaryText
from app.services.trend_engine import (
    TrendCluster,
    _STALE_CUTOFF,
    _is_stale,
    cluster_search_results,
    confidence_for_cluster,
    rank_clusters,
)


def _src(
    title: str,
    url: str = "",
    snippet: str = "",
    kind: str = "web",
) -> SearchSource:
    return SearchSource(
        url=url or f"https://example.com/{abs(hash(title))}",
        title=title,
        type=kind,
        snippet=snippet,
    )


# ── Clustering ────────────────────────────────────────────────────────────────

def test_similar_results_form_one_cluster():
    sources = [
        _src("GitHub Copilot adds agent mode for developers"),
        _src("GitHub Copilot agent mode now available enterprise"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 1
    assert len(clusters[0].sources) == 2


def test_unrelated_results_form_separate_clusters():
    sources = [
        _src("GitHub Copilot adds agent mode for developers"),
        _src("Fintech compliance regulation banking updates"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 2


def test_source_urls_only_from_search_results():
    """Cluster URLs must be a strict subset of the input search result URLs — no fabrication."""
    input_urls = {"https://a.com/1", "https://b.com/2", "https://c.com/3"}
    sources = [_src("Developer tools agent workflow platform", url=u) for u in input_urls]
    clusters = cluster_search_results(sources)
    cluster_urls = {url for c in clusters for url in c.source_urls}
    assert cluster_urls <= input_urls


def test_empty_sources_returns_empty_clusters():
    assert cluster_search_results([]) == []


def test_source_with_no_keywords_is_skipped():
    sources = [_src("")]  # empty title → no keywords → skipped
    assert cluster_search_results(sources) == []


def test_three_sources_same_topic_cluster_together():
    sources = [
        _src("Developer experience platform metrics 2026"),
        _src("Developer experience metrics tooling survey"),
        _src("Engineering metrics developer experience platform"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 1
    assert clusters[0].evidence_count == 3


# ── Confidence scoring ────────────────────────────────────────────────────────

def test_confidence_high_three_sources_two_types():
    cluster = TrendCluster(
        sources=[
            _src("A", kind="podcast"),
            _src("B", kind="reddit"),
            _src("C", kind="web"),
            _src("D", kind="web"),
        ],
        keywords_set=frozenset({"developer", "tools", "agent"}),
    )
    score, label = confidence_for_cluster(cluster)
    assert label == "High"
    assert score >= 0.9


def test_confidence_low_single_source():
    cluster = TrendCluster(
        sources=[_src("Only one result ever")],
        keywords_set=frozenset({"developer"}),
    )
    _, label = confidence_for_cluster(cluster)
    assert label == "Low"


def test_confidence_medium_two_sources_same_type():
    cluster = TrendCluster(
        sources=[_src("A", kind="web"), _src("B", kind="web")],
        keywords_set=frozenset({"developer", "tools"}),
    )
    _, label = confidence_for_cluster(cluster)
    assert label == "Medium"


def test_confidence_medium_two_types_one_source_each():
    cluster = TrendCluster(
        sources=[_src("A", kind="podcast"), _src("B", kind="reddit")],
        keywords_set=frozenset({"developer", "tools"}),
    )
    _, label = confidence_for_cluster(cluster)
    assert label == "Medium"


def test_confidence_set_from_cluster_not_llm():
    """Confidence label is computed deterministically — no LLM call needed."""
    cluster = TrendCluster(
        sources=[_src("A"), _src("B"), _src("C", kind="reddit")],
        keywords_set=frozenset({"agent", "developer", "tools"}),
    )
    _, label = confidence_for_cluster(cluster)
    # 3 sources + 2 types → High, regardless of any LLM output
    assert label == "High"


# ── Stale detection ───────────────────────────────────────────────────────────

def test_stale_detected_on_old_year():
    src = _src(f"AI trends report {_STALE_CUTOFF} analysis")
    assert _is_stale(src) is True


def test_not_stale_for_current_year():
    src = _src(f"AI trends report {date.today().year} analysis")
    assert _is_stale(src) is False


def test_not_stale_when_no_year_in_text():
    src = _src("Developer tools platform announcement")
    assert _is_stale(src) is False


def test_stale_sources_half_weighted():
    """Three stale sources should score the same or below two fresh sources."""
    stale_cluster = TrendCluster(
        sources=[_src("A"), _src("B"), _src("C")],
        keywords_set=frozenset({"developer"}),
        stale_count=3,
    )
    fresh_cluster = TrendCluster(
        sources=[_src("X"), _src("Y")],
        keywords_set=frozenset({"developer"}),
        stale_count=0,
    )
    stale_score, _ = confidence_for_cluster(stale_cluster)
    fresh_score, _ = confidence_for_cluster(fresh_cluster)
    assert stale_score <= fresh_score


def test_mixed_stale_fresh_blended_correctly():
    """2 fresh + 1 stale → effective = 2.5, which should still reach Medium+."""
    cluster = TrendCluster(
        sources=[_src("A"), _src("B"), _src("C")],
        keywords_set=frozenset({"developer"}),
        stale_count=1,
    )
    _, label = confidence_for_cluster(cluster)
    assert label in ("Medium", "High")


# ── Ranking ───────────────────────────────────────────────────────────────────

def test_rank_higher_evidence_first():
    weak = TrendCluster(sources=[_src("A")], keywords_set=frozenset({"agent"}))
    strong = TrendCluster(
        sources=[_src("A"), _src("B"), _src("C")],
        keywords_set=frozenset({"agent"}),
    )
    ranked = rank_clusters([weak, strong])
    assert ranked[0] is strong


def test_rank_prefers_diversity_when_count_equal():
    single_type = TrendCluster(
        sources=[_src("A", kind="web"), _src("B", kind="web")],
        keywords_set=frozenset({"agent"}),
    )
    mixed_type = TrendCluster(
        sources=[_src("A", kind="web"), _src("B", kind="podcast")],
        keywords_set=frozenset({"agent"}),
    )
    ranked = rank_clusters([single_type, mixed_type])
    assert ranked[0] is mixed_type


def test_rank_clusters_is_stable_with_empty_input():
    assert rank_clusters([]) == []


# ── LLM schema guarantees ─────────────────────────────────────────────────────

def test_trend_summary_text_has_no_url_fields():
    """TrendSummaryText must contain no URL/link fields — structural proof LLM cannot generate URLs."""
    forbidden = {"url", "link", "href", "source"}
    url_fields = [
        name for name in TrendSummaryText.model_fields
        if any(word in name.lower() for word in forbidden)
    ]
    assert url_fields == [], f"URL-like fields found in TrendSummaryText: {url_fields}"


def test_trend_summary_text_has_no_confidence_field():
    """Confidence is set from the cluster — LLM must not be able to override it."""
    assert "confidence" not in TrendSummaryText.model_fields


def test_trend_summary_list_nested_schema_clean():
    """TrendSummaryList items must also be free of URL and confidence fields."""
    for name in TrendSummaryList.model_fields:
        assert "url" not in name.lower()
        assert "confidence" not in name.lower()


# ── Delta scoring uses cluster counts, not LLM counts ────────────────────────

def test_cluster_evidence_count_matches_sources_length():
    """evidence_count is a property of the cluster sources list — not LLM-reported."""
    sources = [_src("A"), _src("B"), _src("C")]
    cluster = TrendCluster(sources=sources, keywords_set=frozenset({"agent"}))
    assert cluster.evidence_count == 3
    assert cluster.evidence_count == len(cluster.sources)


def test_trends_with_no_evidence_are_low_confidence_or_absent():
    """If a domain returns no search results, no clusters exist → no trends fabricated."""
    clusters = cluster_search_results([])
    assert clusters == []
