"""Tests for topic keyword extraction and similarity (app/services/normalizer.py)."""
from __future__ import annotations

import pytest

from app.core.schemas import EvidenceItem, ResearchItem, SearchSource
from app.services.normalizer import (
    _normalize_url,
    extract_keywords,
    item_to_topic_snapshot,
    match_topic_to_sources,
    topic_similarity,
    verify_source_urls,
)


# ── Keyword extraction ────────────────────────────────────────────────────────

def test_extract_keywords_strips_stopwords():
    kws = extract_keywords("the rise of open-source agent infrastructure")
    assert "the" not in kws
    assert "of" not in kws
    assert "rise" in kws
    assert "agent" in kws
    assert "infrastructure" in kws


def test_extract_keywords_lowercases():
    kws = extract_keywords("Open Source Agent")
    assert "open" in kws
    assert "Open" not in kws


def test_extract_keywords_ignores_short_tokens():
    # Regex requires 3+ chars after first char, so 1-2 char words are excluded
    kws = extract_keywords("AI is hot")
    assert "is" not in kws
    # "hot" is 3 chars total (h + ot = 2 after first) — boundary case, may or may not appear
    assert "AI" not in kws  # uppercased "AI" → "ai" is 2 chars total


def test_extract_keywords_returns_frozenset():
    kws = extract_keywords("agent workflow tooling")
    assert isinstance(kws, frozenset)


# ── Topic similarity ──────────────────────────────────────────────────────────

def test_identical_keywords_score_1():
    kws = frozenset({"agent", "workflow", "infrastructure"})
    assert topic_similarity(kws, kws) == 1.0


def test_disjoint_keywords_score_0():
    a = frozenset({"agent", "workflow"})
    b = frozenset({"fintech", "compliance"})
    assert topic_similarity(a, b) == 0.0


def test_partial_overlap():
    a = frozenset({"agent", "workflow", "tool"})
    b = frozenset({"agent", "workflow", "infrastructure"})
    # intersection = {agent, workflow} = 2, union = 4
    assert topic_similarity(a, b) == pytest.approx(2 / 4)


def test_empty_keyword_set_returns_0():
    assert topic_similarity(frozenset(), frozenset({"agent"})) == 0.0
    assert topic_similarity(frozenset({"agent"}), frozenset()) == 0.0


# ── Near-duplicate topic normalisation ───────────────────────────────────────

def test_near_duplicate_topics_have_high_similarity():
    """Two headlines describing the same story should score above the match threshold."""
    kws_a = extract_keywords("Open-source agent infrastructure grows rapidly among developers")
    kws_b = extract_keywords("Agent infrastructure open source tooling sees rapid developer adoption")
    score = topic_similarity(kws_a, kws_b)
    assert score >= 0.20, f"Expected >= 0.20 but got {score:.3f}"


def test_unrelated_topics_have_low_similarity():
    kws_a = extract_keywords("Fintech compliance regulation changes")
    kws_b = extract_keywords("Open-source agent infrastructure tooling")
    score = topic_similarity(kws_a, kws_b)
    assert score < 0.20, f"Expected < 0.20 but got {score:.3f}"


# ── URL normalization ─────────────────────────────────────────────────────────

def test_normalize_url_lowercases_host():
    assert _normalize_url("https://TechCrunch.com/post") == "https://techcrunch.com/post"


def test_normalize_url_strips_www():
    assert _normalize_url("https://www.techcrunch.com/post") == "https://techcrunch.com/post"


def test_normalize_url_strips_trailing_slash():
    assert _normalize_url("https://example.com/path/") == "https://example.com/path"


def test_normalize_url_preserves_query():
    result = _normalize_url("https://example.com/search?q=test")
    assert "q=test" in result


def test_normalize_url_handles_invalid_gracefully():
    # Should not raise; returns something usable
    result = _normalize_url("not-a-url")
    assert isinstance(result, str)


# ── verify_source_urls (URL-exact matching) ───────────────────────────────────

def _source(title: str, url: str, snippet: str = "", kind: str = "web") -> SearchSource:
    return SearchSource(url=url, title=title, type=kind, snippet=snippet)


def test_verify_source_urls_exact_match():
    """URL appearing in both item sources and search_sources → count=1."""
    count, domains = verify_source_urls(
        ["https://techcrunch.com/1"],
        [_source("Developer tools revealed", "https://techcrunch.com/1")],
    )
    assert count == 1
    assert "techcrunch.com" in domains


def test_verify_source_urls_normalized_match():
    """URL with trailing slash or different case still matches."""
    count, _ = verify_source_urls(
        ["https://TechCrunch.com/post/"],
        [_source("Story", "https://techcrunch.com/post")],
    )
    assert count == 1


