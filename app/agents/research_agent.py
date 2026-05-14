from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from app.core.config import settings
from app.core.llm import llm_client
from app.core.logger import get_logger
from app.core.prompts import DISCOVERY_SYSTEM, DISCOVERY_USER, RANKING_SYSTEM, RANKING_USER, _EXCLUDED_SECTION_TEMPLATE
from app.core.schemas import ResearchConfig, ResearchItemsList, ResearchReport, SearchSource, SourceDiscovery
from app.services.web_search import QueryResults
from app.sources.podcasts import fetch_podcast_signals
from app.sources.reddit import fetch_reddit_signals
from app.sources.web import fetch_web_signals

log = get_logger(__name__)

# Extra items fetched beyond max_items so the delta engine has a wider pool to
# match against. Topics that fall from rank 3 to rank 5 won't show as DISAPPEARED.
_DELTA_BUFFER = 4


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _format_results(results: list[QueryResults], label: str) -> str:
    lines = [f"=== {label.upper()} ==="]
    for qr in results:
        if not qr.results:
            continue
        lines.append(f'Query: "{qr.query}"')
        for r in qr.results:
            lines.append(f"  - {r.title} ({r.url})")
            if r.snippet:
                lines.append(f"    {r.snippet.strip()}")
    lines.append("")
    return "\n".join(lines)


def _deduplicate(results: list[QueryResults]) -> list[QueryResults]:
    seen_urls: set[str] = set()
    out: list[QueryResults] = []
    for qr in results:
        unique = [r for r in qr.results if r.url not in seen_urls]
        seen_urls.update(r.url for r in unique)
        if unique:
            out.append(QueryResults(query=qr.query, results=unique, source=qr.source))
    return out


class ResearchAgent:
    async def run(self, config: ResearchConfig, excluded_headlines: list[str] | None = None) -> ResearchReport:
        log.info(f"ResearchAgent starting | domain='{config.domain}'")

        # Step 1: discover relevant sources
        discovery = await self._discover_sources(config)
        log.info(f"Sources discovered | podcasts={discovery.podcasts} subreddits={discovery.subreddits}")

        # Step 2: collect from all sources in parallel
        podcast_results, reddit_results, web_results = await asyncio.gather(
            fetch_podcast_signals(config, discovery.podcasts),
            fetch_reddit_signals(config, discovery.subreddits),
            fetch_web_signals(config),
        )

        # Step 3: deduplicate and format all collected data
        all_results = _deduplicate(podcast_results + reddit_results + web_results)

        def _collect(buckets: list, kind: str) -> list[SearchSource]:
            seen: set[str] = set()
            out = []
            for qr in _deduplicate(buckets):
                for r in qr.results:
                    if r.url not in seen:
                        seen.add(r.url)
                        out.append(SearchSource(
                            url=r.url,
                            title=r.title or r.url,
                            type=kind,
                            snippet=r.snippet or "",
                        ))
            return out

        search_sources = (
            _collect(podcast_results, "podcast")
            + _collect(reddit_results, "reddit")
            + _collect(web_results, "web")
        )
        known_hosts: set[str] = {_host(s.url) for s in search_sources if _host(s.url)}
        search_data = (
            _format_results(podcast_results, "Podcasts")
            + _format_results(reddit_results, "Reddit")
            + _format_results(web_results, "Web / News")
        )

        if not any(qr.results for qr in all_results):
            log.warning("No search results found — falling back to LLM knowledge")
            search_data = f"No live search data available. Use your knowledge of the '{config.domain}' domain."
            search_sources = []
            known_hosts = set()

        # Step 4: rank and summarize — fetch extra items for wider delta matching pool
        fetch_count = config.max_items + _DELTA_BUFFER
        items_list = await self._rank_and_summarize(config, search_data, excluded_headlines, fetch_count)

        # Grounding check: item is grounded if any cited URL's hostname appeared in search results
        for item in items_list.items:
            item.grounded = bool(known_hosts) and any(
                _host(url) in known_hosts for url in item.source_links
            )

        log.info(f"ResearchAgent done | items={len(items_list.items)}")
        return ResearchReport(
            config=config,
            items=items_list.items,
            generated_at="",
            search_sources=search_sources,
        )

    async def _discover_sources(self, config: ResearchConfig) -> SourceDiscovery:
        user_prompt = DISCOVERY_USER.format(
            domain=config.domain,
            competitors=", ".join(config.competitors) if config.competitors else "none specified",
            target_users=config.target_users or "not specified",
        )
        return await llm_client.complete(
            system_prompt=DISCOVERY_SYSTEM,
            user_prompt=user_prompt,
            response_model=SourceDiscovery,
            max_tokens=500,
            model=settings.anthropic_fast_model if settings.llm_provider == "anthropic" else None,
            context_label="discovery",
        )

    async def _rank_and_summarize(
        self,
        config: ResearchConfig,
        search_data: str,
        excluded_headlines: list[str] | None = None,
        fetch_count: int | None = None,
    ) -> ResearchItemsList:
        count = fetch_count or config.max_items
        excluded_section = ""
        if excluded_headlines:
            formatted = "\n".join(f"- {h}" for h in excluded_headlines)
            excluded_section = _EXCLUDED_SECTION_TEMPLATE.format(headlines=formatted)

        user_prompt = RANKING_USER.format(
            domain=config.domain,
            competitors=", ".join(config.competitors) if config.competitors else "none",
            target_users=config.target_users or "not specified",
            geographic_market=config.geographic_market or "global",
            time_window_days=config.time_window_days,
            max_items=count,
            search_data=search_data,
            excluded_section=excluded_section,
        )
        return await llm_client.complete(
            system_prompt=RANKING_SYSTEM,
            user_prompt=user_prompt,
            response_model=ResearchItemsList,
            max_tokens=max(4000, 1500 * count),
            temperature=0.3,
            context_label="ranking",
        )


research_agent = ResearchAgent()
