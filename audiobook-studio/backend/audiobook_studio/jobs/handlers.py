"""Background job implementations."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from .. import settings_store, studio
from ..audio.assemble import ChapterAudio, assemble
from ..audio.render import chapter_fingerprint, parse_voice_ref, render_chapter
from ..config import get_config
from ..db import session_scope
from ..ingest import IngestError, parse_book
from ..library import service as library
from ..library.importer import import_folder
from ..library.paths import sanitize_component
from ..models import Book, Chapter, Project, utcnow
from ..settings_store import RenderSettings
from ..tts import get_registry
from ..tts.downloads import download_kokoro, download_piper
from .runner import JobCancelled, JobContext, handler

log = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {secs:02d}s"


# --------------------------------------------------------------------------- ingest
@handler("ingest", lane="general")
def ingest(ctx: JobContext) -> dict:
    project_id = ctx.job.project_id
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Project no longer exists")
        path = studio.source_path(project)
        fmt = project.source_format
        options = dict(project.import_options or {})
        project.status = "importing"
    if path is None or not path.exists():
        raise RuntimeError("The source file is missing")

    ctx.progress(0.02, "Reading document")
    try:
        parsed = parse_book(path, fmt, progress=lambda f, m: (ctx.check_cancelled(), ctx.progress(f * 0.95, m)), options=options)
    except JobCancelled:
        _set_project_error(project_id, "Import cancelled")
        raise
    except IngestError as exc:
        _set_project_error(project_id, str(exc))
        raise
    except Exception as exc:  # noqa: BLE001
        _set_project_error(project_id, f"Could not read this file: {exc}")
        raise

    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Project no longer exists")
        studio.apply_parsed(session, project, parsed)
        chapters = len(parsed.chapters)
        words = sum(c.word_count for c in parsed.chapters if c.include)
        for warning in parsed.warnings:
            ctx.log(warning)
        session.flush()
        if options.get("auto_render"):
            session.commit()
            studio.enqueue_render(session, project)
    return {"message": f"Imported {chapters} chapters ({words:,} words)", "chapters": chapters, "words": words}


def _set_project_error(project_id: int | None, message: str) -> None:
    with session_scope() as session:
        project = session.get(Project, project_id) if project_id else None
        if project is not None:
            project.status = "error"
            project.error = message


# --------------------------------------------------------------------------- render
@handler("render", lane="render")
def render(ctx: JobContext) -> dict:
    project_id = ctx.job.project_id
    started = time.monotonic()
    app_settings = settings_store.current()
    with session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise RuntimeError("Project no longer exists")
        project.status = "rendering"
        project.error = ""
        settings = RenderSettings.model_validate(project.settings or {})
        lexicon = studio.lexicon_for(session, project_id)
        chapters = [
            {"id": c.id, "title": c.title, "text": c.text, "voice": c.voice,
             "audio_path": c.audio_path, "audio_hash": c.audio_hash, "duration": c.duration}
            for c in project.chapters
            if c.include and c.text.strip()
        ]
        tags = library.book_tags(project)
        cover = library.read_cover(project.cover_path)
        title = project.title or "Untitled"
    if not chapters:
        _set_project_error(project_id, "No chapters are selected for narration.")
        raise RuntimeError("No chapters are selected for narration.")

    registry = get_registry()
    try:
        engines_needed = {settings.engine}
        if settings.dialogue_enabled and settings.dialogue_voice:
            engines_needed.add(settings.dialogue_engine or settings.engine)
        for chapter in chapters:
            choice = parse_voice_ref(chapter["voice"], settings.engine, registry.engines)
            if choice:
                engines_needed.add(choice.engine)
        for engine_id in engines_needed:
            engine = registry.get(engine_id)
            ready, message = engine.ready()
            if not ready or not engine.enabled():
                raise RuntimeError(f"{engine.name} is not ready: {message or 'disabled'}")

        folder = studio.project_dir(project_id)
        audio_dir = folder / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        weights = {c["id"]: len(c["text"]) + 40 for c in chapters}
        total = sum(weights.values()) or 1
        done = 0
        rendered_count = 0
        rendered: list[ChapterAudio] = []
        data_dir = get_config().data_dir

        for number, chapter in enumerate(chapters, start=1):
            ctx.check_cancelled()
            fingerprint = chapter_fingerprint(chapter["title"], chapter["text"], settings, chapter["voice"], lexicon)
            path = audio_dir / f"chapter_{chapter['id']}.flac"
            if chapter["audio_hash"] == fingerprint and path.exists() and chapter["duration"] > 0:
                done += weights[chapter["id"]]
                rendered.append(ChapterAudio(chapter["title"], path, chapter["duration"]))
                ctx.progress(0.9 * done / total)
                continue

            with session_scope() as session:
                row = session.get(Chapter, chapter["id"])
                if row is not None:
                    row.status = "rendering"
                    row.error = ""
            ctx.progress(0.9 * done / total, f"Narrating chapter {number} of {len(chapters)}: {chapter['title']}")
            chapter_start = done

            def on_progress(weight: int, base=chapter_start, cap=weights[chapter["id"]]) -> None:
                nonlocal done
                done = min(base + cap, done + weight)
                ctx.progress(0.9 * done / total)

            try:
                duration = render_chapter(
                    chapter["title"], chapter["text"], settings, registry, lexicon, path,
                    voice_override=chapter["voice"], on_progress=on_progress,
                    check_cancelled=ctx.check_cancelled, log_warning=ctx.log,
                )
            except JobCancelled:
                with session_scope() as session:
                    row = session.get(Chapter, chapter["id"])
                    if row is not None:
                        row.status = "pending"
                raise
            except Exception as exc:
                with session_scope() as session:
                    row = session.get(Chapter, chapter["id"])
                    if row is not None:
                        row.status = "error"
                        row.error = str(exc)
                raise
            done = chapter_start + weights[chapter["id"]]
            rendered_count += 1
            with session_scope() as session:
                row = session.get(Chapter, chapter["id"])
                if row is not None:
                    row.status = "done"
                    row.audio_path = path.relative_to(data_dir).as_posix() if path.is_relative_to(data_dir) else str(path)
                    row.audio_hash = fingerprint
                    row.duration = round(duration, 3)
            rendered.append(ChapterAudio(chapter["title"], path, duration))
            ctx.log(f"Chapter {number} “{chapter['title']}” rendered ({_format_duration(duration)})")

        ctx.progress(0.9, "Encoding audiobook")
        output_dir = folder / "output"
        shutil.rmtree(output_dir, ignore_errors=True)
        result = assemble(
            rendered,
            output_dir,
            sanitize_component(title, 100) or "Audiobook",
            settings.output_format,
            tags,
            cover,
            settings.bitrate,
            settings.normalize,
            on_progress=lambda f: ctx.progress(0.9 + 0.09 * f),
            check_cancelled=ctx.check_cancelled,
        )
        ctx.progress(0.99, "Adding to library")
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise RuntimeError("Project no longer exists")
            book = library.publish_render(session, project, result, app_settings.library_template, app_settings.write_sidecars)
            project.book_id = book.id
            project.status = "done"
            project.rendered_at = utcnow()
            project.error = ""
            book_id = book.id
            if not app_settings.keep_workspace_audio:
                studio.delete_workspace_audio(session, project)
        shutil.rmtree(output_dir, ignore_errors=True)
    except JobCancelled:
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.status = "ready"
        raise
    except Exception as exc:
        _set_project_error(project_id, str(exc))
        raise

    elapsed = time.monotonic() - started
    return {
        "message": f"Done – {_format_duration(result.duration)} of audio in {_format_duration(elapsed)}",
        "book_id": book_id,
        "duration": result.duration,
        "rendered_chapters": rendered_count,
    }


# --------------------------------------------------------------------------- models
@handler("download_model", lane="general")
def download_model(ctx: JobContext) -> dict:
    engine_id = ctx.payload.get("engine")
    model = ctx.payload.get("model", "")
    registry = get_registry()
    progress = lambda f, m: ctx.progress(f, m)  # noqa: E731
    cancelled = lambda: ctx.cancelled  # noqa: E731
    try:
        if engine_id == "kokoro":
            download_kokoro(get_config().models_path, model, progress, cancelled)
            registry.get("kokoro").unload()
        elif engine_id == "piper":
            download_piper(registry.get("piper"), model, progress, cancelled)
        else:
            raise RuntimeError(f"Engine {engine_id} has no downloadable models")
    except InterruptedError as exc:
        raise JobCancelled() from exc
    return {"message": f"Installed {model}"}


# --------------------------------------------------------------------------- library
@handler("organize", lane="general")
def organize(ctx: JobContext) -> dict:
    template = ctx.payload.get("template") or settings_store.current().library_template
    book_ids = ctx.payload.get("book_ids") or None
    moved = 0
    with session_scope() as session:
        plan = library.organize_plan(session, template, book_ids)
    for index, entry in enumerate(plan):
        ctx.check_cancelled()
        ctx.progress(index / max(1, len(plan)), f"Moving “{entry['title']}”")
        with session_scope() as session:
            book = session.get(Book, entry["book_id"])
            if book is None:
                continue
            target = library.target_dir_for(book, template)
            try:
                if library.move_book(book, target):
                    moved += 1
                    if settings_store.current().write_sidecars:
                        library.write_sidecars(book)
            except OSError as exc:
                ctx.log(f"Could not move “{book.title}”: {exc}")
    return {"message": f"Moved {moved} of {len(plan)} books", "moved": moved}


@handler("scan", lane="general")
def scan(ctx: JobContext) -> dict:
    root = Path(ctx.payload["path"]) if ctx.payload.get("path") else None
    with session_scope() as session:
        result = import_folder(session, root, progress=ctx.progress, check_cancelled=ctx.check_cancelled)
        missing = 0
        for book in session.query(Book).all():
            if library.check_missing(book):
                missing += 1
    message = f"Found {result['found']} new audiobooks, imported {result['added']}"
    if missing:
        message += f"; {missing} books have missing files"
    return {"message": message, **result, "missing": missing}


@handler("retag", lane="general")
def retag(ctx: JobContext) -> dict:
    book_id = ctx.job.book_id or ctx.payload.get("book_id")
    app_settings = settings_store.current()
    with session_scope() as session:
        book = session.get(Book, book_id)
        if book is None:
            raise RuntimeError("Book no longer exists")
        if ctx.payload.get("move") and app_settings.auto_organize:
            ctx.progress(0.1, "Moving files")
            library.move_book(book, library.target_dir_for(book, app_settings.library_template))
        ctx.progress(0.4, "Writing tags")
        count = library.retag_files(book)
        if app_settings.write_sidecars:
            library.write_sidecars(book)
    return {"message": f"Updated tags in {count} file(s)"}
