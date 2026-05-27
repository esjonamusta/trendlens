"""
Web search service for grounding the Research Agent in live data.

Provider priority:
  1. Tavily (preferred — built for LLM grounding, indexes Reddit/HN deeply)
  2. Brave Search (fallback — broader web coverage)

When neither key is configured, returns empty results and logs a warning.
The Research Agent falls back to pure LLM knowledge gracefully in that case.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class QueryResults:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    source: str = "none"


class WebSearchService:
    """
    Executes multiple search queries in parallel.
    Degrades gracefully to empty results when no API key is present.
    """

    def __init__(self) -> None:
        self._tavily_key = settings.tavily_api_key
        self._brave_key = settings.brave_api_key
        self._timeout = httpx.Timeout(20.0)

    @property
    def enabled(self) -> bool:
        return bool(self._tavily_key or self._brave_key)

    async def search_many(
        self,
        queries: list[str],
        max_results_per_query: int = 5,
        days: int = 90,
    ) -> list[QueryResults]:
        """Run all queries in parallel. Failed queries return empty results."""
        if not self.enabled:
            log.warning(
                "Web search disabled — add TAVILY_API_KEY or BRAVE_API_KEY to .env"
            )
            return []

        tasks = [self._search_one(q, max_results_per_query, days) for q in queries]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[QueryResults] = []
        for query, result in zip(queries, raw):
            if isinstance(result, Exception):
                log.warning(f"Search query failed '{query}': {result}")
                out.append(QueryResults(query=query))
            else:
                out.append(result)  # type: ignore[arg-type]
        return out

    async def _search_one(self, query: str, max_results: int, days: int = 90) -> QueryResults:
        if self._tavily_key:
            try:
                return await self._tavily(query, max_results, days)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (402, 429, 432) and self._brave_key:
                    log.info(f"Tavily credit limit hit — falling back to Brave for '{query}'")
                else:
                    raise
        return await self._brave(query, max_results, days)

    async def _tavily(self, query: str, max_results: int, days: int = 90) -> QueryResults:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                TAVILY_URL,
                json={
                    "api_key": self._tavily_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                    "include_answer": False,
                    "days": days,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", "")[:400],
            )
            for r in data.get("results", [])
            if r.get("title") or r.get("content")
        ]
        log.debug(f"Tavily '{query}' → {len(results)} results")
        return QueryResults(query=query, results=results, source="tavily")

    async def _brave(self, query: str, max_results: int, days: int = 90) -> QueryResults:
        freshness = "pd" if days <= 1 else "pw" if days <= 7 else "pm" if days <= 31 else "py"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                BRAVE_URL,
                params={"q": query, "count": max_results, "freshness": freshness},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self._brave_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        raw = data.get("web", {}).get("results", [])
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", "")[:400],
            )
            for r in raw
            if r.get("title") or r.get("description")
        ]
        log.debug(f"Brave '{query}' → {len(results)} results")
        return QueryResults(query=query, results=results, source="brave")


# ── Query construction ──────────────────────────────────────────────────────────

def build_search_queries(domain: str) -> list[str]:
    """
    Generate five targeted search queries for the domain:
    - 2 broad signal queries (current state, emerging tools)
    - 1 market/business query
    - 1 Reddit practitioner query
    - 1 Hacker News discussion query

    The community queries surface real developer/practitioner sentiment
    that is otherwise invisible to pure LLM synthesis.
    """
    d = domain.strip()
    return [
        f"{d} trends emerging 2025",
        f"{d} new tools frameworks open source",
        f"{d} market signals funding acquisitions 2025",
        f"{d} site:reddit.com",
        f"{d} site:news.ycombinator.com",
    ]


# ── Formatting ──────────────────────────────────────────────────────────────────

def format_search_context(results: list[QueryResults]) -> str:
    """
    Render search results as a structured grounding block to inject into
    the Research Agent's user prompt.

    Returns empty string if there are no usable results — the agent falls
    back to its training knowledge silently.
    """
    populated = [r for r in results if r.results]
    if not populated:
        return ""

    lines: list[str] = [
        "=== LIVE WEB SEARCH GROUNDING ===",
        (
            "The following results were fetched in real-time from the live web. "
            "Prioritise specific facts, product names, and numbers from these sources. "
            "Reddit and Hacker News entries capture raw practitioner sentiment — "
            "treat them as qualitative signal about what developers and operators actually think, "
            "not as authoritative analysis."
        ),
        "",
    ]

    for qr in populated:
        label = _source_label(qr.query)
        lines.append(f'[{label}] Query: "{qr.query}"')
        for i, r in enumerate(qr.results, 1):
            host = _host(r.url)
            lines.append(f"  {i}. {r.title}  ({host})")
            if r.snippet:
                lines.append(f"     {r.snippet.strip()}")
        lines.append("")

    lines.append(
        "Use the above as primary evidence where it is specific and credible. "
        "Fill gaps with your broader training knowledge, but clearly distinguish "
        "observed facts (from search) from inferred patterns (from training)."
    )
    lines.append("=== END WEB SEARCH ===")
    return "\n".join(lines)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.") or url
    except Exception:
        return url


def _source_label(query: str) -> str:
    q = query.lower()
    if "reddit.com" in q:
        return "Reddit"
    if "ycombinator.com" in q or "hacker news" in q:
        return "Hacker News"
    return "Web"


# ── Shared singleton ────────────────────────────────────────────────────────────
web_search_service = WebSearchService()
