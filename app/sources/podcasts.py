from __future__ import annotations

from datetime import date

from app.core.schemas import ResearchConfig
from app.services.web_search import QueryResults, web_search_service

_YEAR = date.today().year


def build_podcast_queries(config: ResearchConfig, podcasts: list[str]) -> list[str]:
    queries: list[str] = []

    for podcast in podcasts[:3]:
        queries.append(f'"{podcast}" podcast episode {config.domain} {_YEAR}')

    queries.append(f"{config.domain} podcast episode {_YEAR}")

    if config.competitors:
        comp = " OR ".join(config.competitors[:2])
        queries.append(f"podcast {comp} {config.domain} {_YEAR}")

    return queries


async def fetch_podcast_signals(
    config: ResearchConfig,
    podcasts: list[str],
) -> list[QueryResults]:
    if not web_search_service.enabled:
        return []
    queries = build_podcast_queries(config, podcasts)
    return await web_search_service.search_many(
        queries,
        max_results_per_query=4,
        days=max(config.time_window_days, 90),
    )
