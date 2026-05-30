from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ResearchConfig(BaseModel):
    domain: Annotated[str, Field(min_length=2, max_length=200)]
    competitors: list[str] = []
    target_users: str = ""
    geographic_market: str = ""
    time_window_days: int = Field(default=7, ge=1, le=90)
    max_items: int = Field(default=3, ge=3, le=10)


class EvidenceItem(BaseModel):
    text: Annotated[str, Field(description="Human-readable description of the source.")]
    url: Annotated[str, Field(description="URL from the search data for this source. Empty string if not found.")] = ""


class ResearchItem(BaseModel):
    headline: Annotated[str, Field(description="Short, specific, newsy headline.")]
    what_happened: Annotated[str, Field(description="1-2 sentences of concrete facts.")]
    why_it_matters: Annotated[str, Field(description="1-2 sentences specific to a PM in this space.")]
    podcast_evidence: Annotated[list[EvidenceItem], Field(description="Podcast references with URLs from the search data.")]
    reddit_evidence: Annotated[list[EvidenceItem], Field(description="Reddit signals with reddit.com URLs from the search data.")]
    source_links: Annotated[list[str], Field(description="URLs from search data.")]
    confidence: Annotated[Literal["High", "Medium", "Low"], Field(description="High = 3+ sources, Medium = 2, Low = 1.")]
    pm_action: Annotated[str, Field(description="One sentence starting with a verb — what should the PM do?")]
    grounded: bool = True  # False when no source_links match the actual search result URLs
    evidence_count: int = 0               # raw source count for transparency
    weighted_evidence_score: float = 0.0  # quality-weighted score used for ranking
    unique_domain_count: int = 0          # number of distinct source domains
    freshness_score: float = 0.5          # 0.2 stale → 0.5 neutral → 1.0 current-year
    novelty_score: float = 0.5            # 0.0 exact historical match → 1.0 completely new
    first_seen_at: str = ""               # ISO timestamp when this topic first appeared in history
    last_seen_at: str = ""                # ISO timestamp of the most recent run containing this topic


class ResearchItemsList(BaseModel):
    items: Annotated[list[ResearchItem], Field(min_length=1, max_length=10)]


class SourceDiscovery(BaseModel):
    podcasts: Annotated[list[str], Field(description="Most relevant podcast show names for this domain.", min_length=2)]
    subreddits: Annotated[list[str], Field(description="Most relevant subreddits in r/name format.", min_length=2)]


class SearchSource(BaseModel):
    url: str
    title: str
    type: str  # "reddit" | "podcast" | "web"
    snippet: str = ""
    engagement_score: float | None = None  # 0.0–1.0 when sourced from a real engagement API


class ResearchReport(BaseModel):
    config: ResearchConfig
    items: list[ResearchItem]
    generated_at: str
    search_sources: list[SearchSource] = []          # all sources fed to the LLM before synthesis
    raw_cluster_canonical_ids: list[str] = []        # canonical IDs for ALL clusters (not just top-N)


# ── History + Delta schemas ────────────────────────────────────────────────────

class TopicSnapshot(BaseModel):
    """Normalised representation of one trend item stored per run."""
    rank: int
    headline: str
    keywords: list[str]
    confidence: str
    source_count: int
    sources: list[str]
    pm_action: str
    matched_url_count: int = 0          # URL-verified count: search result URLs that exactly match item evidence
    matched_domains: list[str] = []     # unique domains from URL-verified search results
    llm_reported_source_count: int = 0  # raw count from LLM-reported evidence fields (may be unverified)
    freshness_score: float = 0.5        # average freshness of sources (0.2 stale → 1.0 current-year)
    novelty_score: float = 0.5          # how new this topic is vs history (0.0 repeat → 1.0 novel)
    first_seen_at: str = ""             # ISO timestamp of first appearance in stored history
    last_seen_at: str = ""              # ISO timestamp of most recent run containing this topic
    canonical_topic_id: str = ""        # deterministic MD5 hash of sorted keywords (first 12 chars)
    weighted_evidence_score: float = 0.0  # quality-weighted evidence score for trend tracking


