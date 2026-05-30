from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ── LLM provider ───────────────────────────────────────────────────────────
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ── Model settings ──────────────────────────────────────────────────────────
    # Anthropic defaults
    anthropic_model: str = "claude-sonnet-4-6"
    # Fast model used for the research agent (signal collection, no deep reasoning needed)
    anthropic_fast_model: str = "claude-haiku-4-5-20251001"
    # OpenAI defaults
    openai_model: str = "gpt-4o"

    temperature: float = 0.7
    max_tokens: int = 8192

    # ── Retry / resilience ──────────────────────────────────────────────────────
    max_retries: int = 3
    retry_wait_min: float = 1.0
    retry_wait_max: float = 8.0

    # ── Web search ──────────────────────────────────────────────────────────────
    # Set either key to enable live web grounding in the Research Agent.
    # Tavily is preferred (better Reddit/HN coverage); Brave is the fallback.
    tavily_api_key: str = ""
    brave_api_key: str = ""

    # ── Real engagement APIs (all optional — fall back gracefully when absent) ───
    # GitHub: raises rate limit from 60 to 5 000 req/hr
    github_token: str = ""
    # Reddit OAuth: enables direct subreddit search with upvote/comment counts
    reddit_client_id: str = ""
    reddit_client_secret: str = ""

    # ── In-memory cache ─────────────────────────────────────────────────────────
    enable_cache: bool = True
    cache_ttl_seconds: int = 3600  # 1 hour

    # ── History retention ────────────────────────────────────────────────────────
    history_retention_days: int = 90  # set to 0 to keep forever
    delta_min_gap_hours: int = 24     # ignore snapshots newer than this for delta comparison

    # ── Topic matching ───────────────────────────────────────────────────────────
    # "jaccard"    — fast, no API cost, weaker on synonym-heavy headlines
    # "embeddings" — semantic cosine similarity via OpenAI text-embedding-3-small
    #                requires OPENAI_API_KEY; falls back to jaccard if unavailable
    similarity_method: Literal["jaccard", "embeddings"] = "jaccard"

    # Jaccard threshold below which two topics are considered different
    match_threshold: float = 0.15
    # Minimum keyword overlap count for a search source to be considered weakly matching a topic
    source_keyword_min_overlap: int = 2

    # ── Delta classification thresholds ──────────────────────────────────────────
    # trend_delta_score ≥ this → SPIKING VS LAST RUN
    spike_threshold: float = 0.40
    # trend_delta_score ≤ this → DECLINING
    decline_threshold: float = -0.30
    # Minimum freshness_score required for NEW or SPIKING classification
    freshness_required: float = 0.30

    # ── Topic lifecycle thresholds ────────────────────────────────────────────────
    # Consecutive missed runs before a topic is marked COOLING / DORMANT
    cooling_after_missing_runs: int = 2
    dormant_after_missing_runs: int = 5
    # Days since last seen before a topic is marked DORMANT / DISAPPEARED
    dormant_after_days: int = 7
    disappeared_after_days: int = 14

    # ── Embedding-based matching ──────────────────────────────────────────────────
    # Cosine similarity threshold when similarity_method = "embeddings"
    embed_match_threshold: float = 0.65

    # ── Storage ──────────────────────────────────────────────────────────────────
    history_db_path: str = "history.db"  # override with /data/history.db in Docker

    # ── App meta ────────────────────────────────────────────────────────────────
    app_name: str = "Future Trends Intelligence Engine"
    app_version: str = "1.0.0"
    debug: bool = False

    @property
    def active_model(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        return self.openai_model


settings = Settings()
