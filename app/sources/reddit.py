from __future__ import annotations

from datetime import date

from app.core.schemas import ResearchConfig
from app.services.web_search import QueryResults, web_search_service

_YEAR = date.today().year


def build_reddit_queries(config: ResearchConfig, subreddits: list[str]) -> list[str]:
    queries: list[str] = []

    for sub in subreddits[:3]:
        queries.append(f"site:reddit.com/r/{sub.lstrip('r/')} {config.domain}")

    queries.append(f"site:reddit.com {config.domain} complaints OR switching OR alternatives {_YEAR}")

    if config.target_users:
        queries.append(f"site:reddit.com {config.domain} {config.target_users}")

    return queries


async def fetch_reddit_signals(
    config: ResearchConfig,
    subreddits: list[str],
) -> list[QueryResults]:
    if not web_search_service.enabled:
        return []
    queries = build_reddit_queries(config, subreddits)
    return await web_search_service.search_many(
        queries,
        max_results_per_query=5,
        days=max(config.time_window_days, 90),
    )
