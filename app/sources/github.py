"""
GitHub source via the GitHub Search API.

Fetches repositories (ranked by stars) and issues (ranked by reactions)
for the domain. Results carry engagement_score so the trend engine
weights popular repos and highly-reacted issues more heavily.

Without GITHUB_TOKEN: 60 req/hr (unauthenticated).
With GITHUB_TOKEN: 5 000 req/hr.

API docs: https://docs.github.com/en/rest/search/search
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.core.schemas import ResearchConfig
from app.services.web_search import QueryResults, SearchResult

log = get_logger(__name__)

_API = "https://api.github.com"
_TIMEOUT = httpx.Timeout(15.0)
_ACCEPT = "application/vnd.github+json"


def _headers() -> dict[str, str]:
    h = {"Accept": _ACCEPT, "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def _repo_engagement(stars: int) -> float:
    """10 000+ stars → 1.0."""
    return min(stars / 10_000, 1.0)


def _issue_engagement(reactions: int) -> float:
    """100+ reactions → 1.0."""
    return min(reactions / 100, 1.0)


async def _search_repos(query: str, client: httpx.AsyncClient) -> list[SearchResult]:
    try:
        resp = await client.get(
            f"{_API}/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 8},
            headers=_headers(),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception as exc:
        log.warning(f"GitHub repo search failed for '{query}': {exc}")
        return []

    results: list[SearchResult] = []
    for item in items:
        url = item.get("html_url", "")
        name = item.get("full_name", "")
        desc = (item.get("description") or "").strip()
        stars = item.get("stargazers_count", 0)
        lang = item.get("language") or ""
        if not url or not name:
            continue
        snippet_parts = []
        if stars:
            snippet_parts.append(f"⭐ {stars:,}")
        if lang:
            snippet_parts.append(lang)
        if desc:
            snippet_parts.append(desc[:200])
        results.append(SearchResult(
            title=name,
            url=url,
            snippet=" · ".join(snippet_parts),
            engagement_score=_repo_engagement(stars),
        ))
    return results


async def _search_issues(query: str, client: httpx.AsyncClient) -> list[SearchResult]:
    try:
        resp = await client.get(
            f"{_API}/search/issues",
            params={"q": query, "sort": "reactions", "order": "desc", "per_page": 5},
            headers=_headers(),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception as exc:
        log.warning(f"GitHub issue search failed for '{query}': {exc}")
        return []

    results: list[SearchResult] = []
    for item in items:
        url = item.get("html_url", "")
        title = (item.get("title") or "").strip()
        reactions = (item.get("reactions") or {}).get("total_count", 0)
        body_preview = (item.get("body") or "")[:200].strip()
        if not url or not title:
            continue
        snippet_parts = []
        if reactions:
            snippet_parts.append(f"{reactions} reactions")
        if body_preview:
            snippet_parts.append(body_preview)
        results.append(SearchResult(
            title=title,
            url=url,
            snippet=" · ".join(snippet_parts),
            engagement_score=_issue_engagement(reactions),
        ))
    return results


async def fetch_github_signals(config: ResearchConfig) -> list[QueryResults]:
    """Fetch GitHub repos and issues for the domain. Falls back to empty on error."""
    query = config.domain
    out: list[QueryResults] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        repo_results = await _search_repos(query, client)
        issue_results = await _search_issues(query, client)

    if repo_results:
        log.debug(f"GitHub repos '{query}' → {len(repo_results)}")
        out.append(QueryResults(query=f"{query} repos", results=repo_results, source="github"))
    if issue_results:
        log.debug(f"GitHub issues '{query}' → {len(issue_results)}")
        out.append(QueryResults(query=f"{query} issues", results=issue_results, source="github"))

    return out
