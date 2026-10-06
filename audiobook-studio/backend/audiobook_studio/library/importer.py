"""Import existing audiobooks from a folder (scan + read tags)."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from ..audio.assemble import ffprobe
from ..audio.codec import AudioError
from ..audio.tags import extract_cover, read_tags
from ..models import Book
from .paths import AUDIO_EXTENSIONS, library_root, resolve_path, to_library_relative
from .service import set_book_cover

log = logging.getLogger(__name__)

IMAGE_NAMES = ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png", "front.jpg")
SINGLE_FILE_FORMATS = {".m4b"}


@dataclass
class Candidate:
    folder: Path
    files: list[Path] = field(default_factory=list)


def _natural_key(path: Path) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def find_candidates(root: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        folder = Path(dirpath)
        audio = sorted((folder / f for f in filenames
                        if Path(f).suffix.lower() in AUDIO_EXTENSIONS and not f.startswith(".")), key=_natural_key)
        if not audio:
            continue
        singles = [p for p in audio if p.suffix.lower() in SINGLE_FILE_FORMATS]
        others = [p for p in audio if p.suffix.lower() not in SINGLE_FILE_FORMATS]
        for single in singles:
            candidates.append(Candidate(folder=folder, files=[single]))
        if others:
            # Disc folders (CD1, Disc 2) belong to the parent book.
            if re.match(r"^(cd|disc|disk|part)\s*\d+$", folder.name, re.IGNORECASE) and candidates and candidates[-1].folder == folder.parent:
                candidates[-1].files.extend(others)
            else:
                candidates.append(Candidate(folder=folder, files=others))
    return candidates


def _known_paths(session: Session) -> set[str]:
    known = set()
    for (files,) in session.query(Book.files):
        for entry in files or []:
            known.add(str(resolve_path(entry["path"]).resolve()))
    return known


def import_folder(
    session: Session,
    root: Path | None = None,
    progress: Callable[[float, str], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> dict[str, int]:
    root = (root or library_root()).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Folder not found: {root}")
    known = _known_paths(session)
    candidates = [c for c in find_candidates(root) if not any(str(f.resolve()) in known for f in c.files)]
    added = 0
    for index, candidate in enumerate(candidates):
        if check_cancelled:
            check_cancelled()
        if progress:
            progress(index / max(1, len(candidates)), f"Importing {candidate.folder.name}")
        try:
            book = build_book(candidate, root)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not import %s: %s", candidate.folder, exc)
            continue
        session.add(book)
        session.flush()
        cover = _find_cover(candidate)
        if cover:
            try:
                set_book_cover(book, cover)
            except Exception as exc:  # noqa: BLE001
                log.info("Ignoring invalid cover in %s: %s", candidate.folder, exc)
        session.commit()
        added += 1
    return {"found": len(candidates), "added": added}


def build_book(candidate: Candidate, root: Path) -> Book:
    infos = [read_tags(path) for path in candidate.files]
    first = infos[0]
    single = len(candidate.files) == 1
    folder = candidate.folder
    relative_parts = folder.relative_to(root).parts if folder != root else ()

    title = (first.get("album") if not single else first.get("album") or first.get("title")) or ""
    if not title:
        title = candidate.files[0].stem if single and folder == root else folder.name
    title = re.sub(r"^\d+\s*[-.]\s*", "", title) if not single else title
    author = first.get("album_artist") or first.get("artist") or ""
    if not author and len(relative_parts) >= 2:
        author = relative_parts[0]
    series = first.get("series", "")
    series_index = first.get("series_index", "")
    if not series and len(relative_parts) >= 3:
        series = relative_parts[1]

    files = []
    chapters = []
    position = 0.0
    total_size = 0
    for path, info in zip(candidate.files, infos):
        duration = float(info.get("duration") or 0.0)
        size = path.stat().st_size
        total_size += size
        files.append({"path": to_library_relative(path), "duration": round(duration, 3), "size": size,
                      "title": info.get("title") or path.stem})
        embedded = _embedded_chapters(path) if path.suffix.lower() in (".m4b", ".m4a", ".mp3") else []
        if embedded:
            chapters.extend({"title": c["title"], "start": round(position + c["start"], 3),
                             "end": round(position + c["end"], 3)} for c in embedded)
        else:
            chapters.append({"title": info.get("title") or path.stem, "start": round(position, 3),
                             "end": round(position + duration, 3)})
        position += duration

    description = first.get("description", "")
    narrator = first.get("narrator", "")
    desc_file = folder / "desc.txt"
    reader_file = folder / "reader.txt"
    if not description and desc_file.exists():
        description = desc_file.read_text(encoding="utf-8", errors="replace").strip()
    if not narrator and reader_file.exists():
        narrator = reader_file.read_text(encoding="utf-8", errors="replace").strip()

    formats = {p.suffix.lower().lstrip(".") for p in candidate.files}
    return Book(
        title=title.strip() or "Untitled",
        author=author.strip(),
        narrator=narrator.strip(),
        series=series.strip(),
        series_index=series_index.strip(),
        genre=first.get("genre", ""),
        year=first.get("year", ""),
        description=description,
        publisher=first.get("publisher", ""),
        language=first.get("language", ""),
        isbn=first.get("isbn", ""),
        tags=[],
        path=to_library_relative(folder),
        files=files,
        chapters=chapters,
        duration=round(position, 3),
        size=total_size,
        format=formats.pop() if len(formats) == 1 else "mixed",
        source="import",
    )


def _embedded_chapters(path: Path) -> list[dict]:
    try:
        info = ffprobe(path)
    except AudioError:
        return []
    result = []
    for chapter in info.get("chapters", []):
        try:
            start, end = float(chapter["start_time"]), float(chapter["end_time"])
        except (KeyError, ValueError):
            continue
        title = (chapter.get("tags") or {}).get("title") or f"Chapter {len(result) + 1}"
        result.append({"title": title, "start": start, "end": end})
    result.sort(key=lambda c: c["start"])
    return result


def _find_cover(candidate: Candidate) -> bytes | None:
    for name in IMAGE_NAMES:
        path = candidate.folder / name
        if path.exists():
            return path.read_bytes()
    for image in sorted(candidate.folder.glob("*.jp*g")) + sorted(candidate.folder.glob("*.png")):
        return image.read_bytes()
    for path in candidate.files[:1]:
        data = extract_cover(path)
        if data:
            return data
    return None
