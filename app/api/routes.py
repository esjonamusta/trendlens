from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Cookie, Form, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse

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
async def submit_feedback(body: FeedbackRequest, tl_user_id: str | None = Cookie(default=None)) -> None:
    user_id = int(tl_user_id) if tl_user_id and tl_user_id.isdigit() else None
    try:
        await asyncio.to_thread(
            history_db.save_feedback,
            body.run_id,
            body.domain,
            body.item_headline,
            body.feedback_type,
            user_id,
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
async def add_domain(
    body: AddDomainRequest,
    tl_user_id: str | None = Cookie(default=None),
) -> TrackedDomain:
    """Add a domain to the auto-research watch list for the current user."""
    user_id = int(tl_user_id) if tl_user_id and tl_user_id.isdigit() else None
    try:
        row = await asyncio.to_thread(td_db.add_domain, body.domain, user_id)
    except Exception as exc:
        log.error(f"Add domain failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return TrackedDomain(**row)


@router.get("/domains", response_model=list[TrackedDomain])
async def list_domains(tl_user_id: str | None = Cookie(default=None)) -> list[TrackedDomain]:
    """Return tracked domains for the current user."""
    user_id = int(tl_user_id) if tl_user_id and tl_user_id.isdigit() else None
    rows = await asyncio.to_thread(td_db.list_domains, user_id)
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
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> dict:
    """Return per-topic scores over time for the trend explorer chart."""
    if (start_date is None) != (end_date is None):
        raise HTTPException(status_code=400, detail="Provide both start_date and end_date.")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be before or equal to end_date.")
    try:
        snapshots = await asyncio.to_thread(
            history_db.get_timeline,
            domain,
            days,
            start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None,
        )
        return {"domain": domain, "snapshots": snapshots}
    except Exception as exc:
        log.error(f"Timeline lookup failed for domain='{domain}': {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/login", include_in_schema=False)
async def login(
    email: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    user = await asyncio.to_thread(history_db.verify_user, email.strip().lower(), password_hash)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    response = RedirectResponse("/app", status_code=303)
    response.set_cookie("tl_user_id", str(user["id"]), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    response.set_cookie("tl_user_name", user["first_name"], max_age=60 * 60 * 24 * 30, samesite="lax")
    return response


@router.post("/signup", include_in_schema=False)
async def signup(
    background_tasks: BackgroundTasks,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    product_type: str = Form(""),
    target_users: str = Form(""),
    business_model: str = Form(""),
    product_goal: str = Form(""),
    keywords: str = Form(""),
    digest_frequency: str = Form("weekly"),
) -> RedirectResponse:
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    digest_value = digest_frequency if digest_frequency in {"daily", "weekly", "monthly", "off"} else "weekly"

    user_data = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "product_type": product_type,
        "target_users": target_users,
        "business_model": business_model,
        "product_goal": product_goal,
        "keywords": json.dumps(keyword_list),
        "digest_frequency": digest_value,
    }

    try:
        await asyncio.to_thread(history_db.create_user, user_data)
    except ValueError:
        raise HTTPException(status_code=400, detail="Email already registered.")

    new_user = await asyncio.to_thread(history_db.get_user_by_email, user_data["email"])
    new_user_id = new_user["id"] if new_user else None

    for keyword in keyword_list:
        try:
            await asyncio.to_thread(td_db.add_domain, keyword, new_user_id)
        except Exception:
            pass  # domain already tracked — fine

    # Kick off research for each keyword in the background so results are
    # ready (or running) by the time the user lands on /app
    async def _run_research_for_keywords(domains: list[str], users: str, goal: str) -> None:
        for domain in domains:
            try:
                config = ResearchConfig(
                    domain=domain,
                    target_users=users,
                    time_window_days=7,
                )
                await run_research(config, use_cache=False)
                log.info(f"Signup research complete | domain='{domain}'")
            except Exception as exc:
                log.error(f"Signup research failed | domain='{domain}': {exc}")

    if keyword_list:
        background_tasks.add_task(_run_research_for_keywords, keyword_list, target_users, product_goal)

    # Redirect to /app?new=1 so the Explorer knows to show a loading state
    response = RedirectResponse("/app?new=1", status_code=303)
    response.set_cookie("tl_user_id", str(new_user_id), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    response.set_cookie("tl_user_name", user_data["first_name"], max_age=60 * 60 * 24 * 30, samesite="lax")
    return response


@router.post("/trend-feedback", status_code=204)
async def submit_trend_feedback(
    body: TrendFeedbackRequest,
    background_tasks: BackgroundTasks,
    tl_user_id: str | None = Cookie(default=None),
) -> None:
    """Save relevant/not_relevant feedback. Thumbs-down also excludes the headline
    from future runs and triggers a background rerun for the domain."""
    user_id = int(tl_user_id) if tl_user_id and tl_user_id.isdigit() else None
    try:
        await asyncio.to_thread(
            history_db.save_trend_feedback,
            body.domain,
            body.item_headline,
            body.feedback_type,
            user_id,
        )
        if body.feedback_type == "not_relevant":
            await asyncio.to_thread(
                history_db.save_feedback, "", body.domain, body.item_headline, "incorrect", user_id,
            )
            background_tasks.add_task(_rerun_domain, body.domain)
    except Exception as exc:
        log.error(f"Trend feedback failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _rerun_domain(domain: str) -> None:
    """Background rerun after thumbs-down so fresh results replace the disliked trend."""
    try:
        config = ResearchConfig(domain=domain, time_window_days=7)
        await run_research(config, use_cache=False)
        log.info(f"Rerun complete after thumbs-down | domain='{domain}'")
    except Exception as exc:
        log.error(f"Rerun failed | domain='{domain}': {exc}")


@router.get("/me")
async def get_me(tl_user_id: str | None = Cookie(default=None)) -> dict:
    """Return the current user's profile data."""
    if not tl_user_id or not tl_user_id.isdigit():
        raise HTTPException(status_code=401, detail="Not logged in.")
    user = await asyncio.to_thread(history_db.get_user_by_id, int(tl_user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.pop("password_hash", None)
    return user


@router.put("/me")
async def update_me(body: dict, tl_user_id: str | None = Cookie(default=None)) -> dict:
    """Update the current user's editable profile fields."""
    if not tl_user_id or not tl_user_id.isdigit():
        raise HTTPException(status_code=401, detail="Not logged in.")
    try:
        await asyncio.to_thread(history_db.update_user, int(tl_user_id), body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    user = await asyncio.to_thread(history_db.get_user_by_id, int(tl_user_id))
    user.pop("password_hash", None)
    return user


@router.get("/me/feedback")
async def get_my_feedback(tl_user_id: str | None = Cookie(default=None)) -> list[dict]:
    """Return all thumbs up/down given by the currently logged-in user."""
    if not tl_user_id or not tl_user_id.isdigit():
        raise HTTPException(status_code=401, detail="Not logged in.")
    try:
        return await asyncio.to_thread(history_db.get_user_feedback, int(tl_user_id))
    except Exception as exc:
        log.error(f"User feedback fetch failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
