"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, settings_store
from .auth import AuthMiddleware
from .config import get_config
from .db import init_db, session_scope
from .inbox import watcher
from .jobs import handlers  # noqa: F401  (registers job handlers)
from .jobs.runner import runner
from .models import Project
from .tts import init_registry

log = logging.getLogger("audiobook_studio")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "phonemizer", "mobi", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _recover_projects() -> None:
    """Projects left 'rendering' by a crash are re-queued by the job runner;
    make sure their status reflects that."""
    with session_scope() as session:
        for project in session.query(Project).filter(Project.status == "rendering"):
            project.status = "queued"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    if not config.disable_background:
        _recover_projects()
        runner.start({"render": config.render_workers, "general": config.general_workers})
        watcher.start()
    yield
    if not config.disable_background:
        watcher.stop()
        runner.stop()


def create_app() -> FastAPI:
    config = get_config()
    _setup_logging(config.log_level)
    config.ensure_dirs()
    init_db(f"sqlite:///{config.db_path}")
    settings_store.invalidate_cache()
    init_registry(config.models_path, settings_store.current)

    app = FastAPI(
        title="Audiobook Studio",
        version=__version__,
        description="Self-hosted audiobook creation suite – REST API",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(AuthMiddleware)

    from .api import books, collections, jobs, lexicon, projects, system, tts

    for module in (projects, books, collections, jobs, tts, lexicon, system):
        app.include_router(module.router)

    @app.exception_handler(PermissionError)
    async def permission_error(_request: Request, exc: PermissionError):
        return JSONResponse(status_code=500, content={"detail": f"Permission denied: {exc.filename or exc}"})

    _mount_frontend(app, config.frontend_path)
    return app


def _mount_frontend(app: FastAPI, frontend: Path | None) -> None:
    if frontend is None:
        log.warning("Frontend build not found - only the API is served (see /api/docs)")

        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"message": "Audiobook Studio API is running. Build the frontend to use the web UI.",
                                 "docs": "/api/docs"})

        return

    assets = frontend / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = frontend / "index.html"
    root = frontend.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "feeds/")):
            raise HTTPException(404, "Not found")
        candidate = (frontend / full_path).resolve()
        if full_path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