def test_verify_source_urls_no_match():
    """URL not in search_sources returns count=0 even if keywords overlap."""
    count, domains = verify_source_urls(
        ["https://example.com/made-up"],
        [_source("Developer tools test headline platform", "https://techcrunch.com/1")],
    )
    assert count == 0
    assert domains == []


def test_verify_source_urls_multiple_matches():
    count, domains = verify_source_urls(
        ["https://techcrunch.com/1", "https://infoq.com/1"],
        [
            _source("Story A", "https://techcrunch.com/1"),
            _source("Story B", "https://infoq.com/1"),
        ],
    )
    assert count == 2
    assert set(domains) == {"techcrunch.com", "infoq.com"}


def test_verify_source_urls_deduplicates_domains():
    """Two URLs from the same domain count as 2 but deduplicate in domains list."""
    count, domains = verify_source_urls(
        ["https://techcrunch.com/1", "https://techcrunch.com/2"],
        [
            _source("A", "https://techcrunch.com/1"),
            _source("B", "https://techcrunch.com/2"),
        ],
    )
    assert count == 2
    assert domains == ["techcrunch.com"]  # deduplicated


def test_verify_source_urls_empty_inputs():
    assert verify_source_urls([], []) == (0, [])
    assert verify_source_urls(["https://example.com"], []) == (0, [])
    assert verify_source_urls([], [_source("A", "https://example.com")]) == (0, [])


# ── match_topic_to_sources (keyword-based, weak matching) ─────────────────────

def test_match_finds_relevant_source():
    topic_kws = extract_keywords("Google developer tools announcement")
    sources = [_source("Google I/O 2026 new developer tools revealed", "https://techcrunch.com/1")]
    count, domains = match_topic_to_sources(topic_kws, sources)
    assert count == 1
    assert "techcrunch.com" in domains


def test_match_requires_two_keyword_overlap():
    topic_kws = extract_keywords("Google cloud infrastructure")
    # Only "cloud" overlaps — not enough
    sources = [_source("Cloud computing trends 2026", "https://example.com/1")]
    count, domains = match_topic_to_sources(topic_kws, sources)
    assert count == 0
    assert domains == []


def test_match_uses_snippet_for_overlap():
    topic_kws = extract_keywords("developer productivity measurement platform")
    # Title alone has no overlap, but snippet does
    sources = [_source(
        "Q2 Engineering report",
        "https://blog.example.com/report",
        snippet="developer productivity platform measurement tools",
    )]
    count, _ = match_topic_to_sources(topic_kws, sources)
    assert count == 1


def test_match_deduplicates_domains():
    topic_kws = extract_keywords("developer experience platform tools")
    sources = [
        _source("Developer experience tools roundup", "https://techcrunch.com/1"),
        _source("Platform developer experience guide", "https://techcrunch.com/2"),
        _source("Developer platform experience report", "https://infoq.com/1"),
    ]
    count, domains = match_topic_to_sources(topic_kws, sources)
    assert count == 3
    assert len(domains) == 2  # techcrunch deduplicated
    assert "techcrunch.com" in domains
    assert "infoq.com" in domains


def test_match_empty_sources_returns_zero():
    topic_kws = extract_keywords("developer experience")
    count, domains = match_topic_to_sources(topic_kws, [])
    assert count == 0
    assert domains == []


def test_match_unrelated_sources_not_counted():
    topic_kws = extract_keywords("fintech payment regulation compliance")
    sources = [
        _source("Open source agent infrastructure tooling", "https://github.com/1"),
        _source("Quantum computing enterprise adoption", "https://example.com/2"),
    ]
    count, _ = match_topic_to_sources(topic_kws, sources)
    assert count == 0


# ── item_to_topic_snapshot ────────────────────────────────────────────────────

def _make_item(
    headline: str = "Test headline about developer tools",
    confidence: str = "High",
    podcast_evidence: list | None = None,
    reddit_evidence: list | None = None,
    source_links: list | None = None,
    pm_action: str = "Review and take action immediately.",
) -> ResearchItem:
    return ResearchItem(
        headline=headline,
        what_happened="Concrete facts about what happened here.",
        why_it_matters="Why this matters for a PM.",
        podcast_evidence=[EvidenceItem(text=e) for e in (podcast_evidence or [])],
        reddit_evidence=[EvidenceItem(text=e) for e in (reddit_evidence or [])],
        source_links=source_links or [],
        confidence=confidence,
        pm_action=pm_action,
    )


def test_snapshot_matched_url_count_set_from_url_match():
    """matched_url_count requires URL-exact match against search_sources."""
    sources = [
        _source("Developer tools story A", "https://techcrunch.com/1"),
        _source("Developer tools story B", "https://infoq.com/1"),
    ]
    # item's source_links include the actual search source URLs
    item = _make_item(source_links=["https://techcrunch.com/1", "https://infoq.com/1"])
    snap = item_to_topic_snapshot(item, rank=1, search_sources=sources)
    assert snap.matched_url_count == 2
    assert "techcrunch.com" in snap.matched_domains
    assert "infoq.com" in snap.matched_domains


