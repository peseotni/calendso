"""Library: browse, edit, play, organise and import audiobooks."""

from __future__ import annotations

import re
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from .. import settings_store
from ..config import get_config
from ..db import get_db
from ..jobs.runner import runner
from ..library import service as library
from ..library.covers import CoverError, fetch_cover, thumb_path
from ..library.feeds import MIME
from ..library.paths import TEMPLATE_FIELDS, TEMPLATE_PRESETS, render_template, resolve_path, template_fields
from ..models import METADATA_FIELDS, Book, Collection, collection_books, utcnow
from ..schemas import BookOut, BookUpdate, BulkBookUpdate, CoverUrl, JobOut, OrganizeRequest, ProgressUpdate, ScanRequest
from .common import book_out, get_or_404, job_out

router = APIRouter(prefix="/api", tags=["library"])

PATH_FIELDS = {"author", "title", "series", "series_index", "genre", "year", "narrator", "language", "publisher", "subtitle"}
SORTS = {
    "title": lambda b: (b.title or "").lower(),
    "author": lambda b: ((b.author or "~").lower(), (b.series or "").lower(), _index(b.series_index), (b.title or "").lower()),
    "added": lambda b: b.added_at,
    "duration": lambda b: b.duration,
    "year": lambda b: b.year or "0",
    "series": lambda b: ((b.series or "~").lower(), _index(b.series_index), (b.title or "").lower()),
    "last_played": lambda b: b.last_played_at.isoformat() if b.last_played_at else "",
    "rating": lambda b: b.rating,
    "progress": lambda b: (b.progress / b.duration) if b.duration else 0,
}


