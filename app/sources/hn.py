"""
Hacker News source via the Algolia Search API.

No API key required. Returns stories with engagement scores derived from
upvote counts so the trend engine can weight high-signal HN discussions higher.

API docs: https://hn.algolia.com/api
"""
from __future__ import annotations

import httpx

from app.core.logger import get_logger
from app.core.schemas import ResearchConfig
from app.services.web_search import QueryResults, SearchResult

log = get_logger(__name__)

_HN_URL = "https://hn.algolia.com/api/v1/search"
_TIMEOUT = httpx.Timeout(15.0)
# Stories need at least this many points to be included — filters out low-quality noise
_MIN_POINTS = 10


def _engagement(points: int) -> float:
    """Map HN upvote count to a 0.0–1.0 engagement score. 500+ points → 1.0."""
    return min(points / 500, 1.0)


def _snippet(hit: dict) -> str:
    parts: list[str] = []
    points = hit.get("points") or 0
    comments = hit.get("num_comments") or 0
    if points:
        parts.append(f"{points} points")
    if comments:
        parts.append(f"{comments} comments")
    story_text = (hit.get("story_text") or "")[:200].strip()
    if story_text:
        parts.append(story_text)
    return " · ".join(parts)


async def fetch_hn_signals(config: ResearchConfig) -> list[QueryResults]:
    """Fetch HN stories about the domain. Falls back to empty results on any error."""
    query = config.domain
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"points>{_MIN_POINTS}",
        "hitsPerPage": 10,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_HN_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning(f"HN Algolia fetch failed for '{query}': {exc}")
        return []

    results: list[SearchResult] = []
    for hit in data.get("hits", []):
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        title = hit.get("title", "").strip()
        if not title or not url:
            continue
        points = hit.get("points") or 0
        results.append(SearchResult(
            title=title,
            url=url,
            snippet=_snippet(hit),
            engagement_score=_engagement(points),
        ))

    log.debug(f"HN '{query}' → {len(results)} stories")
    return [QueryResults(query=query, results=results, source="hn_algolia")]
