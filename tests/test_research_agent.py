"""Lightweight structural tests for research_agent.py.

These tests do NOT make real LLM or search API calls. They verify:
- Helper function correctness (_deduplicate, _format_clusters_for_llm)
- That item construction uses cluster data (not LLM output) for URLs and confidence
- Schema invariants that prevent hallucinated sources from entering the pipeline
"""
from __future__ import annotations

from app.agents.research_agent import _deduplicate, _format_clusters_for_llm
from app.core.schemas import SearchSource, TrendSummaryText
from app.services.trend_engine import TrendCluster, confidence_for_cluster
from app.services.web_search import QueryResults, SearchResult


# ── _deduplicate ──────────────────────────────────────────────────────────────

def _qr(query: str, urls: list[str], source: str = "web") -> QueryResults:
    return QueryResults(
        query=query,
        results=[SearchResult(title=f"Title {u}", url=u, snippet="") for u in urls],
        source=source,
    )


def test_deduplicate_removes_duplicate_urls_across_queries():
    """A URL appearing in two QueryResults must appear only once after dedup."""
    results = [
        _qr("q1", ["https://a.com/1", "https://b.com/2"]),
        _qr("q2", ["https://b.com/2", "https://c.com/3"]),  # b.com/2 duplicated
    ]
    deduped = _deduplicate(results)
    all_urls = [r.url for qr in deduped for r in qr.results]
    assert len(all_urls) == len(set(all_urls)), "Duplicate URLs survived deduplication"
    assert len(all_urls) == 3


def test_deduplicate_preserves_first_occurrence():
    """When a URL appears twice, the first occurrence is kept."""
    results = [
        _qr("q1", ["https://a.com/1"]),
        _qr("q2", ["https://a.com/1"]),  # duplicate
    ]
    deduped = _deduplicate(results)
    all_urls = [r.url for qr in deduped for r in qr.results]
    assert all_urls == ["https://a.com/1"]


def test_deduplicate_empty_input_returns_empty():
    assert _deduplicate([]) == []


def test_deduplicate_drops_empty_query_results():
    """A QueryResults whose all URLs are duplicates is dropped entirely."""
    results = [
        _qr("q1", ["https://a.com/1"]),
        _qr("q2", ["https://a.com/1"]),  # all dupes → should be dropped
    ]
    deduped = _deduplicate(results)
    assert len(deduped) == 1


# ── _format_clusters_for_llm ──────────────────────────────────────────────────

def _make_source(title: str, url: str, kind: str = "web", snippet: str = "") -> SearchSource:
    return SearchSource(url=url, title=title, type=kind, snippet=snippet)


def _make_cluster(sources: list[SearchSource]) -> TrendCluster:
    from app.services.normalizer import extract_keywords
    all_text = " ".join(f"{s.title} {s.snippet}" for s in sources)
    kws = extract_keywords(all_text)
    return TrendCluster(sources=sources, keywords_set=kws)


def test_format_clusters_includes_url():
    """The LLM prompt must include actual source URLs so the LLM has grounding context."""
    cluster = _make_cluster([
        _make_source("Developer tools news", "https://techcrunch.com/developer-tools"),
    ])
    text = _format_clusters_for_llm([cluster])
    assert "https://techcrunch.com/developer-tools" in text


def test_format_clusters_includes_confidence_label():
    """The formatted cluster includes a confidence label so the LLM knows evidence strength."""
    cluster = _make_cluster([
        _make_source("A", "https://a.com", kind="web"),
        _make_source("B", "https://b.com", kind="podcast"),
        _make_source("C", "https://c.com", kind="reddit"),
    ])
    text = _format_clusters_for_llm([cluster])
    # High/Medium/Low must appear
    assert any(label in text for label in ("High", "Medium", "Low"))


def test_format_clusters_includes_source_type():
    """The formatted cluster shows source type (web/podcast/reddit) per evidence item."""
    cluster = _make_cluster([
        _make_source("Podcast episode about agents", "https://podcast.com/ep1", kind="podcast"),
    ])
    text = _format_clusters_for_llm([cluster])
    assert "podcast" in text.lower()


def test_format_clusters_multiple_clusters_numbered():
    """Multiple clusters must appear as CLUSTER 1, CLUSTER 2, etc."""
    clusters = [
        _make_cluster([_make_source(f"Source {i}", f"https://example.com/{i}") for i in range(2)]),
        _make_cluster([_make_source(f"Other {i}", f"https://other.com/{i}") for i in range(2)]),
    ]
    text = _format_clusters_for_llm(clusters)
    assert "CLUSTER 1" in text
    assert "CLUSTER 2" in text


# ── Item construction invariants ─────────────────────────────────────────────

def test_trend_summary_text_has_no_url_fields():
    """TrendSummaryText must have no URL fields — structural proof the LLM cannot generate URLs."""
    forbidden = {"url", "link", "href", "source"}
    url_fields = [
        name for name in TrendSummaryText.model_fields
        if any(word in name.lower() for word in forbidden)
    ]
    assert url_fields == [], f"URL-like fields found in TrendSummaryText: {url_fields}"


def test_trend_summary_text_has_no_confidence_field():
    """Confidence is set deterministically from the cluster; LLM must not be able to override it."""
    assert "confidence" not in TrendSummaryText.model_fields


def test_confidence_label_is_deterministic_from_cluster():
    """confidence_for_cluster returns the same label for the same inputs — no LLM involved."""
    cluster_a = TrendCluster(
        sources=[
            _make_source("A", "https://a.com", kind="web"),
            _make_source("B", "https://b.com", kind="podcast"),
            _make_source("C", "https://c.com", kind="reddit"),
        ],
        keywords_set=frozenset({"agent", "developer", "tools"}),
    )
    cluster_b = TrendCluster(
        sources=list(cluster_a.sources),  # same sources
        keywords_set=frozenset({"agent", "developer", "tools"}),
    )
    score_a, label_a = confidence_for_cluster(cluster_a)
    score_b, label_b = confidence_for_cluster(cluster_b)
    assert label_a == label_b
    assert score_a == score_b


def test_cluster_source_urls_are_subset_of_search_sources():
    """URLs in a cluster must come from the input search sources, not fabricated."""
    input_urls = {"https://a.com/1", "https://b.com/2", "https://c.com/3"}
    sources = [_make_source(f"Title {u}", u) for u in input_urls]
    from app.services.trend_engine import cluster_search_results
    clusters = cluster_search_results(sources)
    cluster_urls = {url for c in clusters for url in c.source_urls}
    assert cluster_urls <= input_urls, (
        f"Cluster URLs not a subset of search result URLs: {cluster_urls - input_urls}"
    )


# ── Prompt drift guards ───────────────────────────────────────────────────────

def test_format_clusters_shows_evidence_count():
    """Cluster formatting must expose evidence count so the LLM knows signal strength."""
    sources = [
        _make_source("Source A", "https://a.com"),
        _make_source("Source B", "https://b.com"),
        _make_source("Source C", "https://c.com"),
    ]
    cluster = _make_cluster(sources)
    text = _format_clusters_for_llm([cluster])
    # Should mention the source count
    assert "3" in text or "sources" in text.lower()


def test_format_clusters_shows_canonical_topic():
    """The most descriptive title (canonical topic) must appear in the formatted cluster."""
    cluster = _make_cluster([
        _make_source("MCP", "https://short.com"),
        _make_source("Model Context Protocol adoption across developer tools", "https://long.com"),
    ])
    text = _format_clusters_for_llm([cluster])
    assert "Model Context Protocol adoption across developer tools" in text
