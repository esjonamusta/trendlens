"""
APScheduler setup — runs research for every tracked domain every 24 hours.

The scheduler uses AsyncIOScheduler so jobs run on the same event loop as
FastAPI without blocking the server. Each domain is processed sequentially
inside the job to avoid hammering APIs in parallel.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logger import get_logger
from app.core.schemas import ResearchConfig
from app.db import history as history_db
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


async def run_email_digest(frequency: str) -> None:
    """Send digest emails to all users subscribed at the given frequency."""
    from app.core.pipeline import run_research
    from app.services.email import send_digest

    users = history_db.list_digest_users(frequency)
    if not users:
        log.info(f"Digest tick — no {frequency} users")
        return

    log.info(f"Digest tick — {len(users)} {frequency} user(s)")

    for user in users:
        email = user.get("email", "")
        first_name = user.get("first_name", "there")
        try:
            keywords = json.loads(user.get("keywords") or "[]")
        except Exception:
            keywords = []

        domain = keywords[0] if keywords else ""
        if not domain:
            log.info(f"Digest skip — no domain | email={email!r}")
            continue

        try:
            config = ResearchConfig(domain=domain)
            report = await run_research(config, use_cache=True)
            topics = [t.model_dump() for t in report.items[:3]] if report.items else []
        except Exception as exc:
            log.error(f"Digest research failed | email={email!r} domain={domain!r}: {exc}")
            topics = []

        try:
            await asyncio.to_thread(send_digest, email, first_name, topics, domain, frequency)
            history_db.update_digest_last_sent(user["id"])
        except Exception as exc:
            log.error(f"Digest send failed | email={email!r}: {exc}")


def start() -> None:
    """Add the daily job and start the scheduler. Called once on app startup."""
    scheduler.add_job(
        run_all_tracked_domains,
        trigger=IntervalTrigger(hours=24),
        id="daily_research",
        replace_existing=True,
        max_instances=1,  # prevent overlapping runs
    )
    scheduler.add_job(
        run_email_digest,
        args=["daily"],
        trigger=IntervalTrigger(hours=24),
        id="daily_digest",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_email_digest,
        args=["weekly"],
        trigger=IntervalTrigger(weeks=1),
        id="weekly_digest",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_email_digest,
        args=["monthly"],
        trigger=IntervalTrigger(days=30),
        id="monthly_digest",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    log.info("Scheduler started — research and digest jobs registered")


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")
