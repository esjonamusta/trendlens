"""Tests for the deterministic trend clustering layer (app/services/trend_engine.py)."""
from __future__ import annotations

from datetime import date

from app.core.schemas import SearchSource, TrendSummaryList, TrendSummaryText
from app.services.trend_engine import (
    CONCEPT_MAP,
    TrendCluster,
    _SPECIFIC_CONCEPT_TOKENS,
    _STALE_CUTOFF,
    _is_stale,
    _merge_clusters,
    cluster_search_results,
    confidence_for_cluster,
    normalize_for_clustering,
    rank_clusters,
    source_quality_weight,
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


# ── Acronym / concept normalisation ──────────────────────────────────────────

def test_normalize_mcp_acronym():
    assert "mcp" in normalize_for_clustering("MCP servers")


def test_normalize_model_context_protocol_collapses_to_mcp():
    result = normalize_for_clustering("Model Context Protocol adoption")
    assert "mcp" in result
    assert "model" not in result
    assert "context" not in result
    assert "protocol" not in result


def test_normalize_llm_full_form_collapses():
    result = normalize_for_clustering("Large Language Model training costs")
    assert "llm" in result
    assert "large" not in result


def test_normalize_llms_plural_collapses():
    result = normalize_for_clustering("LLMs are getting cheaper")
    assert "llm" in result


def test_normalize_rag_full_form():
    result = normalize_for_clustering("retrieval augmented generation pipeline")
    assert "rag" in result


def test_normalize_unknown_term_unchanged():
    result = normalize_for_clustering("Quantum computing enterprise adoption")
    assert "quantum" in result
    assert "computing" in result


def test_concept_map_has_no_uppercase_keys():
    """All keys must be lowercase so the case-insensitive match works correctly."""
    for key in CONCEPT_MAP:
        assert key == key.lower(), f"CONCEPT_MAP key '{key}' is not lowercase"


# ── MCP clustering ────────────────────────────────────────────────────────────

def test_mcp_acronym_and_full_form_cluster_together():
    """'MCP servers' and 'Model Context Protocol adoption' must become one cluster."""
    sources = [
        _src("MCP servers gaining enterprise adoption"),
        _src("Model Context Protocol adoption across developer tools"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 1, (
        f"Expected 1 cluster but got {len(clusters)}: "
        + str([c.canonical_topic for c in clusters])
    )


def test_anthropic_mcp_ecosystem_joins_mcp_cluster():
    """All three MCP-related sources — acronym, full form, vendor prefix — become one cluster."""
    sources = [
        _src("MCP servers gaining enterprise adoption"),
        _src("Model Context Protocol adoption across developer tools"),
        _src("Anthropic MCP ecosystem and third-party integrations"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 1, (
        f"Expected 1 cluster but got {len(clusters)}: "
        + str([c.canonical_topic for c in clusters])
    )
    assert clusters[0].evidence_count == 3


def test_llm_acronym_and_full_form_cluster_together():
    sources = [
        _src("LLM inference costs dropping sharply"),
        _src("Large Language Model training optimisation trends"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 1


def test_canonical_topic_prefers_most_descriptive_title():
    """canonical_topic should pick the longest (most descriptive) title in the cluster."""
    sources = [
        _src("MCP"),
        _src("Model Context Protocol adoption across developer tools"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 1
    assert clusters[0].canonical_topic == "Model Context Protocol adoption across developer tools"


def test_aliases_exclude_canonical_topic():
    """aliases must not repeat the canonical_topic title."""
    sources = [
        _src("MCP servers gaining enterprise adoption"),
        _src("Model Context Protocol adoption across developer tools"),
        _src("Anthropic MCP ecosystem and integrations"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 1
    canonical = clusters[0].canonical_topic
    assert canonical not in clusters[0].aliases


# ── Generic tokens do not merge unrelated topics ──────────────────────────────

def test_agent_alone_does_not_merge_unrelated_topics():
    """Sharing only 'agent' (1 token out of 5+) must not be enough to cluster."""
    sources = [
        _src("Agent workflow automation enterprise solutions"),
        _src("Agent customer chatbot service platform"),
    ]
    clusters = cluster_search_results(sources)
    # {agent} shared; Jaccard = 1/9 = 0.11 < 0.20; "agent" not a specific concept token
    assert len(clusters) == 2, (
        "Topics sharing only 'agent' should not cluster — generic token false positive"
    )


def test_platform_alone_does_not_merge_unrelated_topics():
    sources = [
        _src("Developer productivity measurement tooling survey"),
        _src("Platform migration cloud infrastructure deployment"),
    ]
    clusters = cluster_search_results(sources)
    assert len(clusters) == 2


def test_tool_alone_does_not_merge_unrelated_topics():
    sources = [
        _src("Developer tools productivity measurement platform"),
        _src("Compliance reporting tools enterprise regulation audit"),
    ]
    clusters = cluster_search_results(sources)
    # Shared: {tools} = 1 token; Jaccard = 1/8 = 0.125 < 0.20
    assert len(clusters) == 2


# ── Post-merge correctness ────────────────────────────────────────────────────

def test_merge_clusters_combines_overlapping_clusters():
    """_merge_clusters must join two clusters that already overlap >= threshold."""
    from app.services.normalizer import extract_keywords
    kws_a = extract_keywords("mcp server developer tools")
    kws_b = extract_keywords("mcp client library developer")
    a = TrendCluster(sources=[_src("A")], keywords_set=kws_a)
    b = TrendCluster(sources=[_src("B")], keywords_set=kws_b)
    merged = _merge_clusters([a, b], threshold=0.20)
    assert len(merged) == 1
    assert merged[0].evidence_count == 2


def test_merge_clusters_leaves_unrelated_clusters_separate():
    from app.services.normalizer import extract_keywords
    kws_a = extract_keywords("mcp server protocol integration")
    kws_b = extract_keywords("fintech compliance regulation banking")
    a = TrendCluster(sources=[_src("A")], keywords_set=kws_a)
    b = TrendCluster(sources=[_src("B")], keywords_set=kws_b)
    merged = _merge_clusters([a, b], threshold=0.20)
    assert len(merged) == 2


def test_api_generic_token_does_not_merge_unrelated_topics():
    """'api' is deliberately excluded from _SPECIFIC_CONCEPT_TOKENS so unrelated API topics stay separate."""
    assert "api" not in _SPECIFIC_CONCEPT_TOKENS
    sources = [
        _src("GitHub Copilot API integration developer tools"),
        _src("Stripe API pricing changes payment processing"),
    ]
    clusters = cluster_search_results(sources)
    # {api} shared but not in _SPECIFIC_CONCEPT_TOKENS; Jaccard = 1/7 = 0.14 < 0.20
    assert len(clusters) == 2


def test_source_urls_still_come_from_search_results_after_merge():
    """After merging, all URLs in the cluster must originate from input sources."""
    input_urls = {"https://a.com", "https://b.com"}
    sources = [
        _src("MCP servers enterprise", url="https://a.com"),
        _src("Model Context Protocol adoption tools", url="https://b.com"),
    ]
    clusters = cluster_search_results(sources)
    cluster_urls = {url for c in clusters for url in c.source_urls}
    assert cluster_urls <= input_urls


# ── Weighted evidence scoring ─────────────────────────────────────────────────

def test_weak_duplicates_do_not_outrank_strong_diverse():
    """5 same-domain reddit posts must not outrank 2 strong, independent sources."""
    weak_many = TrendCluster(
        sources=[
            _src(f"Reddit post {i}", url=f"https://reddit.com/r/tech/post{i}", kind="reddit")
            for i in range(5)
        ],
        keywords_set=frozenset({"developer", "agent"}),
    )
    strong_few = TrendCluster(
        sources=[
            _src("GitHub release notes", url="https://github.com/org/repo/releases"),
            _src("TechCrunch coverage", url="https://techcrunch.com/2026/story"),
        ],
        keywords_set=frozenset({"developer", "agent"}),
    )
    ranked = rank_clusters([weak_many, strong_few])
    assert ranked[0] is strong_few, (
        f"strong_few ws={strong_few.weighted_evidence_score:.3f} should beat "
        f"weak_many ws={weak_many.weighted_evidence_score:.3f}"
    )


def test_all_stale_sources_cannot_reach_high_confidence():
    """A cluster where every source is stale must not be High confidence."""
    cluster = TrendCluster(
        sources=[
            _src(f"Trend report {_STALE_CUTOFF}", url=f"https://domain{i}.com/post")
            for i in range(5)
        ],
        keywords_set=frozenset({"developer", "tools"}),
        stale_count=5,
    )
    _, label = confidence_for_cluster(cluster)
    assert label != "High", "All-stale cluster must not reach High confidence"


def test_same_domain_sources_have_diminishing_returns():
    """5 same-domain sources must score lower than 2 strong independent sources."""
    same_domain = TrendCluster(
        sources=[
            _src(f"Medium article {i}", url=f"https://medium.com/article-{i}")
            for i in range(5)
        ],
        keywords_set=frozenset({"developer"}),
    )
    diverse = TrendCluster(
        sources=[
            _src("GitHub release", url="https://github.com/org/repo"),
            _src("Tech article", url="https://techcrunch.com/post"),
        ],
        keywords_set=frozenset({"developer"}),
    )
    assert diverse.weighted_evidence_score > same_domain.weighted_evidence_score, (
        f"diverse ws={diverse.weighted_evidence_score:.3f} should beat "
        f"same_domain ws={same_domain.weighted_evidence_score:.3f}"
    )


def test_raw_evidence_count_preserved_alongside_weighted_score():
    """evidence_count is always the raw source count; weighted_evidence_score is always lower."""
    sources = [_src("A"), _src("B"), _src("C")]
    cluster = TrendCluster(sources=sources, keywords_set=frozenset({"developer", "tools"}))
    assert cluster.evidence_count == 3
    # Diminishing returns guarantee ws < raw count for any realistic quality weight ≤ 1.0
    assert cluster.weighted_evidence_score < cluster.evidence_count
    assert cluster.weighted_evidence_score > 0
