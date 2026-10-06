"""Library operations: publishing renders, moving/organising, retagging, sidecars."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..audio.assemble import AssemblyResult
from ..audio.tags import BookTags, write_tags
from ..config import get_config
from ..models import METADATA_FIELDS, Book, Project
from .covers import delete_cover, save_cover
from .paths import (
    AUDIO_EXTENSIONS,
    is_inside_library,
    library_root,
    remove_empty_dirs,
    render_template,
    resolve_path,
    template_fields,
    to_library_relative,
    unique_dir,
)

log = logging.getLogger(__name__)

SIDECARS = ("cover.jpg", "desc.txt", "reader.txt", "metadata.json")


def book_tags(item: Any) -> BookTags:
    return BookTags(
        title=item.title or "Untitled",
        subtitle=item.subtitle or "",
        author=item.author or "",
        narrator=item.narrator or "",
        series=item.series or "",
        series_index=item.series_index or "",
        genre=item.genre or "",
        year=item.year or "",
        description=item.description or "",
        publisher=item.publisher or "",
        language=item.language or "",
        isbn=item.isbn or "",
        tags=list(item.tags or []),
    )


def book_cover_path(book_id: int) -> Path:
    return get_config().covers_path / f"book_{book_id}.jpg"


def read_cover(path_value: str | None) -> bytes | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = get_config().data_dir / path
    try:
        return path.read_bytes()
    except OSError:
        return None


def data_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(get_config().data_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def set_book_cover(book: Book, data: bytes) -> None:
    path = book_cover_path(book.id)
    save_cover(data, path)
    book.cover_path = data_relative(path)


def book_dir(book: Book) -> Path:
    return resolve_path(book.path) if book.path else library_root()


def target_dir_for(book: Book, template: str) -> Path:
    return library_root() / render_template(template, template_fields(book))


def _file_paths(book: Book) -> list[Path]:
    return [resolve_path(f["path"]) for f in (book.files or [])]


def publish_render(
    session: Session,
    project: Project,
    result: AssemblyResult,
    template: str,
    write_sidecar_files: bool = True,
) -> Book:
    """Move freshly assembled files into the library and create/update the Book."""
    book = session.get(Book, project.book_id) if project.book_id else None
    if book is None:
        book = Book(source="studio", project_id=project.id)
        session.add(book)
    for field in METADATA_FIELDS:
        setattr(book, field, getattr(project, field))
    if not book.narrator:
        book.narrator = project.narrator
    session.flush()

    # Remove the previous render's files (re-render replaces them).
    old_files = _file_paths(book)
    old_dir = book_dir(book) if book.path else None
    for path in old_files:
        if path.exists() and is_inside_library(path):
            path.unlink()

    target = unique_dir(target_dir_for(book, template), set(old_files))
    target.mkdir(parents=True, exist_ok=True)
    files = []
    total_size = 0
    for output in result.files:
        destination = target / output.path.name
        shutil.move(str(output.path), destination)
        size = destination.stat().st_size
        total_size += size
        files.append({"path": to_library_relative(destination), "duration": round(output.duration, 3),
                      "size": size, "title": output.title})
    book.path = to_library_relative(target)
    book.files = files
    book.chapters = result.chapters
    book.duration = round(result.duration, 3)
    book.size = total_size
    book.format = result.format
    book.missing = False

    cover = read_cover(project.cover_path)
    if cover:
        set_book_cover(book, cover)
    if old_dir and old_dir.resolve() != target.resolve():
        _move_sidecars(old_dir, target)
        remove_empty_dirs(old_dir, library_root())
    if write_sidecar_files:
        write_sidecars(book)
    session.flush()
    return book


def write_sidecars(book: Book) -> None:
    """cover.jpg / desc.txt / reader.txt / metadata.json for other players."""
    folder = book_dir(book)
    if not folder.exists() or not is_inside_library(folder) or folder.resolve() == library_root().resolve():
        return
    try:
        cover = read_cover(book.cover_path)
        if cover:
            (folder / "cover.jpg").write_bytes(cover)
        if book.description:
            (folder / "desc.txt").write_text(book.description, encoding="utf-8")
        if book.narrator:
            (folder / "reader.txt").write_text(book.narrator, encoding="utf-8")
        metadata = {
            "title": book.title,
            "subtitle": book.subtitle or None,
            "authors": [a.strip() for a in (book.author or "").replace(" & ", ",").split(",") if a.strip()],
            "narrators": [n.strip() for n in (book.narrator or "").split(",") if n.strip()],
            "series": [f"{book.series} #{book.series_index}" if book.series_index else book.series] if book.series else [],
            "genres": [g.strip() for g in (book.genre or "").split(",") if g.strip()],
            "tags": list(book.tags or []),
            "publishedYear": book.year or None,
            "publisher": book.publisher or None,
            "description": book.description or None,
            "isbn": book.isbn or None,
            "language": book.language or None,
            "chapters": [
                {"id": i, "start": c["start"], "end": c["end"], "title": c["title"]}
                for i, c in enumerate(book.chapters or [])
            ],
        }
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write sidecar files for book %s: %s", book.id, exc)


def _move_sidecars(old_dir: Path, new_dir: Path) -> None:
    if not old_dir.exists():
        return
    remaining_audio = [p for p in old_dir.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
    if remaining_audio:
        return
    for name in SIDECARS:
        source = old_dir / name
        if source.exists():
            destination = new_dir / name
            if destination.exists():
                source.unlink()
            else:
                shutil.move(str(source), destination)


def move_book(book: Book, new_dir: Path) -> bool:
    """Move a book's files into ``new_dir``; returns True when something moved."""
    old_dir = book_dir(book)
    files = _file_paths(book)
    if not files or not all(is_inside_library(p) for p in files):
        return False
    new_dir = unique_dir(new_dir, set(files))
    if new_dir.resolve() == old_dir.resolve():
        return False
    new_dir.mkdir(parents=True, exist_ok=True)
    updated = []
    for entry, source in zip(book.files, files):
        try:
            relative = source.resolve().relative_to(old_dir.resolve())
        except ValueError:
            relative = Path(source.name)
        destination = new_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.move(str(source), destination)
        updated.append({**entry, "path": to_library_relative(destination)})
    book.files = updated
    _move_sidecars(old_dir, new_dir)
    book.path = to_library_relative(new_dir)
    for source in files:
        remove_empty_dirs(source.parent, library_root())
    remove_empty_dirs(old_dir, library_root())
    return True


