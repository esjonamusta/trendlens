"""
APScheduler setup — runs research for every tracked domain every 24 hours.

The scheduler uses AsyncIOScheduler so jobs run on the same event loop as
FastAPI without blocking the server. Each domain is processed sequentially
inside the job to avoid hammering APIs in parallel.
"""
from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logger import get_logger
from app.core.schemas import ResearchConfig
from app.db import tracked_domains as td_db

log = get_logger(__name__)

scheduler = AsyncIOScheduler()


async def run_all_tracked_domains() -> None:
    """Research job: iterate over every tracked domain and run the pipeline."""
    # Import here to avoid circular imports at module load time
    from app.core.pipeline import run_research

    domains = td_db.get_all_domains()
    if not domains:
        log.info("Scheduler tick — no tracked domains")
        return

    log.info(f"Scheduler tick — running {len(domains)} domain(s)")

    for domain in domains:
        now = datetime.now(timezone.utc).isoformat()
        td_db.set_status(domain, "running")
        try:
            config = ResearchConfig(domain=domain)
            await run_research(config, use_cache=False)
            td_db.set_status(domain, "done", last_run_at=datetime.now(timezone.utc).isoformat())
            log.info(f"Scheduler: done | domain='{domain}'")
        except Exception as exc:
            td_db.set_status(domain, "error", last_run_at=now)
            log.error(f"Scheduler: failed | domain='{domain}' error={exc}", exc_info=True)


def start() -> None:
    """Add the daily job and start the scheduler. Called once on app startup."""
    scheduler.add_job(
        run_all_tracked_domains,
        trigger=IntervalTrigger(hours=24),
        id="daily_research",
        replace_existing=True,
        max_instances=1,  # prevent overlapping runs
    )
    scheduler.start()
    log.info("Scheduler started — daily research job registered (every 24 h)")


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")
