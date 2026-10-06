"""Settings, statistics, system information, metadata lookup, auth and feeds."""

from __future__ import annotations

import os
import platform
import secrets
import shutil
import subprocess
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import __version__, auth, settings_store
from ..config import get_config
from ..db import get_db
from ..inbox import watcher
from ..library import feeds
from ..library import metadata as metadata_lookup
from ..models import Book, Chapter, Job, Project, utcnow
from ..schemas import LoginRequest, PasswordChange
from ..settings_store import SECRET_FIELDS, AppSettings
from .common import book_out, get_or_404, project_summary

router = APIRouter(tags=["system"])


# ------------------------------------------------------------------- health / auth
@router.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/api/auth/status")
def auth_status(request: Request):
    enabled = auth.auth_enabled()
    authenticated = (not enabled) or auth.valid_session(request.cookies.get(auth.COOKIE))
    return {"enabled": enabled, "authenticated": authenticated, "managed_by_env": bool(get_config().password)}


@router.post("/api/auth/login")
def login(body: LoginRequest, response: Response, request: Request):
    if not auth.auth_enabled():
        return {"ok": True}
    if not auth.check_password(body.password):
        raise HTTPException(401, "Wrong password")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE, auth.create_session_token(), max_age=auth.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=secure)
    return {"ok": True}


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


# ------------------------------------------------------------------- settings
def _public_settings(settings: AppSettings) -> dict:
    data = settings.model_dump(exclude=SECRET_FIELDS)
    data["password_set"] = bool(settings.password_hash or get_config().password)
    data["password_managed_by_env"] = bool(get_config().password)
    data["openai_api_key_set"] = bool(settings.openai_api_key)
    return data


@router.get("/api/settings")
def get_settings(session: Session = Depends(get_db)):
    return _public_settings(settings_store.get_settings(session))


@router.patch("/api/settings")
def update_settings(changes: dict, session: Session = Depends(get_db)):
    changes = {k: v for k, v in changes.items() if k not in ("password_hash", "feed_token")}
    if changes.get("openai_api_key") in (None, "") and "openai_api_key" in changes and not changes.get("clear_openai_api_key"):
        changes.pop("openai_api_key")
    if changes.pop("clear_openai_api_key", False):
        changes["openai_api_key"] = ""
    try:
        settings = settings_store.update_settings(session, changes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _public_settings(settings)


@router.post("/api/settings/password")
def change_password(body: PasswordChange, session: Session = Depends(get_db)):
    if get_config().password:
        raise HTTPException(400, "The password is set by the STUDIO_PASSWORD environment variable.")
    settings = settings_store.get_settings(session)
    if settings.password_hash and not auth.verify_hash(body.current_password, settings.password_hash):
        raise HTTPException(403, "The current password is wrong.")
    new_hash = auth.hash_password(body.new_password) if body.new_password else ""
    settings_store.update_settings(session, {"password_hash": new_hash})
    return {"ok": True, "enabled": bool(new_hash)}


@router.post("/api/settings/feed-token")
def regenerate_feed_token(session: Session = Depends(get_db)):
    settings = settings_store.update_settings(session, {"feed_token": secrets.token_urlsafe(24)})
    return {"feed_token": settings.feed_token}


# ------------------------------------------------------------------- system & stats
def _ffmpeg_version() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        return "not installed"
    try:
        out = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=10).stdout
        return out.split("\n", 1)[0].replace("ffmpeg version ", "").split(" ")[0]
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _disk(path) -> dict:
    try:
        usage = shutil.disk_usage(path)
        return {"path": str(path), "total": usage.total, "free": usage.free, "used": usage.used}
    except OSError:
        return {"path": str(path), "total": 0, "free": 0, "used": 0}


@router.get("/api/system")
def system_info():
    config = get_config()
    try:
        import pymupdf

        tess = bool(pymupdf.get_tessdata())
    except Exception:  # noqa: BLE001
        tess = False
    return {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ffmpeg": _ffmpeg_version(),
        "ocr_available": tess,
        "paths": {
            "data": str(config.data_dir),
            "library": str(config.library_path),
            "inbox": str(config.inbox_path),
            "models": str(config.models_path),
        },
        "disk": {"data": _disk(config.data_dir), "library": _disk(config.library_path)},
        "inbox_last_scan": watcher.last_scan,
        "render_workers": config.render_workers,
    }


