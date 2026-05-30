"""
Reddit source.

Primary: Reddit OAuth API (direct subreddit search with upvote/comment counts).
Fallback: web search via Tavily/Brave (used when OAuth credentials are absent).

OAuth setup: create a "script" app at https://www.reddit.com/prefs/apps
then set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env.
"""
from __future__ import annotations

from datetime import date

import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.core.schemas import ResearchConfig
from app.services.web_search import QueryResults, SearchResult, web_search_service

log = get_logger(__name__)

_YEAR = date.today().year
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = "https://oauth.reddit.com/search"
_USER_AGENT = "TrendLens/1.0 (research aggregator)"
_TIMEOUT = httpx.Timeout(15.0)


def _reddit_engagement(score: int) -> float:
    """1 000+ upvotes → 1.0."""
    return min(max(score, 0) / 1_000, 1.0)


async def _get_access_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        _TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(settings.reddit_client_id, settings.reddit_client_secret),
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def _fetch_subreddit_oauth(
    client: httpx.AsyncClient,
    token: str,
    subreddit: str,
    query: str,
) -> list[SearchResult]:
    """Search one subreddit via the OAuth API."""
    sub = subreddit.lstrip("r/")
    try:
        resp = await client.get(
            f"https://oauth.reddit.com/r/{sub}/search",
            params={"q": query, "sort": "top", "t": "month", "limit": 5, "restrict_sr": 1},
            headers={"Authorization": f"bearer {token}", "User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        children = resp.json().get("data", {}).get("children", [])
    except Exception as exc:
        log.warning(f"Reddit OAuth search failed for r/{sub}: {exc}")
        return []

    results: list[SearchResult] = []
    for child in children:
        post = child.get("data", {})
        url = post.get("url") or f"https://reddit.com{post.get('permalink', '')}"
        title = (post.get("title") or "").strip()
        score = post.get("score", 0)
        comments = post.get("num_comments", 0)
        selftext = (post.get("selftext") or "")[:200].strip()
        if not title:
            continue
        snippet_parts = [f"{score} upvotes, {comments} comments"]
        if selftext:
            snippet_parts.append(selftext)
        results.append(SearchResult(
            title=title,
            url=url,
            snippet=" · ".join(snippet_parts),
            engagement_score=_reddit_engagement(score),
        ))
    return results


async def _fetch_reddit_oauth(
    config: ResearchConfig,
    subreddits: list[str],
) -> list[QueryResults]:
    """Fetch Reddit signals using the OAuth API. Returns empty list on auth failure."""
    out: list[QueryResults] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            token = await _get_access_token(client)
            for sub in subreddits[:3]:
                results = await _fetch_subreddit_oauth(client, token, sub, config.domain)
                if results:
                    out.append(QueryResults(
                        query=f"r/{sub.lstrip('r/')} {config.domain}",
                        results=results,
                        source="reddit_oauth",
                    ))
    except Exception as exc:
        log.warning(f"Reddit OAuth failed — falling back to web search: {exc}")
        return []

    log.debug(f"Reddit OAuth '{config.domain}' → {sum(len(q.results) for q in out)} posts")
    return out


# ── Web-search fallback (used when OAuth creds are absent) ────────────────────

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
    """Fetch Reddit signals.

    Uses Reddit OAuth API when REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set,
    otherwise falls back to web search (Tavily/Brave) for Reddit results.
    """
    if settings.reddit_client_id and settings.reddit_client_secret:
        results = await _fetch_reddit_oauth(config, subreddits)
        if results:
            return results
        # OAuth returned empty (auth failure) — fall through to web search

    if not web_search_service.enabled:
        return []
    queries = build_reddit_queries(config, subreddits)
    return await web_search_service.search_many(
        queries,
        max_results_per_query=5,
        days=max(config.time_window_days, 90),
    )
