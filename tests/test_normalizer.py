"""Tests for topic keyword extraction and similarity (app/services/normalizer.py)."""
from __future__ import annotations

from app.core.schemas import EvidenceItem, ResearchItem, SearchSource
from app.services.normalizer import (
    extract_keywords,
    item_to_topic_snapshot,
    match_topic_to_sources,
    topic_similarity,
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


import pytest


# ── match_topic_to_sources ────────────────────────────────────────────────────

def _source(title: str, url: str, snippet: str = "", kind: str = "web") -> SearchSource:
    return SearchSource(url=url, title=title, type=kind, snippet=snippet)


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
) -> ResearchItem:
    return ResearchItem(
        headline=headline,
        what_happened="Concrete facts about what happened here.",
        why_it_matters="Why this matters for a PM.",
        podcast_evidence=[EvidenceItem(text=e) for e in (podcast_evidence or [])],
        reddit_evidence=[EvidenceItem(text=e) for e in (reddit_evidence or [])],
        source_links=source_links or [],
        confidence=confidence,
        pm_action="Review and take action immediately.",
    )


def test_snapshot_uses_matched_url_count_when_sources_provided():
    item = _make_item(source_links=["https://example.com"])
    sources = [
        _source("Developer tools test headline platform", "https://techcrunch.com/1"),
        _source("Test headline developer tools platform", "https://infoq.com/1"),
    ]
    snap = item_to_topic_snapshot(item, rank=1, search_sources=sources)
    assert snap.matched_url_count == 2
    assert "techcrunch.com" in snap.matched_domains
    assert "infoq.com" in snap.matched_domains


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


def test_snapshot_source_count_uses_matched_when_available():
    item = _make_item()
    sources = [
        _source("Test headline developer tools platform", "https://a.com/1"),
        _source("Developer tools test platform insights", "https://b.com/1"),
        _source("Platform tools developer test analysis", "https://c.com/1"),
    ]
    snap = item_to_topic_snapshot(item, rank=2, search_sources=sources)
    # source_count should equal matched_url_count (real data takes precedence)
    assert snap.source_count == snap.matched_url_count
    assert snap.matched_url_count > 0
