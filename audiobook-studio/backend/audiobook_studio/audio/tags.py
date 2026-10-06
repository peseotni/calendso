"""Reading and writing audiobook metadata tags (MP4/M4B, MP3, Opus, FLAC)."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class BookTags:
    title: str = ""
    subtitle: str = ""
    author: str = ""
    narrator: str = ""
    series: str = ""
    series_index: str = ""
    genre: str = ""
    year: str = ""
    description: str = ""
    publisher: str = ""
    language: str = ""
    isbn: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def album(self) -> str:
        return f"{self.title}: {self.subtitle}" if self.subtitle else self.title

    @property
    def grouping(self) -> str:
        if not self.series:
            return ""
        return f"{self.series} #{self.series_index}" if self.series_index else self.series


def write_tags(
    path: Path,
    book: BookTags,
    cover: bytes | None = None,
    track: tuple[int, int] | None = None,
    track_title: str | None = None,
) -> None:
    suffix = path.suffix.lower()
    try:
        if suffix in (".m4b", ".m4a", ".mp4", ".aac"):
            _write_mp4(path, book, cover, track, track_title)
        elif suffix == ".mp3":
            _write_id3(path, book, cover, track, track_title)
        elif suffix in (".opus", ".ogg", ".oga", ".flac"):
            _write_vorbis(path, book, cover, track, track_title)
    except Exception:  # noqa: BLE001 - tagging must not break a render
        log.exception("Could not write tags to %s", path)


def _cover_mime(cover: bytes) -> str:
    return "image/png" if cover[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def _write_mp4(path, book, cover, track, track_title):
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

    audio = MP4(str(path))
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags

    def put(key: str, value: str) -> None:
        if value:
            tags[key] = [value]
        elif key in tags:
            del tags[key]

    put("\xa9nam", track_title or book.album)
    put("\xa9alb", book.album)
    put("\xa9ART", book.author)
    put("aART", book.author)
    put("\xa9wrt", book.narrator)
    put("\xa9gen", book.genre)
    put("\xa9day", book.year)
    put("desc", book.description[:255])
    put("ldes", book.description)
    put("\xa9cmt", book.description[:255])
    put("\xa9grp", book.grouping)
    put("\xa9mvn", book.series)
    put("cprt", book.publisher)
    if book.series_index:
        try:
            tags["\xa9mvi"] = [int(float(book.series_index))]
        except ValueError:
            pass
    tags["stik"] = [2]  # audiobook
    if track:
        tags["trkn"] = [track]
    freeform = {
        "SERIES": book.series,
        "SERIES-PART": book.series_index,
        "NARRATOR": book.narrator,
        "PUBLISHER": book.publisher,
        "LANGUAGE": book.language,
        "ISBN": book.isbn,
        "SUBTITLE": book.subtitle,
    }
    for name, value in freeform.items():
        key = f"----:com.apple.iTunes:{name}"
        if value:
            tags[key] = [MP4FreeForm(value.encode("utf-8"))]
        elif key in tags:
            del tags[key]
    if cover:
        fmt = MP4Cover.FORMAT_PNG if _cover_mime(cover) == "image/png" else MP4Cover.FORMAT_JPEG
        tags["covr"] = [MP4Cover(cover, imageformat=fmt)]
    audio.save()


def _write_id3(path, book, cover, track, track_title):
    from mutagen.id3 import (
        APIC, COMM, ID3, MVIN, MVNM, TALB, TCOM, TCON, TDRC, TIT1, TIT2, TLAN, TPE1, TPE2, TPUB, TRCK, TXXX,
        ID3NoHeaderError,
    )

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()

    def put(frame_id: str, frame) -> None:
        tags.delall(frame_id)
        if frame is not None:
            tags.add(frame)

    put("TIT2", TIT2(encoding=3, text=track_title or book.album))
    put("TALB", TALB(encoding=3, text=book.album))
    put("TPE1", TPE1(encoding=3, text=book.author) if book.author else None)
    put("TPE2", TPE2(encoding=3, text=book.author) if book.author else None)
    put("TCOM", TCOM(encoding=3, text=book.narrator) if book.narrator else None)
    put("TCON", TCON(encoding=3, text=book.genre) if book.genre else None)
    put("TDRC", TDRC(encoding=3, text=book.year) if book.year else None)
    put("TPUB", TPUB(encoding=3, text=book.publisher) if book.publisher else None)
    put("TLAN", TLAN(encoding=3, text=book.language) if book.language else None)
    put("TIT1", TIT1(encoding=3, text=book.grouping) if book.grouping else None)
    put("MVNM", MVNM(encoding=3, text=book.series) if book.series else None)
    put("MVIN", MVIN(encoding=3, text=book.series_index) if book.series and book.series_index else None)
    put("COMM", COMM(encoding=3, lang="eng", desc="", text=book.description) if book.description else None)
    if track:
        put("TRCK", TRCK(encoding=3, text=f"{track[0]}/{track[1]}"))
    tags.delall("TXXX")
    for name, value in (("SERIES", book.series), ("SERIES-PART", book.series_index), ("NARRATOR", book.narrator),
                        ("ISBN", book.isbn), ("SUBTITLE", book.subtitle)):
        if value:
            tags.add(TXXX(encoding=3, desc=name, text=value))
    if cover:
        put("APIC", APIC(encoding=3, mime=_cover_mime(cover), type=3, desc="Cover", data=cover))
    # Keep chapter frames in playback order for players that ignore CTOC.
    chapters = sorted(tags.getall("CHAP"), key=lambda frame: frame.start_time)
    if chapters:
        tags.delall("CHAP")
        for frame in chapters:
            tags.add(frame)
    tags.save(str(path))


def _write_vorbis(path, book, cover, track, track_title):
    import mutagen
    from mutagen.flac import FLAC, Picture

    audio = mutagen.File(str(path))
    if audio is None:
        return
    if audio.tags is None:
        audio.add_tags()
    values = {
        "title": track_title or book.album,
        "album": book.album,
        "artist": book.author,
        "albumartist": book.author,
        "composer": book.narrator,
        "performer": book.narrator,
        "genre": book.genre,
        "date": book.year,
        "description": book.description,
        "comment": book.description,
        "publisher": book.publisher,
        "language": book.language,
        "series": book.series,
        "series-part": book.series_index,
        "grouping": book.grouping,
        "isbn": book.isbn,
    }
    for key, value in values.items():
        if value:
            audio[key] = [value]
        elif key in audio:
            del audio[key]
    if track:
        audio["tracknumber"] = [str(track[0])]
        audio["tracktotal"] = [str(track[1])]
    if cover:
        picture = Picture()
        picture.type = 3
        picture.mime = _cover_mime(cover)
        picture.desc = "Cover"
        picture.data = cover
        if isinstance(audio, FLAC):
            audio.clear_pictures()
            audio.add_picture(picture)
        else:
            audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
    audio.save()


# ----------------------------------------------------------------------------
# Reading


def _first(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list | tuple):
        value = value[0] if value else ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    text = getattr(value, "text", None)
    if text is not None:
        return _first(text)
    return str(value).strip()


def read_tags(path: Path) -> dict[str, Any]:
    """Best-effort metadata of an audio file (title, album, artist, ...)."""
    import mutagen

    result: dict[str, Any] = {"duration": 0.0}
    try:
        audio = mutagen.File(str(path))
    except Exception:  # noqa: BLE001
        return result
    if audio is None:
        return result
    result["duration"] = float(getattr(audio.info, "length", 0.0) or 0.0)
    tags = audio.tags
    if tags is None:
        return result

    keys = {k.lower() if isinstance(k, str) else k: k for k in tags.keys()}

    def get(*names: str) -> str:
        for name in names:
            real = keys.get(name.lower())
            if real is not None:
                value = _first(tags[real])
                if value:
                    return value
        return ""

    result["title"] = get("\xa9nam", "TIT2", "title")
    result["album"] = get("\xa9alb", "TALB", "album")
    result["artist"] = get("\xa9ART", "TPE1", "artist")
    result["album_artist"] = get("aART", "TPE2", "albumartist", "album artist")
    result["narrator"] = get("\xa9wrt", "TCOM", "composer", "----:com.apple.iTunes:NARRATOR", "TXXX:NARRATOR", "narrator", "performer")
    result["genre"] = get("\xa9gen", "TCON", "genre")
    result["year"] = get("\xa9day", "TDRC", "TYER", "date", "year")[:4]
    result["description"] = get("ldes", "desc", "\xa9cmt", "COMM::eng", "COMM", "description", "comment")
    result["series"] = get("----:com.apple.iTunes:SERIES", "TXXX:SERIES", "\xa9mvn", "MVNM", "series")
    result["series_index"] = get("----:com.apple.iTunes:SERIES-PART", "TXXX:SERIES-PART", "\xa9mvi", "MVIN", "series-part")
    result["publisher"] = get("cprt", "TPUB", "publisher", "organization")
    result["language"] = get("----:com.apple.iTunes:LANGUAGE", "TLAN", "language")
    result["isbn"] = get("----:com.apple.iTunes:ISBN", "TXXX:ISBN", "isbn")
    track = get("trkn", "TRCK", "tracknumber")
    result["track"] = _track_number(tags, keys, track)
    if not result["description"]:
        for key in keys:
            if isinstance(key, str) and key.startswith("comm"):
                result["description"] = _first(tags[keys[key]])
                break
    return result


def _track_number(tags, keys, raw: str) -> int:
    real = keys.get("trkn")
    if real is not None:
        try:
            return int(tags[real][0][0])
        except (IndexError, TypeError, ValueError):
            pass
    try:
        return int(str(raw).split("/")[0])
    except ValueError:
        return 0


def extract_cover(path: Path) -> bytes | None:
    import mutagen

    try:
        audio = mutagen.File(str(path))
    except Exception:  # noqa: BLE001
        return None
    if audio is None:
        return None
    pictures = getattr(audio, "pictures", None)
    if pictures:
        return pictures[0].data
    tags = audio.tags
    if tags is None:
        return None
    try:
        if "covr" in tags and tags["covr"]:
            return bytes(tags["covr"][0])
    except (KeyError, TypeError, ValueError):
        pass
    getall = getattr(tags, "getall", None)
    if getall:
        frames = getall("APIC")
        if frames:
            return frames[0].data
    try:
        blocks = tags.get("metadata_block_picture") if hasattr(tags, "get") else None
        if blocks:
            from mutagen.flac import Picture

            return Picture(base64.b64decode(blocks[0])).data
    except Exception:  # noqa: BLE001
        pass
    return None
