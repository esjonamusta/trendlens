from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.llm import llm_client
from app.core.logger import get_logger
from app.core.prompts import (
    DISCOVERY_SYSTEM,
    DISCOVERY_USER,
    SUMMARIZE_SYSTEM,
    SUMMARIZE_USER,
    _EXCLUDED_SECTION_TEMPLATE,
)
from app.core.schemas import (
    EvidenceItem,
    ResearchConfig,
    ResearchItem,
    ResearchReport,
    SearchSource,
    SourceDiscovery,
    TrendSummaryList,
    TrendSummaryText,
)
from app.services.normalizer import extract_keywords, make_canonical_id, topic_similarity
from app.services.trend_engine import (
    TrendCluster,
    cluster_search_results,
    confidence_for_cluster,
    rank_clusters,
)
from app.services.web_search import QueryResults
from app.sources.podcasts import fetch_podcast_signals
from app.sources.reddit import fetch_reddit_signals
from app.sources.web import fetch_web_signals

log = get_logger(__name__)

# Extra clusters summarized beyond max_items so the delta engine has a wider
# pool to match against on the next run. Topics that slip from rank 3 to rank 5
# won't show as DISAPPEARED just because they fell out of the display window.
_DELTA_BUFFER = 4


def _deduplicate(results: list[QueryResults]) -> list[QueryResults]:
    seen_urls: set[str] = set()
    out: list[QueryResults] = []
    for qr in results:
        unique = [r for r in qr.results if r.url not in seen_urls]
        seen_urls.update(r.url for r in unique)
        if unique:
            out.append(QueryResults(query=qr.query, results=unique, source=qr.source))
    return out


def _format_clusters_for_llm(clusters: list[TrendCluster]) -> str:
    """Render pre-ranked clusters as a structured block for the summarization prompt."""
    lines: list[str] = []
    for i, cluster in enumerate(clusters, 1):
        _, conf_label = confidence_for_cluster(cluster)
        type_str = ", ".join(sorted(cluster.source_type_set))
        lines.append(
            f"CLUSTER {i} | {conf_label} confidence | "
            f"{cluster.evidence_count} sources ({type_str})"
        )
        lines.append(f'Topic: "{cluster.canonical_topic}"')
        if cluster.aliases:
            lines.append("Related:")
            for alias in cluster.aliases[:5]:
                lines.append(f"  - {alias}")
        lines.append("Evidence:")
        for source in cluster.sources[:8]:
            lines.append(f"  [{source.type}] {source.title} | {source.url}")
            if source.snippet:
                lines.append(f"    {source.snippet[:200]}")
        lines.append("")
    return "\n".join(lines)