def test_keyword_overlap_alone_does_not_set_matched_url_count():
    """Generic keyword overlap does NOT create verified grounding (matched_url_count=0)."""
    item = _make_item(source_links=["https://example.com/not-in-sources"])
    sources = [
        _source("Developer tools test headline platform", "https://techcrunch.com/1"),
        _source("Test headline developer tools platform", "https://infoq.com/1"),
    ]
    snap = item_to_topic_snapshot(item, rank=1, search_sources=sources)
    # No URL match → matched_url_count is 0 even though keywords overlap
    assert snap.matched_url_count == 0
    assert snap.matched_domains == []
    # LLM-reported count is still tracked separately
    assert snap.llm_reported_source_count == 1


def test_snapshot_falls_back_to_llm_count_when_no_sources():
    item = _make_item(
        podcast_evidence=["Show A ep 1"],
        reddit_evidence=["r/devops discussion"],
        source_links=["https://x.com", "https://y.com"],
    )
    snap = item_to_topic_snapshot(item, rank=1, search_sources=None)
    assert snap.matched_url_count == 0
    # source_count = 1 podcast + 1 reddit + 2 links = 4
    assert snap.source_count == 4


def test_snapshot_matched_domains_empty_when_no_sources():
    item = _make_item()
    snap = item_to_topic_snapshot(item, rank=1)
    assert snap.matched_domains == []


def test_snapshot_source_count_uses_url_verified_when_available():
    """When URL-verified matches exist, source_count == matched_url_count."""
    sources = [
        _source("A", "https://a.com/1"),
        _source("B", "https://b.com/1"),
    ]
    item = _make_item(source_links=["https://a.com/1", "https://b.com/1"])
    snap = item_to_topic_snapshot(item, rank=2, search_sources=sources)
    assert snap.matched_url_count == 2
    assert snap.source_count == snap.matched_url_count


def test_snapshot_llm_reported_source_count_populated():
    """llm_reported_source_count tracks raw LLM evidence count independently."""
    item = _make_item(
        podcast_evidence=["Podcast A", "Podcast B"],
        reddit_evidence=["Reddit post"],
        source_links=["https://example.com/1"],
    )
    snap = item_to_topic_snapshot(item, rank=1)
    # 2 podcast + 1 reddit + 1 web = 4
    assert snap.llm_reported_source_count == 4


def test_snapshot_llm_count_zero_when_no_evidence():
    item = _make_item()
    snap = item_to_topic_snapshot(item, rank=1)
    assert snap.llm_reported_source_count == 0


# ── Canonical ID stability ────────────────────────────────────────────────────

def test_canonical_id_stable_when_pm_action_changes():
    """Same headline + what_happened → same canonical_topic_id regardless of pm_action."""
    item_a = _make_item(
        headline="AI compliance tools enterprise deployment",
        pm_action="Audit your compliance stack immediately.",
    )
    item_b = _make_item(
        headline="AI compliance tools enterprise deployment",
        pm_action="Schedule a review meeting with your team next week.",
    )
    snap_a = item_to_topic_snapshot(item_a, rank=1)
    snap_b = item_to_topic_snapshot(item_b, rank=1)
    assert snap_a.canonical_topic_id == snap_b.canonical_topic_id, (
        "canonical_topic_id must not change when only pm_action wording changes"
    )


def test_canonical_id_differs_for_unrelated_topics():
    """Different headlines produce different canonical IDs."""
    item_a = _make_item(headline="AI compliance tools enterprise deployment")
    item_b = _make_item(headline="Quantum computing financial modelling breakthrough")
    snap_a = item_to_topic_snapshot(item_a, rank=1)
    snap_b = item_to_topic_snapshot(item_b, rank=1)
    assert snap_a.canonical_topic_id != snap_b.canonical_topic_id


def test_canonical_id_excludes_pm_action_keywords():
    """Keywords used for canonical ID must not include pm_action-only words."""
    item = _make_item(
        headline="Developer tooling trends",
        pm_action="Immediately audit all dependency vulnerabilities now.",
    )
    snap = item_to_topic_snapshot(item, rank=1)
    # "immediately", "audit", "vulnerabilities" are pm_action-only — not in headline/what_happened
    # The what_happened fixture is "Concrete facts about what happened here." so keywords from
    # it are fine, but pm_action-exclusive words must not appear
    pm_only_words = {"immediately", "vulnerabilities"}
    assert not pm_only_words.intersection(set(snap.keywords)), (
        f"pm_action words leaked into snapshot keywords: {pm_only_words & set(snap.keywords)}"
    )