def _index(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 9999.0


@router.get("/books", response_model=list[BookOut])
def list_books(
    q: str = "",
    author: str | None = None,
    genre: str | None = None,
    series: str | None = None,
    narrator: str | None = None,
    language: str | None = None,
    year: str | None = None,
    tag: str | None = None,
    collection: int | None = None,
    favorite: bool | None = None,
    status: str | None = Query(None, pattern="^(unplayed|in_progress|finished)$"),
    source: str | None = None,
    missing: bool | None = None,
    sort: str = "added",
    order: str = Query("desc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
):
    query = session.query(Book)
    if q.strip():
        for term in q.split():
            like = f"%{term}%"
            query = query.filter(or_(
                Book.title.ilike(like), Book.subtitle.ilike(like), Book.author.ilike(like),
                Book.narrator.ilike(like), Book.series.ilike(like), Book.genre.ilike(like),
                Book.publisher.ilike(like), Book.isbn.ilike(like), cast(Book.tags, String).ilike(like),
            ))
    for column, value in ((Book.author, author), (Book.series, series), (Book.narrator, narrator),
                          (Book.language, language), (Book.year, year), (Book.source, source)):
        if value is not None:
            query = query.filter(column == value)
    if genre is not None:
        query = query.filter(or_(Book.genre == genre, Book.genre.ilike(f"{genre},%"), Book.genre.ilike(f"%, {genre}"),
                                 Book.genre.ilike(f"%, {genre},%")))
    if tag:
        query = query.filter(cast(Book.tags, String).ilike(f'%"{tag}"%'))
    if collection is not None:
        query = query.join(collection_books, collection_books.c.book_id == Book.id).filter(
            collection_books.c.collection_id == collection)
    if favorite is not None:
        query = query.filter(Book.favorite.is_(favorite))
    if missing is not None:
        query = query.filter(Book.missing.is_(missing))
    if status == "finished":
        query = query.filter(Book.finished.is_(True))
    elif status == "in_progress":
        query = query.filter(Book.finished.is_(False), Book.progress > 0)
    elif status == "unplayed":
        query = query.filter(Book.finished.is_(False), Book.progress == 0)
    books = query.all()
    key = SORTS.get(sort, SORTS["added"])
    books.sort(key=key, reverse=order == "desc")
    return [book_out(b) for b in books]


@router.get("/books/facets")
def facets(session: Session = Depends(get_db)):
    books = session.query(Book).all()
    counters: dict[str, Counter] = {k: Counter() for k in ("author", "genre", "series", "narrator", "language", "year", "tags", "format")}
    for book in books:
        for key in ("author", "series", "narrator", "language", "year", "format"):
            value = getattr(book, key)
            if value:
                counters[key][value] += 1
        for genre in (book.genre or "").split(","):
            if genre.strip():
                counters["genre"][genre.strip()] += 1
        for tag in book.tags or []:
            counters["tags"][tag] += 1
    result = {
        key: [{"value": value, "count": count} for value, count in sorted(counter.items(), key=lambda kv: kv[0].lower())]
        for key, counter in counters.items()
    }
    result["total"] = len(books)
    return result


@router.get("/books/{book_id}", response_model=BookOut)
def get_book(book_id: int, session: Session = Depends(get_db)):
    return book_out(get_or_404(session, Book, book_id, "Book"))


def _apply_changes(session: Session, book: Book, changes: dict) -> bool:
    """Apply metadata changes; returns True when tags/paths must be rewritten."""
    retag = False
    for field, value in changes.items():
        if field in METADATA_FIELDS and value is not None:
            value = [t.strip() for t in value if t.strip()] if field == "tags" else str(value).strip()
            if getattr(book, field) != value:
                setattr(book, field, value)
                retag = True
        elif field in ("rating", "favorite", "finished") and value is not None:
            setattr(book, field, value)
            if field == "finished" and value:
                book.progress = 0.0
    if "collection_ids" in changes and changes["collection_ids"] is not None:
        wanted = set(changes["collection_ids"])
        book.collections = session.query(Collection).filter(Collection.id.in_(wanted)).all() if wanted else []
    return retag


@router.patch("/books/{book_id}", response_model=BookOut)
def update_book(book_id: int, body: BookUpdate, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    changes = body.model_dump(exclude_unset=True)
    retag = _apply_changes(session, book, changes)
    session.commit()
    if retag and book.files:
        move = bool(PATH_FIELDS & set(changes))
        runner.enqueue(session, "retag", f"Update tags of “{book.title}”", {"move": move}, book_id=book.id)
    session.refresh(book)
    return book_out(book)


@router.post("/books/bulk")
def bulk_update(body: BulkBookUpdate, session: Session = Depends(get_db)):
    books = session.query(Book).filter(Book.id.in_(body.book_ids)).all()
    allowed = {k: v for k, v in body.changes.items() if k in METADATA_FIELDS or k in ("rating", "favorite", "finished")}
    collection_add = session.get(Collection, body.add_collection_id) if body.add_collection_id else None
    collection_remove = session.get(Collection, body.remove_collection_id) if body.remove_collection_id else None
    to_retag = []
    for book in books:
        if _apply_changes(session, book, allowed):
            to_retag.append(book)
        if collection_add and collection_add not in book.collections:
            book.collections.append(collection_add)
        if collection_remove and collection_remove in book.collections:
            book.collections.remove(collection_remove)
    session.commit()
    move = bool(PATH_FIELDS & set(allowed))
    for book in to_retag:
        if book.files:
            runner.enqueue(session, "retag", f"Update tags of “{book.title}”", {"move": move}, book_id=book.id)
    return {"updated": len(books), "retagging": len(to_retag)}


@router.delete("/books/{book_id}")
def delete_book(book_id: int, delete_files: bool = False, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    if delete_files:
        library.delete_book_files(book)
    from ..models import Project

    for project in session.query(Project).filter(Project.book_id == book.id):
        project.book_id = None
        if project.status == "done":
            project.status = "ready"
    session.delete(book)
    session.commit()
    return {"ok": True}


@router.put("/books/{book_id}/progress", response_model=BookOut)
def save_progress(book_id: int, body: ProgressUpdate, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    book.progress = min(body.position, book.duration or body.position)
    book.last_played_at = utcnow()
    if body.finished is not None:
        book.finished = body.finished
    elif book.duration and book.progress >= book.duration - min(15.0, book.duration * 0.02):
        book.finished = True
    session.commit()
    return book_out(book)


# ------------------------------------------------------------------- media
@router.get("/books/{book_id}/cover")
def book_cover(book_id: int, size: str = "full", session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    if not book.cover_path:
        raise HTTPException(404, "No cover")
    path = get_config().data_dir / book.cover_path
    if size == "thumb" and thumb_path(path).exists():
        path = thumb_path(path)
    if not path.exists():
        raise HTTPException(404, "No cover")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


def _store_book_cover(session: Session, book: Book, data: bytes) -> None:
    try:
        library.set_book_cover(book, data)
    except CoverError as exc:
        raise HTTPException(400, str(exc)) from exc
    book.updated_at = utcnow()
    session.commit()
    if book.files:
        runner.enqueue(session, "retag", f"Update cover of “{book.title}”", {"move": False}, book_id=book.id)


@router.post("/books/{book_id}/cover", response_model=BookOut)
def upload_book_cover(book_id: int, file: UploadFile = File(...), session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    _store_book_cover(session, book, file.file.read(30 * 1024 * 1024))
    return book_out(book)


@router.post("/books/{book_id}/cover/url", response_model=BookOut)
def book_cover_from_url(book_id: int, body: CoverUrl, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    try:
        data = fetch_cover(body.url)
    except CoverError as exc:
        raise HTTPException(400, str(exc)) from exc
    _store_book_cover(session, book, data)
    return book_out(book)


@router.get("/books/{book_id}/files/{index}")
def stream_file(book_id: int, index: int, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    if not 0 <= index < len(book.files or []):
        raise HTTPException(404, "File not found")
    path = resolve_path(book.files[index]["path"])
    if not path.exists():
        raise HTTPException(404, "The audio file is missing on disk")
    media_type = MIME.get(path.suffix.lower(), "application/octet-stream")
    if path.suffix.lower() in (".m4b", ".m4a"):
        media_type = "audio/mp4"  # what browsers expect for playback
    return FileResponse(path, media_type=media_type, filename=path.name, content_disposition_type="inline")


@router.get("/books/{book_id}/download")
def download_book(book_id: int, background: BackgroundTasks, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    paths = [resolve_path(f["path"]) for f in book.files or []]
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise HTTPException(404, "No audio files found")
    if len(paths) == 1:
        return FileResponse(paths[0], filename=paths[0].name)
    safe = re.sub(r"[^\w .-]+", "", f"{book.author} - {book.title}").strip() or "audiobook"
    tmp = tempfile.NamedTemporaryFile(prefix="book-", suffix=".zip", dir=get_config().tmp_path, delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in paths:
            archive.write(path, f"{safe}/{path.name}")
        cover = library.read_cover(book.cover_path)
        if cover:
            archive.writestr(f"{safe}/cover.jpg", cover)
    background.add_task(Path(tmp.name).unlink, missing_ok=True)
    return FileResponse(tmp.name, filename=f"{safe}.zip", media_type="application/zip")


@router.post("/books/{book_id}/retag", response_model=JobOut)
def retag_book(book_id: int, session: Session = Depends(get_db)):
    book = get_or_404(session, Book, book_id, "Book")
    return job_out(runner.enqueue(session, "retag", f"Update tags of “{book.title}”", {"move": False}, book_id=book.id))


# ------------------------------------------------------------------- organisation
@router.get("/library/templates")
def templates():
    settings = settings_store.current()
    return {"presets": TEMPLATE_PRESETS, "fields": TEMPLATE_FIELDS, "current": settings.library_template,
            "library_path": str(get_config().library_path)}


@router.post("/library/template-preview")
def template_preview(body: OrganizeRequest, session: Session = Depends(get_db)):
    template = body.template or settings_store.current().library_template
    books = session.query(Book).order_by(Book.added_at.desc()).limit(6).all()
    samples = [template_fields(b) for b in books] or [
        {"author": "Ursula K. Le Guin", "title": "A Wizard of Earthsea", "series": "Earthsea Cycle",
         "series_index": "1", "genre": "Fantasy", "year": "1968", "narrator": "Kokoro", "language": "en"},
        {"author": "Jane Austen", "title": "Pride and Prejudice", "genre": "Classics", "year": "1813", "language": "en"},
    ]
    return {"template": template, "examples": [render_template(template, fields) for fields in samples]}


@router.post("/library/organize/preview")
def organize_preview(body: OrganizeRequest, session: Session = Depends(get_db)):
    template = body.template or settings_store.current().library_template
    plan = library.organize_plan(session, template, body.book_ids)
    return {"template": template, "moves": plan}


@router.post("/library/organize", response_model=JobOut)
def organize(body: OrganizeRequest, session: Session = Depends(get_db)):
    if body.template:
        settings_store.update_settings(session, {"library_template": body.template})
    job = runner.enqueue(session, "organize", "Organise library folders", {"template": body.template, "book_ids": body.book_ids})
    return job_out(job)


@router.post("/library/scan", response_model=JobOut)
def scan(body: ScanRequest, session: Session = Depends(get_db)):
    path = body.path.strip() if body.path else None
    if path and not Path(path).is_dir():
        raise HTTPException(400, f"Folder not found: {path}")
    job = runner.enqueue(session, "scan", "Scan for existing audiobooks", {"path": path})
    return job_out(job)
