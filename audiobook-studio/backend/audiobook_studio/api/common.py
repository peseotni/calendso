"""Shared helpers for API routers: lookups and serialisation."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..audio.render import chapter_fingerprint
from ..models import Book, Chapter, Job, Project
from ..schemas import BookOut, ChapterOut, JobDetail, JobOut, ProjectDetail, ProjectSummary
from ..settings_store import RenderSettings
from ..text.lexicon import Lexicon

T = TypeVar("T")
WORDS_PER_MINUTE = 155


def get_or_404(session: Session, model: type[T], item_id: int, label: str = "Item") -> T:
    item = session.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return item


def estimate_seconds(words: int, speed: float = 1.0) -> float:
    return round(words / (WORDS_PER_MINUTE * max(0.5, speed)) * 60, 1)


def _version(value: datetime | None) -> int:
    return int(value.replace(tzinfo=timezone.utc).timestamp()) if value else 0


def project_cover_url(project: Project) -> str | None:
    if not project.cover_path:
        return None
    return f"/api/projects/{project.id}/cover?v={_version(project.updated_at)}"


def render_settings(project: Project) -> RenderSettings:
    try:
        return RenderSettings.model_validate(project.settings or {})
    except Exception:  # noqa: BLE001 - fall back to defaults on corrupt settings
        return RenderSettings()


def chapter_out(chapter: Chapter, settings: RenderSettings, lexicon: Lexicon | None) -> ChapterOut:
    state = "none"
    if chapter.audio_path:
        if lexicon is not None and chapter.audio_hash == chapter_fingerprint(
            chapter.title, chapter.text, settings, chapter.voice, lexicon
        ):
            state = "ready"
        else:
            state = "stale"
    text = chapter.text.strip()
    first_break = text.find("\n\n")
    preview_source = text[first_break + 2:] if 0 < first_break < 120 else text
    return ChapterOut(
        id=chapter.id,
        position=chapter.position,
        title=chapter.title,
        include=chapter.include,
        kind=chapter.kind,
        word_count=chapter.word_count,
        voice=chapter.voice,
        status=chapter.status,
        error=chapter.error,
        duration=chapter.duration,
        audio_state=state,
        preview=preview_source[:180].replace("\n", " "),
        estimated_seconds=estimate_seconds(chapter.word_count, settings.speed),
    )


def active_jobs_by_project(session: Session) -> dict[int, Job]:
    jobs = (
        session.query(Job)
        .filter(Job.status.in_(("queued", "running")), Job.project_id.isnot(None))
        .order_by(Job.id)
        .all()
    )
    return {job.project_id: job for job in jobs if job.project_id is not None}


def project_summary(project: Project, job: Job | None = None) -> ProjectSummary:
    settings = render_settings(project)
    included = [c for c in project.chapters if c.include]
    words = sum(c.word_count for c in included)
    return ProjectSummary(
        id=project.id,
        title=project.title,
        author=project.author,
        status=project.status,
        error=project.error,
        source_format=project.source_format,
        source_filename=project.source_filename,
        cover_url=project_cover_url(project),
        chapter_count=len(project.chapters),
        included_chapters=len(included),
        word_count=words,
        estimated_seconds=estimate_seconds(words, settings.speed),
        rendered_seconds=round(sum(c.duration for c in included if c.audio_path), 1),
        book_id=project.book_id,
        job_id=job.id if job else None,
        job_progress=job.progress if job else None,
        job_message=job.message if job else None,
        engine=settings.engine,
        voice=settings.voice,
        created_at=project.created_at,
        updated_at=project.updated_at,
        rendered_at=project.rendered_at,
    )


def project_detail(session: Session, project: Project, job: Job | None, lexicon: Lexicon, workspace_bytes: int) -> ProjectDetail:
    settings = render_settings(project)
    summary = project_summary(project, job)
    chapters = [chapter_out(c, settings, lexicon) for c in project.chapters]
    return ProjectDetail(
        **summary.model_dump(),
        subtitle=project.subtitle,
        narrator=project.narrator,
        series=project.series,
        series_index=project.series_index,
        genre=project.genre,
        tags=list(project.tags or []),
        language=project.language,
        publisher=project.publisher,
        year=project.year,
        description=project.description,
        isbn=project.isbn,
        settings=settings.model_dump(),
        warnings=list(project.warnings or []),
        import_options=dict(project.import_options or {}),
        chapters=chapters,
        workspace_bytes=workspace_bytes,
        stale_chapters=sum(1 for c in chapters if c.audio_state == "stale" and c.include),
    )


def book_out(book: Book) -> BookOut:
    version = _version(book.updated_at)
    data: dict[str, Any] = {
        column: getattr(book, column)
        for column in BookOut.model_fields
        if hasattr(book, column) and column not in ("collection_ids", "cover_url", "thumb_url")
    }
    data["files"] = book.files or []
    data["chapters"] = book.chapters or []
    data["tags"] = list(book.tags or [])
    data["collection_ids"] = [c.id for c in book.collections]
    if book.cover_path:
        data["cover_url"] = f"/api/books/{book.id}/cover?v={version}"
        data["thumb_url"] = f"/api/books/{book.id}/cover?size=thumb&v={version}"
    return BookOut.model_validate(data)


def job_out(job: Job, detail: bool = False) -> JobOut:
    data = JobDetail.model_validate(job) if detail else JobOut.model_validate(job)
    if job.started_at and job.status == "running":
        elapsed = time.time() - job.started_at.replace(tzinfo=timezone.utc).timestamp()
        data.elapsed_seconds = round(elapsed, 1)
        if job.progress > 0.02:
            data.eta_seconds = round(elapsed * (1 - job.progress) / job.progress, 1)
    elif job.started_at and job.finished_at:
        data.elapsed_seconds = round((job.finished_at - job.started_at).total_seconds(), 1)
    return data