class ScoreBreakdown(BaseModel):
    """Component contributions to trend_delta_score."""
    source_count_contribution: float   # 40% weight
    rank_contribution: float           # 25% weight
    confidence_contribution: float     # 20% weight
    diversity_contribution: float      # 15% weight


class DeltaInsight(BaseModel):
    """Delta observation for a single topic between two runs."""
    classification: str          # NEW THIS RUN | SPIKING | DECLINING | STABLE | WEAK SIGNAL | DISAPPEARED
    topic: str
    previous_rank: int | None = None
    current_rank: int | None = None
    previous_source_count: int | None = None
    current_source_count: int | None = None
    rank_delta: int | None = None
    source_count_delta: int | None = None
    previous_confidence: str | None = None
    current_confidence: str | None = None
    reason: str
    evidence: list[str]
    trend_delta_score: float
    score_breakdown: ScoreBreakdown | None = None


class TopicLifecycle(BaseModel):
    """Lifecycle status for a previous topic that did not appear in the current run."""
    canonical_topic_id: str
    status: str                              # NOT_DETECTED_THIS_RUN | COOLING | DORMANT | DISAPPEARED
    topic_headline: str                      # most recent display headline for this topic
    days_since_last_seen: float = 0.0
    consecutive_missing_runs: int = 0
    last_seen_at: str = ""
    last_weighted_evidence_score: float = 0.0
    rolling_7d_weighted_evidence_score: float = 0.0


class DeltaReport(BaseModel):
    """Full delta between the current run and the selected previous run."""
    compared_to_run_id: str
    compared_to_date: str
    days_apart: float
    comparison_type: str         # "7_day" | "most_recent"
    insights: list[DeltaInsight]
    disappeared: list[str]       # headlines confirmed DISAPPEARED (14+ days, no raw cluster evidence)
    lifecycle: list[TopicLifecycle] = []  # all unmatched previous topics with classified status


class ResearchReportWithDelta(ResearchReport):
    """ResearchReport extended with optional history delta."""
    run_id: str = ""
    delta: DeltaReport | None = None
    is_baseline: bool = False
    delta_unavailable_reason: str = ""  # set when delta is suppressed (e.g. too soon)


class TrendSummaryText(BaseModel):
    """Text-only LLM output for a single trend cluster.

    URLs and confidence labels are set deterministically from the cluster — the LLM
    cannot generate or modify them because they are not fields in this schema.
    """
    headline: Annotated[str, Field(description="Short, specific, newsy headline — max 12 words.")]
    what_happened: Annotated[str, Field(description="1-2 sentences of concrete facts from the evidence provided.")]
    why_it_matters: Annotated[str, Field(description="1-2 sentences on why a PM in this space should care.")]
    pm_action: Annotated[str, Field(description="One sentence starting with a verb — what should the PM do this week?")]


class TrendSummaryList(BaseModel):
    summaries: Annotated[list[TrendSummaryText], Field(min_length=1, max_length=10)]


class FeedbackRequest(BaseModel):
    run_id: str
    domain: str
    item_headline: str
    feedback_type: Literal["incorrect", "helpful"]


class ProductProfile(BaseModel):
    """Persistent PM + product context stored per domain.

    Loaded automatically by the pipeline on every research run so the LLM can
    frame 'why it matters' and 'pm_action' against the actual product reality
    rather than a generic PM in this space.
    """
    domain: str
    product_description: str = ""       # What the product does (1-2 sentences)
    product_stage: str = ""             # "early-stage" | "growth" | "mature" | "enterprise"
    tech_stack: list[str] = []          # ["Python", "React", "AWS"]
    customer_segment: str = ""          # Who buys it, e.g. "enterprise engineering teams"
    user_pain_points: list[str] = []    # Top user complaints, drives pm_action specificity
    pm_role: str = ""                   # e.g. "Platform PM", "Growth PM"
    pm_focus: str = ""                  # Current OKR or strategic theme this quarter
    # These pre-fill ResearchConfig fields when not set in the request
    competitors: list[str] = []
    target_users: str = ""
    geographic_market: str = ""
    created_at: str = ""
    updated_at: str = ""
