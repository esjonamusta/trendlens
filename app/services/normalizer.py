from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from app.core.schemas import ResearchItem, SearchSource, TopicSnapshot

_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "can", "its", "it",
    "this", "that", "these", "those", "amid", "new", "says", "said",
    "report", "reports", "over", "into", "while", "after", "before", "than",
    "more", "less", "now", "just", "also", "about", "how", "why", "what",
    "when", "where", "who", "which", "their", "they", "them", "our", "not",
    "all", "one", "two", "three", "use", "used", "using", "make", "gets",
    "get", "see", "set", "puts", "put", "take", "takes", "show", "shows",
})


def make_canonical_id(keywords: list[str] | frozenset[str]) -> str:
    """Deterministic 12-char ID derived from the sorted keyword set."""
    joined = "|".join(sorted(keywords))
    return hashlib.md5(joined.encode()).hexdigest()[:12]


def extract_keywords(text: str) -> frozenset[str]:
    """Return meaningful lowercase tokens from text, filtering stopwords.

    Hyphens are treated as separators so 'open-source' yields both 'open' and 'source'.
    """
    normalised = text.lower().replace("-", " ")
    tokens = re.findall(r"\b[a-z][a-z]{2,}\b", normalised)
    return frozenset(t for t in tokens if t not in _STOPWORDS)


def topic_similarity(kw_a: frozenset[str], kw_b: frozenset[str]) -> float:
    """Jaccard similarity between two keyword sets. Returns 0.0–1.0."""
    if not kw_a or not kw_b:
        return 0.0
    return len(kw_a & kw_b) / len(kw_a | kw_b)


def _domain(url: str) -> str:
    try:
        return urlparse(url).hostname.removeprefix("www.") or ""  # type: ignore[union-attr]
    except Exception:
        return ""


def match_topic_to_sources(
    topic_kws: frozenset[str],
    search_sources: list[SearchSource],
) -> tuple[int, list[str]]:
    """Count search sources relevant to a topic and return their unique domains.

    A source is considered relevant if its title+snippet shares at least 2 keywords
    with the topic. Returns (matched_url_count, matched_domains).
    """
    matched_domains: list[str] = []
    seen_domains: set[str] = set()
    count = 0

    for source in search_sources:
        source_kws = extract_keywords(f"{source.title} {source.snippet}")
        if len(topic_kws & source_kws) >= 2:
            count += 1
            d = _domain(source.url)
            if d and d not in seen_domains:
                seen_domains.add(d)
                matched_domains.append(d)

    return count, matched_domains


def item_to_topic_snapshot(
    item: ResearchItem,
    rank: int,
    search_sources: list[SearchSource] | None = None,
) -> TopicSnapshot:
    """Convert a ResearchItem into a TopicSnapshot for persistence and delta comparison."""
    sources: list[str] = []
    if item.podcast_evidence:
        sources.append("podcast")
    if item.reddit_evidence:
        sources.append("reddit")
    if item.source_links:
        sources.append("web")

    combined_text = f"{item.headline} {item.what_happened} {item.pm_action}"
    keywords = sorted(extract_keywords(combined_text))
    topic_kws = frozenset(keywords)

    matched_url_count = 0
    matched_domains: list[str] = []

    if search_sources:
        matched_url_count, matched_domains = match_topic_to_sources(topic_kws, search_sources)

    # source_count: real matched URL count when available, LLM-reported count as fallback
    source_count = matched_url_count or (
        len(item.podcast_evidence or [])
        + len(item.reddit_evidence or [])
        + len(item.source_links or [])
    )

    return TopicSnapshot(
        rank=rank,
        headline=item.headline,
        keywords=keywords,
        confidence=item.confidence,
        source_count=max(source_count, 1),
        sources=sources,
        pm_action=item.pm_action,
        matched_url_count=matched_url_count,
        matched_domains=matched_domains,
        freshness_score=item.freshness_score,
        canonical_topic_id=make_canonical_id(keywords),
        weighted_evidence_score=item.weighted_evidence_score,
        # novelty_score, first_seen_at, last_seen_at enriched by the pipeline
    )
