"""
Future Trends Intelligence Engine — application entry point.

Usage:
    uvicorn main:app --reload            # development
    python main.py                        # production (via uvicorn.run)
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.core.logger import get_logger
from app.db import history as history_db
from app.db import tracked_domains as td_db
from app import scheduler as sched

log = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "A three-agent AI pipeline that generates PM-grade strategic trend reports "
            "for any technology or business domain. Powered by Anthropic Claude."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            "app/static/landing.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/app", include_in_schema=False)
    async def explorer() -> FileResponse:
        return FileResponse(
            "app/static/index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/landing.html", include_in_schema=False)
    async def landing() -> FileResponse:
        return FileResponse(
            "app/static/landing.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/signup.html", include_in_schema=False)
    async def signup_page() -> FileResponse:
        return FileResponse(
            "app/static/signup.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.on_event("startup")
    async def _startup() -> None:
        history_db.init_db()
        history_db.purge_old_snapshots(settings.history_retention_days)
        td_db.init_db()
        sched.start()
        log.info(
            f"[{settings.app_name}] v{settings.app_version} starting | "
            f"provider={settings.llm_provider} model={settings.active_model}"
        )

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        sched.stop()

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
