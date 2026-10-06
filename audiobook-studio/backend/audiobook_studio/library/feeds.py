"""Podcast-style RSS feeds so audiobooks can be played in any podcast app."""

from __future__ import annotations

import mimetypes
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import quote
from xml.sax.saxutils import escape

from ..models import Book

MIME = {".m4b": "audio/x-m4b", ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".opus": "audio/ogg", ".ogg": "audio/ogg", ".flac": "audio/flac"}


def _duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _mime(path: str) -> str:
    for ext, mime in MIME.items():
        if path.lower().endswith(ext):
            return mime
    return mimetypes.guess_type(path)[0] or "audio/mpeg"


def _date(value: datetime | None, offset_minutes: int = 0) -> str:
    value = (value or datetime.now(timezone.utc).replace(tzinfo=None)).replace(tzinfo=timezone.utc)
    return format_datetime(value + timedelta(minutes=offset_minutes))


def _channel(title: str, description: str, link: str, image: str, author: str, items: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:podcast="https://podcastindex.org/namespace/1.0">\n<channel>\n'
        f"<title>{escape(title)}</title>\n<link>{escape(link)}</link>\n"
        f"<description>{escape(description or title)}</description>\n"
        f"<itunes:author>{escape(author)}</itunes:author>\n"
        "<itunes:explicit>false</itunes:explicit>\n<itunes:type>serial</itunes:type>\n"
        + (f'<itunes:image href="{escape(image)}"/>\n<image><url>{escape(image)}</url><title>{escape(title)}</title>'
           f"<link>{escape(link)}</link></image>\n" if image else "")
        + "".join(items)
        + "</channel>\n</rss>\n"
    )


def _item(title: str, guid: str, url: str, path: str, size: int, duration: float, published: str,
          description: str, image: str, episode: int | None = None) -> str:
    return (
        "<item>\n"
        f"<title>{escape(title)}</title>\n<guid isPermaLink=\"false\">{escape(guid)}</guid>\n"
        f'<enclosure url="{escape(url)}" length="{int(size or 0)}" type="{_mime(path)}"/>\n'
        f"<pubDate>{published}</pubDate>\n<itunes:duration>{_duration(duration)}</itunes:duration>\n"
        f"<description>{escape(description or title)}</description>\n"
        + (f"<itunes:episode>{episode}</itunes:episode>\n" if episode else "")
        + (f'<itunes:image href="{escape(image)}"/>\n' if image else "")
        + "</item>\n"
    )


def book_feed(book: Book, base_url: str, token: str) -> str:
    query = f"?token={quote(token)}" if token else ""
    image = f"{base_url}/api/books/{book.id}/cover{query}" if book.cover_path else ""
    items = []
    for index, entry in enumerate(book.files or []):
        url = f"{base_url}/api/books/{book.id}/files/{index}{query}"
        items.append(_item(
            title=entry.get("title") or f"Part {index + 1}",
            guid=f"book-{book.id}-file-{index}",
            url=url,
            path=entry["path"],
            size=entry.get("size", 0),
            duration=entry.get("duration", 0),
            # Older parts get older dates so podcast apps keep the order.
            published=_date(book.added_at, offset_minutes=index),
            description=book.description[:4000],
            image=image,
            episode=index + 1,
        ))
    title = f"{book.title} – {book.author}" if book.author else book.title
    return _channel(title, book.description, f"{base_url}/library/{book.id}", image, book.author or "", items)


def library_feed(books: list[Book], base_url: str, token: str, title: str = "Audiobook Studio Library") -> str:
    query = f"?token={quote(token)}" if token else ""
    items = []
    for book in books:
        if not book.files or len(book.files) != 1:
            continue  # multi-file books have their own per-book feed
        entry = book.files[0]
        image = f"{base_url}/api/books/{book.id}/cover{query}" if book.cover_path else ""
        items.append(_item(
            title=f"{book.title} – {book.author}" if book.author else book.title,
            guid=f"book-{book.id}",
            url=f"{base_url}/api/books/{book.id}/files/0{query}",
            path=entry["path"],
            size=entry.get("size", 0),
            duration=book.duration,
            published=_date(book.added_at),
            description=book.description[:4000],
            image=image,
        ))
    return _channel(title, "All single-file audiobooks in your library.", f"{base_url}/library", "", "Audiobook Studio", items)