class ResearchAgent:
    async def run(
        self,
        config: ResearchConfig,
        excluded_headlines: list[str] | None = None,
        product_context: str = "",
    ) -> ResearchReport:
        log.info(f"ResearchAgent starting | domain='{config.domain}'")

        # ── 1. Source discovery (Haiku — fast/cheap) ──────────────────────────
        discovery = await self._discover_sources(config, product_context)
        log.info(
            f"Sources discovered | podcasts={discovery.podcasts} "
            f"subreddits={discovery.subreddits}"
        )

        # ── 2. Parallel fetch from all source types ───────────────────────────
        podcast_results, reddit_results, web_results = await asyncio.gather(
            fetch_podcast_signals(config, discovery.podcasts),
            fetch_reddit_signals(config, discovery.subreddits),
            fetch_web_signals(config),
        )

        # ── 3. Deduplicate and collect typed SearchSource objects ─────────────
        def _collect(buckets: list, kind: str) -> list[SearchSource]:
            seen: set[str] = set()
            out: list[SearchSource] = []
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

        if not search_sources:
            log.warning("No search results — returning empty report")
            return ResearchReport(config=config, items=[], generated_at="", search_sources=[])

        # ── 4. Cluster search results deterministically — no LLM ─────────────
        clusters = cluster_search_results(search_sources)
        ranked = rank_clusters(clusters)
        log.info(f"Clusters | total={len(ranked)} | domain='{config.domain}'")

        # Deterministically filter clusters that overlap excluded headlines
        if excluded_headlines:
            excluded_kws = [extract_keywords(h) for h in excluded_headlines]
            ranked = [
                c for c in ranked
                if not any(
                    topic_similarity(c.keywords_set, ekws) >= 0.20
                    for ekws in excluded_kws
                )
            ]

        # Canonical IDs for ALL clusters (wider pool for lifecycle tracking)
        all_cluster_ids = [make_canonical_id(c.keywords_set) for c in ranked]

        top = ranked[: config.max_items + _DELTA_BUFFER]
        if not top:
            log.warning("No clusters after exclusion filter")
            return ResearchReport(
                config=config,
                items=[],
                generated_at="",
                search_sources=search_sources,
                raw_cluster_canonical_ids=all_cluster_ids,
            )

        # ── 5. LLM writes text only — URLs and confidence already set ─────────
        summaries = await self._summarize_trends(config, top, excluded_headlines, product_context)
        if len(summaries) < len(top):
            log.warning(
                f"LLM returned {len(summaries)} summaries for {len(top)} clusters — "
                "truncating to matched pairs"
            )

        # ── 6. Combine cluster evidence (grounded) with LLM text ─────────────
        # Grounding is guaranteed by construction: all URLs come from real search results.
        items: list[ResearchItem] = []
        for cluster, summary in zip(top, summaries):
            _, conf_label = confidence_for_cluster(cluster)
            items.append(ResearchItem(
                headline=summary.headline,
                what_happened=summary.what_happened,
                why_it_matters=summary.why_it_matters,
                pm_action=summary.pm_action,
                podcast_evidence=[
                    EvidenceItem(text=s.title, url=s.url)
                    for s in cluster.sources if s.type == "podcast"
                ],
                reddit_evidence=[
                    EvidenceItem(text=s.title, url=s.url)
                    for s in cluster.sources if s.type == "reddit"
                ],
                source_links=[s.url for s in cluster.sources if s.type == "web"],
                confidence=conf_label,
                grounded=True,
                evidence_count=cluster.evidence_count,
                weighted_evidence_score=round(cluster.weighted_evidence_score, 3),
                unique_domain_count=cluster.unique_domain_count,
                freshness_score=round(cluster.cluster_freshness_score, 3),
                # novelty_score / first_seen_at / last_seen_at set by pipeline
            ))

        log.info(f"ResearchAgent done | items={len(items)}")
        return ResearchReport(
            config=config,
            items=items,
            generated_at="",
            search_sources=search_sources,
            raw_cluster_canonical_ids=all_cluster_ids,
        )

    async def _discover_sources(
        self, config: ResearchConfig, product_context: str = ""
    ) -> SourceDiscovery:
        user_prompt = DISCOVERY_USER.format(
            domain=config.domain,
            competitors=", ".join(config.competitors) if config.competitors else "none specified",
            target_users=config.target_users or "not specified",
            product_context=product_context,
        )
        return await llm_client.complete(
            system_prompt=DISCOVERY_SYSTEM,
            user_prompt=user_prompt,
            response_model=SourceDiscovery,
            max_tokens=500,
            model=settings.anthropic_fast_model if settings.llm_provider == "anthropic" else None,
            context_label="discovery",
        )

    async def _summarize_trends(
        self,
        config: ResearchConfig,
        clusters: list[TrendCluster],
        excluded_headlines: list[str] | None = None,
        product_context: str = "",
    ) -> list[TrendSummaryText]:
        cluster_text = _format_clusters_for_llm(clusters)
        excluded_section = ""
        if excluded_headlines:
            formatted = "\n".join(f"- {h}" for h in excluded_headlines)
            excluded_section = _EXCLUDED_SECTION_TEMPLATE.format(headlines=formatted)

        user_prompt = SUMMARIZE_USER.format(
            domain=config.domain,
            competitors=", ".join(config.competitors) if config.competitors else "none",
            target_users=config.target_users or "not specified",
            geographic_market=config.geographic_market or "global",
            product_context=product_context,
            count=len(clusters),
            excluded_section=excluded_section,
            cluster_text=cluster_text,
        )
        result = await llm_client.complete(
            system_prompt=SUMMARIZE_SYSTEM,
            user_prompt=user_prompt,
            response_model=TrendSummaryList,
            max_tokens=max(2000, 400 * len(clusters)),
            temperature=0.2,
            context_label="summarize",
        )
        return result.summaries


research_agent = ResearchAgent()
