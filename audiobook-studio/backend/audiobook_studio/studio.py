"""Project (conversion) operations shared by the API, job handlers and the inbox."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from . import settings_store
from .config import get_config
from .ingest import IngestError, ParsedBook, detect_format
from .ingest.base import count_words
from .jobs.runner import runner
from .library.covers import save_cover
from .library.service import data_relative
from .models import Chapter, Job, LexiconRule, Project
from .settings_store import RenderSettings
from .text.lexicon import Lexicon, Rule
from .tts import TTSError, get_registry

log = logging.getLogger(__name__)


def project_dir(project_id: int) -> Path:
    return get_config().projects_path / str(project_id)


def source_path(project: Project) -> Path | None:
    if not project.source_path:
        return None
    path = Path(project.source_path)
    return path if path.is_absolute() else get_config().data_dir / path


def voice_label(engine_id: str, voice_id: str) -> str:
    try:
        engine = get_registry().get(engine_id)
        base = voice_id.split("#", 1)[0]
        if "+" in voice_id:
            name = " + ".join(p.split(":", 1)[0].split("_", 1)[-1].title() for p in voice_id.split("+"))
        else:
            name = next((v.name for v in engine.list_voices() if v.id == base), voice_id)
        return f"{name} ({engine.name})"
    except TTSError:
        return voice_id


def default_render_settings(language: str) -> RenderSettings:
    defaults = settings_store.current().render_defaults.model_copy(deep=True)
    try:
        engine, voice = get_registry().pick_voice(language or "en", defaults.engine, defaults.voice)
        defaults.engine, defaults.voice = engine, voice
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not pick a default voice: %s", exc)
    return defaults


def create_project_from_file(
    session: Session, filename: str, uploaded: Path, options: dict | None = None
) -> Project:
    fmt = detect_format(filename)
    if fmt is None:
        raise IngestError(f"Unsupported file type: {filename}")
    stem = re.sub(r"\.fb2$", "", Path(filename).stem, flags=re.IGNORECASE)
    project = Project(
        title=re.sub(r"[_]+", " ", stem).strip() or "Untitled",
        source_filename=filename,
        source_format=fmt,
        status="importing",
        settings={},
        import_options=options or {},
    )
    session.add(project)
    session.flush()
    folder = project_dir(project.id)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = ".fb2.zip" if filename.lower().endswith(".fb2.zip") else Path(filename).suffix.lower()
    destination = folder / f"source{suffix}"
    shutil.move(str(uploaded), destination)
    project.source_path = data_relative(destination)
    session.commit()
    runner.enqueue(session, "ingest", f"Import “{filename}”", {}, project_id=project.id)
    return project


def create_project_from_text(session: Session, title: str, text: str, author: str = "") -> Project:
    from .ingest import finalize
    from .ingest.plain import parse_pasted_text

    parsed = finalize(parse_pasted_text(title, text, author))
    project = Project(title=title or "Untitled", source_filename="", source_format="text", status="importing", settings={})
    session.add(project)
    session.flush()
    project_dir(project.id).mkdir(parents=True, exist_ok=True)
    apply_parsed(session, project, parsed)
    session.commit()
    return project


_GENRE_MAP = {
    "fiction": "Fiction", "science fiction": "Science Fiction", "sf": "Science Fiction", "fantasy": "Fantasy",
    "mystery": "Mystery", "thriller": "Thriller", "romance": "Romance", "horror": "Horror",
    "biography": "Biography", "history": "History", "poetry": "Poetry", "children": "Children",
}


def _genre(subjects: list[str]) -> str:
    for subject in subjects:
        value = subject.split("/")[-1].split("--")[0].strip()
        if value and len(value) <= 40:
            mapped = _GENRE_MAP.get(value.lower())
            return mapped or (value.title() if value.islower() else value)
    return ""


def apply_parsed(session: Session, project: Project, parsed: ParsedBook) -> None:
    project.title = parsed.title or project.title
    project.subtitle = parsed.subtitle
    project.author = ", ".join(parsed.authors)
    project.language = parsed.language or project.language
    project.publisher = parsed.publisher
    project.year = parsed.year
    project.description = parsed.description
    project.isbn = parsed.isbn
    project.series = parsed.series
    project.series_index = parsed.series_index
    project.genre = _genre(parsed.subjects)
    project.tags = [s for s in parsed.subjects if len(s) <= 40][:10]
    project.warnings = parsed.warnings

    if parsed.cover:
        try:
            path = project_dir(project.id) / "cover.jpg"
            save_cover(parsed.cover, path)
            project.cover_path = data_relative(path)
        except Exception as exc:  # noqa: BLE001
            log.info("Ignoring unreadable cover: %s", exc)

    for chapter in list(project.chapters):
        session.delete(chapter)
    session.flush()
    for position, chapter in enumerate(parsed.chapters):
        session.add(Chapter(
            project_id=project.id,
            position=position,
            title=chapter.title,
            text=chapter.text,
            include=chapter.include,
            kind=chapter.kind,
            word_count=count_words(chapter.text),
        ))
    if not project.settings:
        settings = default_render_settings(project.language)
        project.settings = settings.model_dump()
        project.narrator = voice_label(settings.engine, settings.voice)
    project.status = "ready"
    project.error = ""


def lexicon_for(session: Session, project_id: int | None) -> Lexicon:
    query = session.query(LexiconRule).filter(LexiconRule.enabled.is_(True))
    rules = query.filter((LexiconRule.project_id == project_id) | (LexiconRule.project_id.is_(None))).all()
    # Project rules first so they can override global ones.
    rules.sort(key=lambda r: (r.project_id is None, r.id))
    return Lexicon(
        Rule(r.pattern, r.replacement, r.is_regex, r.case_sensitive, r.whole_word) for r in rules
    )


def active_job(session: Session, project_id: int, kinds: tuple[str, ...] = ("render", "ingest")) -> Job | None:
    return (
        session.query(Job)
        .filter(Job.project_id == project_id, Job.kind.in_(kinds), Job.status.in_(("queued", "running")))
        .order_by(Job.id.desc())
        .first()
    )


def enqueue_render(session: Session, project: Project, chapter_ids: list[int] | None = None) -> Job:
    existing = active_job(session, project.id)
    if existing is not None:
        return existing
    project.status = "queued"
    project.error = ""
    session.commit()
    return runner.enqueue(
        session, "render", f"Narrate “{project.title}”", {"chapter_ids": chapter_ids or []}, project_id=project.id
    )


def delete_workspace_audio(session: Session, project: Project) -> int:
    removed = 0
    for chapter in project.chapters:
        if chapter.audio_path:
            path = get_config().data_dir / chapter.audio_path
            if path.exists():
                path.unlink()
                removed += 1
            chapter.audio_path = None
            chapter.audio_hash = None
            chapter.status = "pending"
    audio_dir = project_dir(project.id) / "audio"
    if audio_dir.exists():
        shutil.rmtree(audio_dir, ignore_errors=True)
    return removed


def workspace_size(project_id: int) -> int:
    folder = project_dir(project_id)
    if not folder.exists():
        return 0
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
