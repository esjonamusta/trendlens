"""
Deterministic trend detection layer.

Takes raw SearchSource objects from the search layer and:
1. Normalises text by collapsing known acronyms and their full forms to a shared
   canonical token, so "MCP" and "Model Context Protocol" produce the same keywords
2. Clusters normalised results by Jaccard similarity (no LLM)
3. Post-merges any clusters whose expanded keyword sets still overlap (greedy fix)
4. Scores each cluster by evidence count and source diversity
5. Flags stale sources (only old year references in text)
6. Ranks clusters by signal strength

The LLM never touches URLs, confidence labels, or trend counts.
Those are computed here and passed to the summarisation step as read-only facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

from app.core.schemas import SearchSource, TopicSnapshot
from app.services.normalizer import extract_keywords, topic_similarity

_CURRENT_YEAR = date.today().year
_PREV_YEAR = _CURRENT_YEAR - 1
_CLUSTER_THRESHOLD = 0.20
_STALE_CUTOFF = _CURRENT_YEAR - 2  # years ≤ this are stale (e.g. 2024 and below in 2026)


# Maps known phrases AND their acronyms to a single canonical token.
# Multi-word phrases must be listed so they are replaced before single tokens.
# All keys must be lowercase.
CONCEPT_MAP: dict[str, str] = {
    # Model Context Protocol
    "model context protocol": "mcp",
    "mcp": "mcp",
    # Large Language Models
    "large language models": "llm",
    "large language model": "llm",
    "llms": "llm",
    "llm": "llm",
    # Retrieval-Augmented Generation
    "retrieval augmented generation": "rag",
    "retrieval-augmented generation": "rag",
    "rag": "rag",
    # Developer Experience
    "developer experience": "devex",
    "devx": "devex",
    "dx": "devex",
    # Application Programming Interface
    "application programming interface": "api",
    "apis": "api",
    "api": "api",
    # Software Development Kit
    "software development kit": "sdk",
    "sdks": "sdk",
    "sdk": "sdk",
    # Kubernetes
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    # DevOps / CI-CD
    "devops": "devops",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "cicd": "cicd",
    # Go-to-market
    "go to market": "gtm",
    "go-to-market": "gtm",
    "gtm": "gtm",
    # SaaS / PaaS
    "software as a service": "saas",
    "saas": "saas",
    "platform as a service": "paas",
    "paas": "paas",
}

# Pre-compiled patterns sorted longest-first so multi-word phrases match before single tokens.
_CONCEPT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(phrase) + r"\b"), canonical)
    for phrase, canonical in sorted(
        CONCEPT_MAP.items(), key=lambda kv: len(kv[0]), reverse=True
    )
]

# Canonical tokens specific enough to warrant merging clusters that share them,
# even when overall Jaccard is below the threshold. Excludes generic terms like
# "api" and "sdk" that appear across completely unrelated topics.
_SPECIFIC_CONCEPT_TOKENS: frozenset[str] = frozenset({
    "mcp",        # Model Context Protocol
    "llm",        # Large Language Model
    "rag",        # Retrieval-Augmented Generation
    "devex",      # Developer Experience
    "kubernetes", # Kubernetes / k8s
})

# Quality weights by observable domain. Sources not listed fall back to type-based defaults.
_QUALITY_DOMAIN_WEIGHTS: dict[str, float] = {
    # Official documentation
    "docs.github.com": 1.0,
    "docs.anthropic.com": 1.0,
    "docs.openai.com": 1.0,
    # Code / release artefacts
    "github.com": 0.8,
    # Practitioner discussion
    "news.ycombinator.com": 0.7,
    "lobste.rs": 0.7,
    # Reputable tech publications
    "techcrunch.com": 0.8,
    "wired.com": 0.8,
    "arstechnica.com": 0.8,
    "theregister.com": 0.8,
    "thenewstack.io": 0.8,
    "infoq.com": 0.8,
    "stackoverflow.blog": 0.8,
    "devops.com": 0.7,
    # Community / practitioner writing
    "substack.com": 0.6,
    # Lower-quality / aggregator
    "medium.com": 0.4,
    "reddit.com": 0.5,
}

# SEO listicle URL pattern — "top-10-tools", "7-best-platforms", etc.
_LISTICLE_RE = re.compile(r"(top-\d|\d+-best|\d+-tools|\d+-ways|\d+-things)", re.IGNORECASE)
# docs.* or doc.* subdomains
_DOCS_SUBDOMAIN_RE = re.compile(r"^docs?\.", re.IGNORECASE)


def _url_domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        return host.removeprefix("www.")
    except Exception:
        return ""


def source_quality_weight(source: SearchSource) -> float:
    """
    Score a search result by observable metadata only — no LLM calls.

    Weights (before stale multiplier):
      official docs / company blog  1.0
      reputable tech publication     0.8
      GitHub repo / release          0.8
      Hacker News                    0.7
      podcast                        0.7
      generic web                    0.6
      Reddit                         0.5
      medium.com / aggregator        0.4
      SEO listicle (URL pattern)     0.2

    Stale sources (all year refs ≤ _STALE_CUTOFF) are multiplied by 0.5.

    When engagement_score is set (from a real API like HN Algolia, GitHub, or Reddit
    OAuth), an additional 1.0–1.5× multiplier is applied so highly-upvoted or
    heavily-starred content ranks above low-engagement content from the same domain.
    """
    domain = _url_domain(source.url)

    if domain in _QUALITY_DOMAIN_WEIGHTS:
        base = _QUALITY_DOMAIN_WEIGHTS[domain]
    elif _DOCS_SUBDOMAIN_RE.match(domain):
        base = 1.0
    elif source.type == "podcast":
        base = 0.7
    elif source.type == "reddit":
        base = 0.5
    elif _LISTICLE_RE.search(source.url):
        base = 0.2
    else:
        base = 0.6

    weight = base * (0.5 if _is_stale(source) else 1.0)

    if source.engagement_score is not None:
        engagement_multiplier = 1.0 + 0.5 * source.engagement_score  # 1.0–1.5×
        weight *= engagement_multiplier

    return weight


def freshness_score(source: SearchSource) -> float:
    """
    Score temporal freshness from year references in title/snippet.

      1.0  current year mentioned
      0.7  previous year only
      0.5  no year signal (neutral)
      0.2  only stale years (≤ _STALE_CUTOFF)
    """
    text = f"{source.title} {source.snippet}"
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return 0.5
    max_year = max(years)
    if max_year >= _CURRENT_YEAR:
        return 1.0
    if max_year >= _PREV_YEAR:
        return 0.7
    return 0.2


def _freshness_multiplier(source: SearchSource) -> float:
    """Internal multiplier applied to weighted_evidence_score.

    Boosts fresh sources; leaves neutral/stale unchanged here because
    source_quality_weight already applies the 0.5 stale penalty.
    """
    text = f"{source.title} {source.snippet}"
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return 1.0
    max_year = max(years)
    if max_year >= _CURRENT_YEAR:
        return 1.2
    if max_year >= _PREV_YEAR:
        return 1.05
    return 1.0  # stale already penalized in source_quality_weight


def novelty_score(
    cluster_kws: frozenset[str],
    history: list[TopicSnapshot],
) -> float:
    """
    Measure how new this topic's keyword composition is relative to stored history.

      1.0  keywords never seen before (completely novel)
      0.0  exact keyword match with a historical topic

    A bonus is added when the cluster introduces keywords absent from all
    historical snapshots — rewarding new subtopics under an old canonical term.
    """
    if not history:
        return 1.0
    if not cluster_kws:
        return 0.5

    max_sim = max(
        topic_similarity(cluster_kws, frozenset(snap.keywords))
        for snap in history
    )

    all_hist_kws: frozenset[str] = frozenset().union(*(frozenset(s.keywords) for s in history))
    new_kw_fraction = len(cluster_kws - all_hist_kws) / len(cluster_kws)

    base_novelty = 1.0 - max_sim
    boosted = base_novelty + (new_kw_fraction * 0.3)
    return round(min(1.0, max(0.0, boosted)), 4)


def normalize_for_clustering(text: str) -> str:
    """
    Lowercase text and replace known concept phrases/acronyms with canonical tokens.

    "Model Context Protocol adoption" → "mcp adoption"
    "MCP servers" → "mcp servers"
    Both produce keyword {mcp} so they cluster together.
    """
    t = text.lower()
    for pattern, canonical in _CONCEPT_PATTERNS:
        t = pattern.sub(canonical, t)
    return t


@dataclass
class TrendCluster:
    sources: list[SearchSource] = field(default_factory=list)
    keywords_set: frozenset[str] = field(default_factory=frozenset)
    stale_count: int = 0  # sources where all year references are stale

    @property
    def canonical_topic(self) -> str:
        """Most descriptive title in the cluster (longest word count)."""
        if not self.sources:
            return ""
        return max(self.sources, key=lambda s: len(s.title.split())).title

    @property
    def aliases(self) -> list[str]:
        """All source titles except the canonical topic."""
        canonical = self.canonical_topic
        return [s.title for s in self.sources if s.title != canonical]

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

    @property
    def weighted_evidence_score(self) -> float:
        """Quality- and freshness-weighted evidence sum with same-domain diminishing returns.

        Each source is scored as quality_weight × freshness_multiplier, sorted
        highest-first so the best source from each domain always gets full weight.
        Subsequent sources from the same domain are halved each time.
        """
        scored = sorted(
            ((s, source_quality_weight(s) * _freshness_multiplier(s)) for s in self.sources),
            key=lambda sw: sw[1],
            reverse=True,
        )
        domain_counts: dict[str, int] = {}
        total = 0.0
        for source, w in scored:
            domain = _url_domain(source.url) or source.url
            n = domain_counts.get(domain, 0)
            total += w * (0.5 ** n)
            domain_counts[domain] = n + 1
        return round(total, 4)

    @property
    def cluster_freshness_score(self) -> float:
        """Average freshness_score across all sources in the cluster."""
        if not self.sources:
            return 0.5
        return round(sum(freshness_score(s) for s in self.sources) / len(self.sources), 4)

    @property
    def unique_domain_count(self) -> int:
        return len({_url_domain(s.url) for s in self.sources if _url_domain(s.url)})


def _is_stale(source: SearchSource) -> bool:
    """Return True when the source only references years older than _STALE_CUTOFF."""
    text = f"{source.title} {source.snippet}"
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return False  # no year signal — assume fresh
    return max(years) <= _STALE_CUTOFF


def _merge_clusters(
    clusters: list[TrendCluster],
    threshold: float,
) -> list[TrendCluster]:
    """
    Post-merge clusters whose expanded keyword sets overlap >= threshold.

    Uses union-find so transitive merges (A≈B, B≈C → all three merge) are handled
    in one pass without repeated scans.
    """
    n = len(clusters)
    if n <= 1:
        return clusters

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if find(i) != find(j):
                shared_concepts = (
                    clusters[i].keywords_set
                    & clusters[j].keywords_set
                    & _SPECIFIC_CONCEPT_TOKENS
                )
                should_merge = (
                    topic_similarity(clusters[i].keywords_set, clusters[j].keywords_set) >= threshold
                    or bool(shared_concepts)
                )
                if should_merge:
                    parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    result: list[TrendCluster] = []
    for indices in groups.values():
        primary = clusters[indices[0]]
        merged = TrendCluster(
            sources=list(primary.sources),
            keywords_set=primary.keywords_set,
            stale_count=primary.stale_count,
        )
        for idx in indices[1:]:
            other = clusters[idx]
            merged.sources.extend(other.sources)
            merged.keywords_set = merged.keywords_set | other.keywords_set
            merged.stale_count += other.stale_count
        result.append(merged)

    return result


def cluster_search_results(
    sources: list[SearchSource],
    threshold: float = _CLUSTER_THRESHOLD,
) -> list[TrendCluster]:
    """
    Group search results into topic clusters by keyword similarity.

    Applies concept normalisation (acronym → canonical token) before extraction
    so "MCP servers" and "Model Context Protocol adoption" share the keyword `mcp`
    and cluster together. Runs a post-merge pass to fix greedy splits.
    """
    clusters: list[TrendCluster] = []

    for source in sources:
        normalised = normalize_for_clustering(f"{source.title} {source.snippet}")
        source_kws = extract_keywords(normalised)
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

    return _merge_clusters(clusters, threshold)


def confidence_for_cluster(cluster: TrendCluster) -> tuple[float, str]:
    """Deterministic confidence from weighted evidence score and source diversity.

    Thresholds:
      High   — weighted_score ≥ 1.8 + unique_domains ≥ 2
               OR weighted_score ≥ 1.0 + source_type_count ≥ 2
      Medium — weighted_score ≥ 1.0 OR unique_domains ≥ 2 OR source_type_count ≥ 2
               (fallback 0.4 when score ≥ 0 but below all Medium conditions)
      Low    — single source, OR all sources stale and score weak

    All-stale clusters are capped at Medium (score 0.35) so stale evidence alone
    cannot reach High, and the numeric score stays below the fresh-evidence floor (0.4).

    Returns (score: float 0–1, label: "High" | "Medium" | "Low")
    """
    if cluster.evidence_count == 1:
        return 0.2, "Low"

    ws = cluster.weighted_evidence_score
    unique_domains = cluster.unique_domain_count
    source_types = len(cluster.source_type_set)
    all_stale = cluster.stale_count == cluster.evidence_count > 0

    if all_stale:
        # Stale-only clusters: cap below fresh-evidence Medium floor (0.4)
        if ws >= 1.0 or source_types >= 2:
            return 0.35, "Medium"
        return 0.2, "Low"

    if (ws >= 1.8 and unique_domains >= 2) or (ws >= 1.0 and source_types >= 2):
        return 0.9, "High"
    if ws >= 1.0 or unique_domains >= 2 or source_types >= 2:
        return 0.6, "Medium"
    return 0.4, "Medium"


def rank_clusters(clusters: list[TrendCluster]) -> list[TrendCluster]:
    """Sort clusters by weighted evidence score desc, then unique domain count desc."""
    return sorted(clusters, key=lambda c: (-c.weighted_evidence_score, -c.unique_domain_count))
