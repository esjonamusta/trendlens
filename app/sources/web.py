from __future__ import annotations

from datetime import date

from app.core.schemas import ResearchConfig
from app.services.web_search import QueryResults, web_search_service

_YEAR = date.today().year


def build_web_queries(config: ResearchConfig) -> list[str]:
    d = config.domain
    queries = [
        f"{d} news announcement {_YEAR}",
        f"{d} product launch funding acquisition {_YEAR}",
    ]

    if config.competitors:
        comp = " OR ".join(f'"{c}"' for c in config.competitors[:3])
        queries.append(f"({comp}) announcement update {_YEAR}")

    if config.geographic_market:
        queries.append(f"{d} {config.geographic_market} market {_YEAR}")

    queries.append(f"site:news.ycombinator.com {d}")

    return queries


async def fetch_web_signals(config: ResearchConfig) -> list[QueryResults]:
    if not web_search_service.enabled:
        return []
    queries = build_web_queries(config)
    return await web_search_service.search_many(
        queries,
        max_results_per_query=5,
        days=max(config.time_window_days, 90),
    )
