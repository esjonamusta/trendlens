from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
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