def organize_plan(session: Session, template: str, book_ids: list[int] | None = None) -> list[dict[str, Any]]:
    query = session.query(Book)
    if book_ids:
        query = query.filter(Book.id.in_(book_ids))
    plan = []
    for book in query.order_by(Book.author, Book.title):
        files = _file_paths(book)
        if not files or not all(is_inside_library(p) for p in files):
            continue
        current = book_dir(book)
        target = target_dir_for(book, template)
        if current.resolve() != target.resolve():
            plan.append({
                "book_id": book.id,
                "title": book.title,
                "from": to_library_relative(current),
                "to": to_library_relative(target),
            })
    return plan


def retag_files(book: Book) -> int:
    tags = book_tags(book)
    cover = read_cover(book.cover_path)
    files = [p for p in _file_paths(book) if p.exists()]
    for index, (entry, path) in enumerate(zip(book.files or [], _file_paths(book)), start=1):
        if not path.exists():
            continue
        track = (index, len(files)) if len(files) > 1 else None
        write_tags(path, tags, cover, track=track, track_title=entry.get("title") if len(files) > 1 else None)
    return len(files)


def delete_book_files(book: Book) -> None:
    folder = book_dir(book)
    for path in _file_paths(book):
        if path.exists() and is_inside_library(path):
            path.unlink()
            remove_empty_dirs(path.parent, library_root())
    if folder.exists() and is_inside_library(folder) and folder.resolve() != library_root().resolve():
        remaining = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
        if not remaining:
            for name in SIDECARS:
                (folder / name).unlink(missing_ok=True)
        remove_empty_dirs(folder, library_root())
    if book.cover_path:
        delete_cover(get_config().data_dir / book.cover_path)


def check_missing(book: Book) -> bool:
    missing = not book.files or not all(resolve_path(f["path"]).exists() for f in book.files)
    book.missing = missing
    return missing
