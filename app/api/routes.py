from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from fastapi import BackgroundTasks

from app.core.logger import get_logger
from app.core.pipeline import run_research
from app.core.schemas import (
    AddDomainRequest,
    FeedbackRequest,
    ProductProfile,
    ResearchConfig,
    ResearchReportWithDelta,
    TrackedDomain,
    TrendFeedbackRequest,
)
from app.db import history as history_db
from app.db import tracked_domains as td_db
from app.services.report import to_markdown

log = get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/research", response_model=ResearchReportWithDelta)
async def research(
    body: ResearchConfig,
    cache: bool = Query(True),
) -> ResearchReportWithDelta:
    try:
        return await run_research(config=body, use_cache=cache)
    except Exception as exc:
        log.error(f"Research failed for domain='{body.domain}': {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/research/markdown", response_class=PlainTextResponse)
async def research_markdown(
    body: ResearchConfig,
    cache: bool = Query(True),
) -> str:
    try:
        report = await run_research(config=body, use_cache=cache)
        return to_markdown(report)
    except Exception as exc:
        log.error(f"Markdown export failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/feedback", status_code=204)
async def submit_feedback(body: FeedbackRequest) -> None:
    try:
        await asyncio.to_thread(
            history_db.save_feedback,
            body.run_id,
            body.domain,
            body.item_headline,
            body.feedback_type,
        )
    except Exception as exc:
        log.error(f"Feedback save failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/profile/{domain}", response_model=ProductProfile)
async def get_profile(domain: str) -> ProductProfile:
    """Return the stored product profile for a domain, or 404 if none exists."""
    data = await asyncio.to_thread(history_db.get_profile, domain)
    if data is None:
        raise HTTPException(status_code=404, detail="No profile found for this domain")
    return ProductProfile(**data)


@router.put("/profile/{domain}", response_model=ProductProfile)
async def upsert_profile(domain: str, body: ProductProfile) -> ProductProfile:
    """Create or update the product profile for a domain."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    data = body.model_dump()
    data["domain"] = domain.strip().lower()
    data["updated_at"] = now
    if not data.get("created_at"):
        data["created_at"] = now
    try:
        await asyncio.to_thread(history_db.upsert_profile, domain, data)
    except Exception as exc:
        log.error(f"Profile save failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ProductProfile(**data)


@router.post("/domains", response_model=TrackedDomain, status_code=201)
async def add_domain(body: AddDomainRequest) -> TrackedDomain:
    """Add a domain to the auto-research watch list."""
    try:
        row = await asyncio.to_thread(td_db.add_domain, body.domain)
    except Exception as exc:
        log.error(f"Add domain failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return TrackedDomain(**row)


@router.get("/domains", response_model=list[TrackedDomain])
async def list_domains() -> list[TrackedDomain]:
    """Return all tracked domains."""
    rows = await asyncio.to_thread(td_db.list_domains)
    return [TrackedDomain(**r) for r in rows]


@router.post("/domains/run-now", status_code=202)
async def run_now(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Manually trigger a research run for all tracked domains (async, fires in background)."""
    from app.scheduler import run_all_tracked_domains
    background_tasks.add_task(run_all_tracked_domains)
    return {"status": "triggered"}


@router.get("/history/{domain}")
async def get_history(
    domain: str,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    """Return recent snapshot summaries for a domain (most recent first)."""
    try:
        snapshots = await asyncio.to_thread(history_db.list_snapshots, domain, limit)
        return [
            {
                "run_id": s.run_id,
                "domain": s.domain,
                "created_at": s.created_at,
                "topics": s.topics,
            }
            for s in snapshots
        ]
    except Exception as exc:
        log.error(f"History lookup failed for domain='{domain}': {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/history/{domain}/timeline")
async def get_timeline(
    domain: str,
    days: int = Query(default=30, ge=1, le=90),
) -> dict:
    """Return per-topic scores over time for the trend explorer chart."""
    try:
        snapshots = await asyncio.to_thread(history_db.get_timeline, domain, days)
        return {"domain": domain, "snapshots": snapshots}
    except Exception as exc:
        log.error(f"Timeline lookup failed for domain='{domain}': {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/trend-feedback", status_code=204)
async def submit_trend_feedback(body: TrendFeedbackRequest) -> None:
    """Save relevant/not_relevant feedback for a trend to improve personalization."""
    try:
        await asyncio.to_thread(
            history_db.save_trend_feedback,
            body.domain,
            body.item_headline,
            body.feedback_type,
        )
    except Exception as exc:
        log.error(f"Trend feedback failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
