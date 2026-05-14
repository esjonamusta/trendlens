from __future__ import annotations

import pytest

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
    )
