"""Library folder naming templates and path helpers."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from ..config import get_config

TEMPLATE_PRESETS = [
    {"id": "abs", "label": "Author / Series / # - Title (Audiobookshelf, Plex)", "template": "{author}/[{series}/][{series_index} - ]{title}"},
    {"id": "author_title", "label": "Author / Title", "template": "{author}/{title}"},
    {"id": "genre", "label": "Genre / Author / Title", "template": "{genre}/{author}/{title}"},
    {"id": "flat", "label": "Author - Title (flat)", "template": "{author} - {title}"},
    {"id": "language", "label": "Language / Author / Title", "template": "{language}/{author}/{title}"},
    {"id": "year", "label": "Year / Author - Title", "template": "{year}/{author} - {title}"},
]
TEMPLATE_FIELDS = [
    "author", "author_sort", "title", "subtitle", "series", "series_index", "genre",
    "year", "narrator", "language", "publisher", "first_letter",
]
_TOKEN_RE = re.compile(r"\{(\w+)(?::([^}]*))?\}")
_GROUP_RE = re.compile(r"\[([^\[\]]*)\]")
_FALLBACKS = {"author": "Unknown Author", "title": "Untitled", "genre": "Unsorted", "language": "Unknown", "year": "Unknown Year"}


def sanitize_component(value: str, max_length: int = 120) -> str:
    value = unicodedata.normalize("NFC", str(value))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if len(value) > max_length:
        value = value[:max_length].rstrip(" .")
    if value in ("", ".", ".."):
        return ""
    return value


def author_sort(author: str) -> str:
    first = re.split(r"\s*(?:,|&|;| and )\s*", author.strip())[0] if author.strip() else ""
    parts = first.split()
    if len(parts) < 2:
        return first
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def template_fields(item: Any) -> dict[str, str]:
    get = (lambda k: item.get(k, "")) if isinstance(item, dict) else (lambda k: getattr(item, k, "") or "")
    author = str(get("author") or "")
    fields = {
        "author": author,
        "author_sort": author_sort(author),
        "title": str(get("title") or ""),
        "subtitle": str(get("subtitle") or ""),
        "series": str(get("series") or ""),
        "series_index": str(get("series_index") or ""),
        "genre": str(get("genre") or "").split(",")[0].strip(),
        "year": str(get("year") or ""),
        "narrator": str(get("narrator") or ""),
        "language": str(get("language") or ""),
        "publisher": str(get("publisher") or ""),
    }
    surname = fields["author_sort"] or fields["title"]
    fields["first_letter"] = surname[:1].upper() if surname[:1].isalpha() else "#"
    return fields


def _format_token(fields: dict[str, str], name: str, spec: str | None) -> str:
    value = fields.get(name, "")
    if value and spec:
        try:
            number = float(value)
            value = format(int(number) if number.is_integer() else number, spec)
        except (ValueError, TypeError):
            pass
    return value


def render_template(template: str, fields: dict[str, str]) -> str:
    """Render a folder template.

    ``{field}`` inserts a value, ``{series_index:02}`` applies a number format and
    ``[ ... ]`` marks an optional group that disappears when any field inside it is empty.
    """

    def group(match: re.Match[str]) -> str:
        inner = match.group(1)
        tokens = _TOKEN_RE.findall(inner)
        if any(not fields.get(name) for name, _ in tokens):
            return ""
        return _TOKEN_RE.sub(lambda m: sanitize_component(_format_token(fields, m.group(1), m.group(2))), inner)

    rendered = _GROUP_RE.sub(group, template)
    rendered = _TOKEN_RE.sub(
        lambda m: sanitize_component(_format_token(fields, m.group(1), m.group(2)) or _FALLBACKS.get(m.group(1), "")),
        rendered,
    )
    parts = [sanitize_component(part) for part in rendered.replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    return "/".join(parts) or sanitize_component(fields.get("title") or "Untitled") or "Untitled"


def library_root() -> Path:
    return get_config().library_path


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else library_root() / path


def to_library_relative(path: Path) -> str:
    root = library_root().resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def is_inside_library(path: Path) -> bool:
    try:
        path.resolve().relative_to(library_root().resolve())
        return True
    except ValueError:
        return False


def unique_dir(path: Path, own_files: set[Path] | None = None) -> Path:
    """Return ``path`` or ``path (2)``... when it holds another book's audio."""
    own = {p.resolve() for p in (own_files or set())}
    candidate = path
    counter = 2
    while candidate.exists() and _has_foreign_audio(candidate, own):
        candidate = path.with_name(f"{path.name} ({counter})")
        counter += 1
    return candidate


AUDIO_EXTENSIONS = {".m4b", ".m4a", ".mp3", ".opus", ".ogg", ".oga", ".flac", ".aac", ".wav", ".wma", ".mp4"}


def _has_foreign_audio(folder: Path, own: set[Path]) -> bool:
    try:
        for child in folder.iterdir():
            if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS and child.resolve() not in own:
                return True
    except OSError:
        return False
    return False


def remove_empty_dirs(start: Path, stop: Path) -> None:
    """Remove empty directories from ``start`` upwards, never touching ``stop``."""
    try:
        current = start.resolve()
        stop = stop.resolve()
        while current != stop and stop in current.parents:
            if any(current.iterdir()):
                break
            current.rmdir()
            current = current.parent
    except OSError:
        pass
