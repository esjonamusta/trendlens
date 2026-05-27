from __future__ import annotations

from app.core.schemas import TopicSnapshot


def make_topic(
    headline: str,
    rank: int = 1,
    confidence: str = "High",
    source_count: int = 5,
    sources: list[str] | None = None,
    keywords: list[str] | None = None,
    pm_action: str = "Monitor closely.",
    matched_url_count: int = 0,
    matched_domains: list[str] | None = None,
    freshness_score: float = 0.5,
    novelty_score: float = 0.5,
    first_seen_at: str = "",
    last_seen_at: str = "",
    canonical_topic_id: str = "",
    weighted_evidence_score: float = 0.0,
) -> TopicSnapshot:
    if sources is None:
        sources = ["podcast", "reddit", "web"]
    if keywords is None:
        keywords = headline.lower().split()[:4]
    return TopicSnapshot(
        rank=rank,
        headline=headline,
        keywords=keywords,
        confidence=confidence,
        source_count=source_count,
        sources=sources,
        pm_action=pm_action,
        matched_url_count=matched_url_count,
        matched_domains=matched_domains or [],
        freshness_score=freshness_score,
        novelty_score=novelty_score,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        canonical_topic_id=canonical_topic_id,
        weighted_evidence_score=weighted_evidence_score,
    )
