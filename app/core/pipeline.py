from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

from app.agents.research_agent import research_agent
from app.core.config import settings
from app.core.logger import get_logger
from app.core.schemas import ResearchConfig, ResearchReportWithDelta, TopicSnapshot
from app.db import history as history_db
from app.services.delta import compute_delta
from app.services.embeddings import build_similarity_matrix
from app.services.normalizer import item_to_topic_snapshot

log = get_logger(__name__)


class _TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[ResearchReportWithDelta, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> ResearchReportWithDelta | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            report, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return report

    async def set(self, key: str, value: ResearchReportWithDelta) -> None:
        async with self._lock:
            self._store[key] = (value, time.monotonic())


_cache = _TTLCache(settings.cache_ttl_seconds)


def _cache_key(config: ResearchConfig) -> str:
    parts = [config.domain.strip().lower()]
    if config.competitors:
        parts.append(",".join(sorted(c.lower() for c in config.competitors)))
    if config.target_users:
        parts.append(config.target_users.lower())
    if config.geographic_market:
        parts.append(config.geographic_market.lower())
    parts.append(str(config.time_window_days))
    parts.append(str(config.max_items))
    return "|".join(parts)


async def run_research(config: ResearchConfig, use_cache: bool = True) -> ResearchReportWithDelta:
    key = _cache_key(config)

    if use_cache and settings.enable_cache:
        cached = await _cache.get(key)
        if cached is not None:
            log.info(f"Cache hit | domain='{config.domain}'")
            return cached

    log.info(f"Pipeline starting | domain='{config.domain}'")
    t_start = time.perf_counter()

    excluded = await asyncio.to_thread(history_db.get_incorrect_headlines, config.domain)
    if excluded:
        log.info(f"Excluding {len(excluded)} previously marked-incorrect item(s) | domain='{config.domain}'")

    report = await research_agent.run(config, excluded_headlines=excluded or None)
    report.generated_at = datetime.now(timezone.utc).isoformat()

    run_id = str(uuid.uuid4())
    domain_key = config.domain.strip().lower()

    # Save ALL fetched items (including delta buffer) so the matching pool is wider
    # and topics that drop a rank or two don't show as DISAPPEARED next run.
    all_topics = [
        item_to_topic_snapshot(item, rank=i + 1, search_sources=report.search_sources)
        for i, item in enumerate(report.items)
    ]

    # Only the items the user actually sees — buffer items must not appear in delta insights.
    display_items = report.items[: config.max_items]
    display_topics = all_topics[: config.max_items]

    # Find the best previous snapshot (prefer ~7 days ago, fall back to most recent)
    previous = await asyncio.to_thread(
        history_db.find_previous_snapshot,
        domain_key,
        run_id,
        7,
        settings.delta_min_gap_hours,
    )

    delta = None
    delta_unavailable_reason = ""

    if previous is None:
        any_snapshots = await asyncio.to_thread(history_db.list_snapshots, domain_key, 1)
        is_baseline = not any_snapshots
        if any_snapshots:
            delta_unavailable_reason = (
                "Run again tomorrow — comparing runs from the same day shows "
                "LLM variance, not real trend movement."
            )
    else:
        is_baseline = False

    if previous is not None:
        prev_topics = [TopicSnapshot(**t) for t in previous.topics]

        sim_matrix = None
        if settings.similarity_method == "embeddings":
            sim_matrix = await build_similarity_matrix(
                [t.headline for t in display_topics],
                [t.headline for t in prev_topics],
            )
            log.info(
                f"Similarity | method={'embeddings' if sim_matrix else 'jaccard (fallback)'} "
                f"domain='{config.domain}'"
            )

        delta = compute_delta(
            current_topics=display_topics,
            previous_topics=prev_topics,
            previous_run_id=previous.run_id,
            previous_created_at=previous.created_at,
            current_created_at=report.generated_at,
            similarity_matrix=sim_matrix,
        )
        log.info(
            f"Delta computed | domain='{config.domain}' "
            f"days_apart={delta.days_apart} type={delta.comparison_type}"
        )

    # Persist all topics (including buffer) for a wider matching pool on future runs
    await asyncio.to_thread(
        history_db.save_snapshot,
        run_id,
        domain_key,
        config.model_dump(),
        report.model_dump(),
        [t.model_dump() for t in all_topics],
        report.generated_at,
    )

    elapsed = time.perf_counter() - t_start
    log.info(
        f"Pipeline complete | domain='{config.domain}' "
        f"elapsed={elapsed:.1f}s baseline={is_baseline}"
    )

    report_dict = report.model_dump()
    report_dict["items"] = [i.model_dump() for i in display_items]
    enriched = ResearchReportWithDelta(
        **report_dict,
        run_id=run_id,
        delta=delta,
        is_baseline=is_baseline,
        delta_unavailable_reason=delta_unavailable_reason,
    )

    if settings.enable_cache:
        await _cache.set(key, enriched)

    return enriched
