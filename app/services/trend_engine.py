"""
Deterministic trend detection layer.

Takes raw SearchSource objects from the search layer and:
1. Clusters them by keyword similarity (no LLM)
2. Scores each cluster by evidence count and source diversity
3. Flags stale sources (only old year references in text)
4. Ranks clusters by signal strength

The LLM never touches URLs, confidence labels, or trend counts.
Those are computed here and passed to the summarization step as read-only facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.core.schemas import SearchSource
from app.services.normalizer import extract_keywords, topic_similarity

_CURRENT_YEAR = date.today().year
_CLUSTER_THRESHOLD = 0.20
_STALE_CUTOFF = _CURRENT_YEAR - 2  # years ≤ this are considered stale (e.g. 2024 and below in 2026)


@dataclass
class TrendCluster:
    sources: list[SearchSource] = field(default_factory=list)
    keywords_set: frozenset[str] = field(default_factory=frozenset)
    stale_count: int = 0  # sources where all year references are stale

    @property
    def canonical_topic(self) -> str:
        return self.sources[0].title if self.sources else ""

    @property
    def aliases(self) -> list[str]:
        return [s.title for s in self.sources[1:]]

    @property
    def source_urls(self) -> list[str]:
        return [s.url for s in self.sources]

    @property
    def evidence_count(self) -> int:
        return len(self.sources)

    @property
    def fresh_count(self) -> int:
        return self.evidence_count - self.stale_count

    @property
    def source_type_set(self) -> set[str]:
        return {s.type for s in self.sources}


def _is_stale(source: SearchSource) -> bool:
    """Return True when the source only references years older than _STALE_CUTOFF."""
    text = f"{source.title} {source.snippet}"
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return False  # no year signal — assume fresh
    return max(years) <= _STALE_CUTOFF


def cluster_search_results(
    sources: list[SearchSource],
    threshold: float = _CLUSTER_THRESHOLD,
) -> list[TrendCluster]:
    """
    Group search results into topic clusters by keyword similarity.

    Each source joins the most similar existing cluster (greedy), or starts a new one.
    Sources with no extractable keywords are silently skipped.
    """
    clusters: list[TrendCluster] = []

    for source in sources:
        source_kws = extract_keywords(f"{source.title} {source.snippet}")
        if not source_kws:
            continue

        best_sim, best_cluster = 0.0, None
        for cluster in clusters:
            sim = topic_similarity(cluster.keywords_set, source_kws)
            if sim > best_sim:
                best_sim, best_cluster = sim, cluster

        stale = _is_stale(source)

        if best_sim >= threshold and best_cluster is not None:
            best_cluster.sources.append(source)
            best_cluster.keywords_set = best_cluster.keywords_set | source_kws
            if stale:
                best_cluster.stale_count += 1
        else:
            clusters.append(TrendCluster(
                sources=[source],
                keywords_set=source_kws,
                stale_count=1 if stale else 0,
            ))

    return clusters


def confidence_for_cluster(cluster: TrendCluster) -> tuple[float, str]:
    """
    Compute a deterministic confidence score from evidence count and source diversity.
    Stale sources are half-weighted so old evergreen content doesn't inflate confidence.

    Returns (score: float 0-1, label: "High" | "Medium" | "Low")
    """
    effective = cluster.fresh_count + 0.5 * cluster.stale_count
    diversity = len(cluster.source_type_set)

    if effective >= 3 and diversity >= 2:
        return 0.9, "High"
    if effective >= 3 or diversity >= 2:
        return 0.6, "Medium"
    if effective >= 2:
        return 0.4, "Medium"
    return 0.2, "Low"


def rank_clusters(clusters: list[TrendCluster]) -> list[TrendCluster]:
    """
    Sort clusters by signal strength: effective evidence count (desc), then source type diversity (desc).
    """
    def _key(c: TrendCluster) -> tuple[float, int]:
        effective = c.fresh_count + 0.5 * c.stale_count
        return (-effective, -len(c.source_type_set))

    return sorted(clusters, key=_key)
