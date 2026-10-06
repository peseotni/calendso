"""Studio projects: upload, review chapters, configure voice, render."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from .. import studio
from ..audio.codec import encode_preview
from ..audio.render import preview as render_preview
from ..config import get_config
from ..db import get_db
from ..ingest import FORMAT_LABELS, IngestError, detect_format, supported_extensions
from ..ingest.base import count_words
from ..jobs.runner import runner
from ..library.covers import CoverError, delete_cover, fetch_cover, save_cover
from ..library.service import data_relative
from ..models import METADATA_FIELDS, Book, Chapter, Job, LexiconRule, Project, utcnow
from ..schemas import (
    ChapterBulk,
    ChapterDetail,
    ChapterMerge,
    ChapterReorder,
    ChapterSplit,
    ChapterUpdate,
    CoverUrl,
    JobOut,
    PreviewRequest,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
    ReimportRequest,
    RenderRequest,
    TextProjectCreate,
)
from ..settings_store import RenderSettings
from ..text.cleanup import clean_for_speech
from ..tts import TTSError, get_registry
from .common import (
    active_jobs_by_project,
    chapter_out,
    get_or_404,
    job_out,
    project_detail,
    project_summary,
    render_settings,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _detail(session: Session, project: Project) -> ProjectDetail:
    session.refresh(project)
    job = studio.active_job(session, project.id)
    lexicon = studio.lexicon_for(session, project.id)
    return project_detail(session, project, job, lexicon, studio.workspace_size(project.id))


def _editable(project: Project) -> None:
    if project.status in ("rendering",):
        raise HTTPException(409, "The project is being rendered. Cancel the render to make changes.")


def _renumber(project: Project) -> None:
    for position, chapter in enumerate(sorted(project.chapters, key=lambda c: c.position)):
        chapter.position = position


@router.get("/formats")
def formats() -> dict:
    return {"extensions": supported_extensions(), "labels": FORMAT_LABELS}


@router.get("", response_model=list[ProjectSummary])
def list_projects(session: Session = Depends(get_db)):
    jobs = active_jobs_by_project(session)
    projects = session.query(Project).order_by(Project.updated_at.desc()).all()
    return [project_summary(p, jobs.get(p.id)) for p in projects]


@router.post("/upload", response_model=list[ProjectSummary])
def upload(
    files: list[UploadFile] = File(...),
    auto_render: bool = Form(False),
    ocr: str = Form("auto"),
    session: Session = Depends(get_db),
):
    config = get_config()
    limit = config.max_upload_mb * 1024 * 1024
    created = []
    for upload_file in files:
        name = Path(upload_file.filename or "upload").name
        if detect_format(name) is None:
            raise HTTPException(400, f"Unsupported file type: {name}. Supported: {', '.join(supported_extensions())}")
        tmp_dir = Path(tempfile.mkdtemp(dir=config.tmp_path))
        tmp_path = tmp_dir / name
        size = 0
        try:
            with tmp_path.open("wb") as handle:
                while chunk := upload_file.file.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"{name} is larger than {config.max_upload_mb} MB")
                    handle.write(chunk)
            project = studio.create_project_from_file(
                session, name, tmp_path, {"auto_render": auto_render, "ocr": ocr if ocr in ("auto", "force", "off") else "auto"}
            )
            created.append(project)
        except IngestError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    jobs = active_jobs_by_project(session)
    return [project_summary(p, jobs.get(p.id)) for p in created]


@router.post("/text", response_model=ProjectDetail)
def create_from_text(body: TextProjectCreate, session: Session = Depends(get_db)):
    try:
        project = studio.create_project_from_text(session, body.title, body.text, body.author)
    except IngestError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _detail(session, project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, session: Session = Depends(get_db)):
    return _detail(session, get_or_404(session, Project, project_id, "Project"))


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: int, body: ProjectUpdate, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    changes = body.model_dump(exclude_unset=True)
    new_settings = changes.pop("settings", None)
    for field, value in changes.items():
        if field in METADATA_FIELDS and value is not None:
            setattr(project, field, [t.strip() for t in value if t.strip()] if field == "tags" else value.strip())
    if new_settings is not None:
        _editable(project)
        current = render_settings(project)
        merged = current.model_dump()
        for key, value in new_settings.items():
            if key == "cleanup" and isinstance(value, dict):
                merged["cleanup"] = {**merged["cleanup"], **value}
            elif key in merged:
                merged[key] = value
        try:
            validated = RenderSettings.model_validate(merged)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # Keep the auto-generated narrator name in sync with the voice.
        old_label = studio.voice_label(current.engine, current.voice)
        if (validated.engine, validated.voice) != (current.engine, current.voice) and project.narrator in ("", old_label) and "narrator" not in changes:
            project.narrator = studio.voice_label(validated.engine, validated.voice)
        project.settings = validated.model_dump()
    session.commit()
    return _detail(session, project)


@router.delete("/{project_id}")
def delete_project(project_id: int, delete_book: bool = False, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    job = studio.active_job(session, project.id)
    if job is not None:
        runner.cancel(job.id)
    if delete_book and project.book_id:
        from ..library.service import delete_book_files

        book = session.get(Book, project.book_id)
        if book is not None:
            delete_book_files(book)
            session.delete(book)
    session.query(LexiconRule).filter(LexiconRule.project_id == project.id).delete()
    session.query(Job).filter(Job.project_id == project.id, Job.status.notin_(("queued", "running"))).delete(
        synchronize_session=False
    )
    session.delete(project)
    session.commit()
    shutil.rmtree(studio.project_dir(project_id), ignore_errors=True)
    return {"ok": True}


@router.post("/{project_id}/render", response_model=JobOut)
def start_render(project_id: int, body: RenderRequest | None = None, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    if project.status == "importing":
        raise HTTPException(409, "The document is still being imported.")
    if not any(c.include and c.text.strip() for c in project.chapters):
        raise HTTPException(400, "Select at least one chapter to narrate.")
    job = studio.enqueue_render(session, project, body.chapter_ids if body else None)
    return job_out(job)


@router.post("/{project_id}/cancel")
def cancel_render(project_id: int, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    job = studio.active_job(session, project.id)
    if job is None:
        if project.status in ("queued", "rendering"):
            project.status = "ready"
            session.commit()
        return {"ok": False}
    cancelled = runner.cancel(job.id)
    session.refresh(project)
    if project.status == "queued":
        project.status = "ready"
        session.commit()
    return {"ok": cancelled}


@router.post("/{project_id}/reimport", response_model=JobOut)
def reimport(project_id: int, body: ReimportRequest, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _editable(project)
    if not project.source_path:
        raise HTTPException(400, "This project has no source document.")
    if studio.active_job(session, project.id):
        raise HTTPException(409, "A job is already running for this project.")
    project.import_options = {**(project.import_options or {}), "ocr": body.ocr, "language": body.language, "auto_render": False}
    project.status = "importing"
    session.commit()
    job = runner.enqueue(session, "ingest", f"Re-import “{project.title}”", {}, project_id=project.id)
    return job_out(job)


@router.post("/{project_id}/clean")
def clean_workspace(project_id: int, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _editable(project)
    removed = studio.delete_workspace_audio(session, project)
    session.commit()
    return {"removed": removed}


@router.get("/{project_id}/source")
def download_source(project_id: int, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    path = studio.source_path(project)
    if path is None or not path.exists():
        raise HTTPException(404, "Source file not found")
    return FileResponse(path, filename=project.source_filename or path.name)


@router.get("/{project_id}/export.txt", response_class=PlainTextResponse)
def export_text(project_id: int, cleaned: bool = False, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    settings = render_settings(project)
    lexicon = studio.lexicon_for(session, project.id)
    parts = [project.title, ""]
    for chapter in project.chapters:
        if not chapter.include:
            continue
        text = chapter.text
        if cleaned:
            text = "\n\n".join(
                lexicon.apply(clean_for_speech(p, settings.cleanup, settings.language or project.language or "en"))
                for p in chapter.text.split("\n\n")
            )
        parts += [f"## {chapter.title}", "", text, ""]
    filename = re.sub(r"[^\w.-]+", "_", project.title or "book")[:80] + ".txt"
    return PlainTextResponse("\n".join(parts), headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ------------------------------------------------------------------- cover
@router.get("/{project_id}/cover")
def get_cover(project_id: int, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    if not project.cover_path:
        raise HTTPException(404, "No cover")
    path = get_config().data_dir / project.cover_path
    if not path.exists():
        raise HTTPException(404, "No cover")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


def _store_project_cover(session: Session, project: Project, data: bytes) -> None:
    path = studio.project_dir(project.id) / "cover.jpg"
    try:
        save_cover(data, path)
    except CoverError as exc:
        raise HTTPException(400, str(exc)) from exc
    project.cover_path = data_relative(path)
    project.updated_at = utcnow()  # changes the cover URL so browsers refetch it
    session.commit()


@router.post("/{project_id}/cover", response_model=ProjectDetail)
def upload_cover(project_id: int, file: UploadFile = File(...), session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _store_project_cover(session, project, file.file.read(30 * 1024 * 1024))
    return _detail(session, project)


@router.post("/{project_id}/cover/url", response_model=ProjectDetail)
def cover_from_url(project_id: int, body: CoverUrl, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    try:
        data = fetch_cover(body.url)
    except CoverError as exc:
        raise HTTPException(400, str(exc)) from exc
    _store_project_cover(session, project, data)
    return _detail(session, project)


@router.delete("/{project_id}/cover", response_model=ProjectDetail)
def remove_cover(project_id: int, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    if project.cover_path:
        delete_cover(get_config().data_dir / project.cover_path)
        project.cover_path = None
        project.updated_at = utcnow()
        session.commit()
    return _detail(session, project)


# ------------------------------------------------------------------- preview
def _audio_response(audio, rate) -> Response:
    data, mime = encode_preview(audio, rate)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-store"})


@router.post("/{project_id}/preview")
def preview_project(project_id: int, body: PreviewRequest, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    settings = render_settings(project)
    text = body.text
    title = ""
    if not text:
        included = [c for c in project.chapters if c.include and c.word_count]
        chapter = next((c for c in included if c.word_count > 20), included[0] if included else None)
        if chapter is None:
            raise HTTPException(400, "There is no text to preview.")
        text, title = chapter.text, chapter.title
    try:
        audio, rate = render_preview(text, settings, get_registry(), studio.lexicon_for(session, project.id),
                                     body.max_chars, title)
    except TTSError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _audio_response(audio, rate)


# ------------------------------------------------------------------- chapters
def _chapter(session: Session, project_id: int, chapter_id: int) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None or chapter.project_id != project_id:
        raise HTTPException(404, "Chapter not found")
    return chapter


@router.post("/{project_id}/chapters", response_model=ProjectDetail)
def add_chapter(project_id: int, body: ChapterUpdate, position: int | None = None, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _editable(project)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "The chapter needs some text.")
    index = len(project.chapters) if position is None else max(0, min(position, len(project.chapters)))
    for chapter in project.chapters:
        if chapter.position >= index:
            chapter.position += 1
    session.add(Chapter(project_id=project.id, position=index, title=(body.title or "New chapter").strip(),
                        text=text, include=True, kind="chapter", word_count=count_words(text)))
    session.commit()
    return _detail(session, project)


@router.get("/{project_id}/chapters/{chapter_id}", response_model=ChapterDetail)
def get_chapter(project_id: int, chapter_id: int, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    chapter = _chapter(session, project_id, chapter_id)
    out = chapter_out(chapter, render_settings(project), studio.lexicon_for(session, project_id))
    return ChapterDetail(**out.model_dump(), text=chapter.text)


@router.patch("/{project_id}/chapters/{chapter_id}", response_model=ChapterDetail)
def update_chapter(project_id: int, chapter_id: int, body: ChapterUpdate, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    chapter = _chapter(session, project_id, chapter_id)
    if body.title is not None:
        chapter.title = body.title.strip() or chapter.title
    if body.text is not None:
        chapter.text = body.text.replace("\r\n", "\n").strip()
        chapter.word_count = count_words(chapter.text)
    if body.include is not None:
        chapter.include = body.include
    if body.voice is not None:
        chapter.voice = body.voice.strip() or None
    session.commit()
    out = chapter_out(chapter, render_settings(project), studio.lexicon_for(session, project_id))
    return ChapterDetail(**out.model_dump(), text=chapter.text)


@router.delete("/{project_id}/chapters/{chapter_id}", response_model=ProjectDetail)
def delete_chapter(project_id: int, chapter_id: int, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _editable(project)
    chapter = _chapter(session, project_id, chapter_id)
    if chapter.audio_path:
        (get_config().data_dir / chapter.audio_path).unlink(missing_ok=True)
    session.delete(chapter)
    session.flush()
    session.refresh(project)
    _renumber(project)
    session.commit()
    return _detail(session, project)


@router.post("/{project_id}/chapters/bulk", response_model=ProjectDetail)
def bulk_update(project_id: int, body: ChapterBulk, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    ids = set(body.chapter_ids)
    for chapter in project.chapters:
        if chapter.id in ids:
            if body.include is not None:
                chapter.include = body.include
            if body.voice is not None:
                chapter.voice = body.voice.strip() or None
    session.commit()
    return _detail(session, project)


@router.post("/{project_id}/chapters/{chapter_id}/split", response_model=ProjectDetail)
def split_chapter(project_id: int, chapter_id: int, body: ChapterSplit, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _editable(project)
    chapter = _chapter(session, project_id, chapter_id)
    if body.offset >= len(chapter.text):
        raise HTTPException(400, "The split position is outside the chapter text.")
    head, tail = chapter.text[: body.offset].strip(), chapter.text[body.offset:].strip()
    if not head or not tail:
        raise HTTPException(400, "Both parts need some text.")
    first_line = tail.split("\n", 1)[0].strip()
    title = body.title or (first_line if len(first_line) <= 80 else f"{chapter.title} (continued)")
    for other in project.chapters:
        if other.position > chapter.position:
            other.position += 1
    chapter.text = head
    chapter.word_count = count_words(head)
    session.add(Chapter(project_id=project.id, position=chapter.position + 1, title=title, text=tail,
                        include=chapter.include, kind=chapter.kind, word_count=count_words(tail), voice=chapter.voice))
    session.commit()
    return _detail(session, project)


@router.post("/{project_id}/chapters/merge", response_model=ProjectDetail)
def merge_chapters(project_id: int, body: ChapterMerge, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _editable(project)
    chapters = sorted((c for c in project.chapters if c.id in set(body.chapter_ids)), key=lambda c: c.position)
    if len(chapters) < 2:
        raise HTTPException(400, "Select at least two chapters to merge.")
    first = chapters[0]
    first.text = "\n\n".join(c.text.strip() for c in chapters)
    first.word_count = count_words(first.text)
    first.include = any(c.include for c in chapters)
    for other in chapters[1:]:
        if other.audio_path:
            (get_config().data_dir / other.audio_path).unlink(missing_ok=True)
        session.delete(other)
    session.flush()
    session.refresh(project)
    _renumber(project)
    session.commit()
    return _detail(session, project)


@router.post("/{project_id}/chapters/reorder", response_model=ProjectDetail)
def reorder_chapters(project_id: int, body: ChapterReorder, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    _editable(project)
    order = {chapter_id: index for index, chapter_id in enumerate(body.chapter_ids)}
    if set(order) != {c.id for c in project.chapters}:
        raise HTTPException(400, "The new order must contain every chapter exactly once.")
    for chapter in project.chapters:
        chapter.position = order[chapter.id]
    session.commit()
    return _detail(session, project)


@router.post("/{project_id}/chapters/{chapter_id}/preview")
def preview_chapter(project_id: int, chapter_id: int, body: PreviewRequest, session: Session = Depends(get_db)):
    project = get_or_404(session, Project, project_id, "Project")
    chapter = _chapter(session, project_id, chapter_id)
    settings = render_settings(project)
    if chapter.voice:
        engine, sep, voice = chapter.voice.partition(":")
        if sep:
            settings.engine, settings.voice = engine, voice
    text = body.text or chapter.text
    try:
        audio, rate = render_preview(text, settings, get_registry(), studio.lexicon_for(session, project.id),
                                     body.max_chars, "" if body.text else chapter.title)
    except TTSError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _audio_response(audio, rate)


@router.get("/{project_id}/chapters/{chapter_id}/audio")
def chapter_audio(project_id: int, chapter_id: int, session: Session = Depends(get_db)):
    chapter = _chapter(session, project_id, chapter_id)
    if not chapter.audio_path:
        raise HTTPException(404, "This chapter has not been rendered yet.")
    path = get_config().data_dir / chapter.audio_path
    if not path.exists():
        raise HTTPException(404, "The rendered audio was removed.")
    return FileResponse(path, media_type="audio/flac")
