from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.core.logger import get_logger
from app.core.pipeline import run_research
from app.core.schemas import FeedbackRequest, ProductProfile, ResearchConfig, ResearchReportWithDelta
from app.db import history as history_db
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