@router.get("/api/stats")
def stats(session: Session = Depends(get_db)):
    books = session.query(Book).all()
    projects = session.query(Project).all()
    week_ago = utcnow() - timedelta(days=7)
    genres: Counter = Counter()
    authors: Counter = Counter()
    languages: Counter = Counter()
    for book in books:
        for genre in (book.genre or "Unsorted").split(","):
            genres[genre.strip() or "Unsorted"] += 1
        authors[book.author or "Unknown"] += 1
        languages[book.language or "?"] += 1
    rendered_words = session.query(func.coalesce(func.sum(Chapter.word_count), 0)).filter(
        Chapter.audio_hash.isnot(None)).scalar() or 0
    job_counts = dict(session.query(Job.status, func.count(Job.id)).group_by(Job.status).all())
    in_progress = sorted(
        (b for b in books if b.progress > 0 and not b.finished),
        key=lambda b: b.last_played_at or b.added_at,
        reverse=True,
    )[:8]
    recent = sorted(books, key=lambda b: b.added_at, reverse=True)[:12]
    recent_projects = sorted(projects, key=lambda p: p.updated_at, reverse=True)[:6]
    return {
        "books": len(books),
        "total_duration": round(sum(b.duration for b in books), 1),
        "total_size": sum(b.size for b in books),
        "authors": len({b.author for b in books if b.author}),
        "series": len({b.series for b in books if b.series}),
        "finished": sum(1 for b in books if b.finished),
        "listened_seconds": round(sum(b.duration if b.finished else b.progress for b in books), 1),
        "added_this_week": sum(1 for b in books if b.added_at >= week_ago),
        "projects": len(projects),
        "projects_by_status": dict(Counter(p.status for p in projects)),
        "rendered_words": int(rendered_words),
        "jobs": job_counts,
        "top_genres": [{"name": k, "count": v} for k, v in genres.most_common(8)],
        "top_authors": [{"name": k, "count": v} for k, v in authors.most_common(8)],
        "languages": [{"name": k, "count": v} for k, v in languages.most_common()],
        "continue_listening": [book_out(b) for b in in_progress],
        "recently_added": [book_out(b) for b in recent],
        "recent_projects": [project_summary(p) for p in recent_projects],
    }


# ------------------------------------------------------------------- metadata
@router.get("/api/metadata/search")
def metadata_search(title: str = "", author: str = "", isbn: str = ""):
    if not settings_store.current().online_metadata:
        raise HTTPException(400, "Online metadata lookup is disabled in Settings.")
    return metadata_lookup.search(title, author, isbn)


@router.get("/api/metadata/description")
def metadata_description(source: str, source_id: str):
    if source != "openlibrary":
        return {"description": ""}
    try:
        return {"description": metadata_lookup.open_library_description(source_id)}
    except Exception:  # noqa: BLE001
        return {"description": ""}


# ------------------------------------------------------------------- feeds
def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


@router.get("/api/feeds")
def feed_links(request: Request, session: Session = Depends(get_db)):
    token = settings_store.current().feed_token if auth.auth_enabled() else ""
    base = _base_url(request)
    query = f"?token={token}" if token else ""
    return {"library": f"{base}/feeds/library.xml{query}", "book_template": f"{base}/feeds/books/{{id}}.xml{query}",
            "token_required": bool(token)}


@router.get("/feeds/library.xml")
def library_feed(request: Request, session: Session = Depends(get_db)):
    token = settings_store.current().feed_token if auth.auth_enabled() else ""
    books = session.query(Book).filter(Book.missing.is_(False)).order_by(Book.added_at.desc()).all()
    xml = feeds.library_feed(books, _base_url(request), token)
    return RawResponse(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/feeds/books/{book_id}.xml")
def book_feed(book_id: int, request: Request, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    token = settings_store.current().feed_token if auth.auth_enabled() else ""
    xml = feeds.book_feed(book, _base_url(request), token)
    return RawResponse(content=xml, media_type="application/rss+xml; charset=utf-8")
