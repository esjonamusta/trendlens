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


class ResearchReport(BaseModel):
    config: ResearchConfig
    items: list[ResearchItem]
    generated_at: str
    search_sources: list[SearchSource] = []  # all sources fed to the LLM before synthesis


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
    matched_url_count: int = 0      # real count of search result URLs matched to this topic
    matched_domains: list[str] = [] # unique domains from matched search results


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


class DeltaReport(BaseModel):
    """Full delta between the current run and the selected previous run."""
    compared_to_run_id: str
    compared_to_date: str
    days_apart: float
    comparison_type: str         # "7_day" | "most_recent"
    insights: list[DeltaInsight]
    disappeared: list[str]       # headlines of topics that vanished


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
