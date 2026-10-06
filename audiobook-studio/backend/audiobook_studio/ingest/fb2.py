"""FictionBook 2 (.fb2 / .fb2.zip) parser."""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

from lxml import etree

from .base import (
    IngestError,
    ParsedBook,
    ParsedChapter,
    clean_inline,
    extract_isbn,
    first_year,
    guess_language,
    looks_like_front_matter,
    normalize_language,
)

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=True)

_GENRES = {
    "sf": "Science Fiction", "fantasy": "Fantasy", "det": "Mystery", "thriller": "Thriller",
    "prose": "Fiction", "love": "Romance", "adv": "Adventure", "child": "Children",
    "poetry": "Poetry", "dramaturgy": "Drama", "antique": "Classics", "sci": "Science",
    "comp": "Computers", "ref": "Reference", "nonf": "Nonfiction", "religion": "Religion",
    "humor": "Humor", "home": "Home & Garden", "history": "History", "horror": "Horror",
}


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(el: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in el if _local(c.tag) == name]


def _child(el: etree._Element | None, name: str) -> etree._Element | None:
    if el is None:
        return None
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el: etree._Element | None) -> str:
    if el is None:
        return ""
    # Drop footnote links before reading text.
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        if _local(node.tag) == "a" and (node.get("type") == "note"):
            if node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
        if node is not el and node.tail:
            parts.append(node.tail)

    walk(el)
    return clean_inline("".join(parts))


def _block_paragraphs(el: etree._Element) -> list[str]:
    """Paragraph texts of a section element (excluding nested sections)."""
    result: list[str] = []
    for child in el:
        name = _local(child.tag)
        if name in ("section", "title", "image"):
            continue
        if name in ("p", "subtitle", "text-author"):
            text = _text(child)
            if text:
                result.append(text)
        elif name == "poem":
            for stanza in child.iter():
                if _local(stanza.tag) == "stanza":
                    lines = [_text(v) for v in stanza if _local(v.tag) == "v"]
                    if any(lines):
                        result.append("\n".join(line for line in lines if line))
                elif _local(stanza.tag) == "title":
                    pass
        elif name in ("epigraph", "cite", "annotation"):
            result.extend(_block_paragraphs(child))
        elif name == "table":
            for row in child.iter():
                if _local(row.tag) == "tr":
                    cells = [_text(c) for c in row]
                    if any(cells):
                        result.append(", ".join(c for c in cells if c))
    return result


def _title_of(section: etree._Element) -> str:
    title = _child(section, "title")
    if title is None:
        return ""
    lines = [_text(p) for p in title if _local(p.tag) in ("p", "subtitle")]
    return ": ".join(line for line in lines if line) or _text(title)


def parse_fb2(path: Path) -> ParsedBook:
    data = path.read_bytes()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".fb2")]
            if not names:
                raise IngestError("The archive does not contain an .fb2 file.")
            data = archive.read(names[0])
    try:
        root = etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise IngestError(f"Invalid FB2 file: {exc}") from exc
    if root is None:
        raise IngestError("Invalid FB2 file.")

    book = ParsedBook()
    description = _child(root, "description")
    info = _child(description, "title-info")
    if info is not None:
        book.title = _text(_child(info, "book-title"))
        for author in _children(info, "author"):
            parts = [_text(_child(author, n)) for n in ("first-name", "middle-name", "last-name")]
            name = " ".join(p for p in parts if p) or _text(_child(author, "nickname"))
            if name:
                book.authors.append(name)
        genres = [_text(g) for g in _children(info, "genre")]
        readable = []
        for code in genres:
            label = _GENRES.get(code) or _GENRES.get(code.split("_")[0])
            if label and label not in readable:
                readable.append(label)
        book.subjects = readable or [g for g in genres if g]
        annotation = _child(info, "annotation")
        if annotation is not None:
            book.description = "\n\n".join(_block_paragraphs(annotation))
        book.language = normalize_language(_text(_child(info, "lang")))
        date = _child(info, "date")
        if date is not None:
            book.year = first_year(date.get("value") or _text(date))
        sequence = _child(info, "sequence")
        if sequence is not None:
            book.series = sequence.get("name") or ""
            book.series_index = sequence.get("number") or ""
        cover_page = _child(info, "coverpage")
        if cover_page is not None:
            image = _child(cover_page, "image")
            if image is not None:
                href = next((v for k, v in image.attrib.items() if k.endswith("href")), "")
                book.cover = _binary(root, href.lstrip("#"))
    publish = _child(description, "publish-info")
    if publish is not None:
        book.publisher = _text(_child(publish, "publisher"))
        book.year = book.year or first_year(_text(_child(publish, "year")))
        book.isbn = extract_isbn(_text(_child(publish, "isbn")))

    bodies = [b for b in _children(root, "body") if (b.get("name") or "") not in ("notes", "comments", "footnotes")]
    chapters: list[ParsedChapter] = []
    for body in bodies:
        intro = _block_paragraphs(body)
        if intro:
            chapters.append(ParsedChapter(title=_title_of(body) or "Introduction", text="\n\n".join(intro), kind="front"))
        for section in _children(body, "section"):
            _walk_section(section, chapters)
    if not chapters:
        raise IngestError("No text found in this FB2 file.")
    for chapter in chapters:
        if looks_like_front_matter(chapter.title, chapter.text):
            chapter.include = False
    book.chapters = chapters
    if not book.title:
        book.title = path.stem
    if not book.language:
        book.language = guess_language(" ".join(c.text[:2000] for c in chapters[:5]))
    return book


def _walk_section(section: etree._Element, chapters: list[ParsedChapter]) -> None:
    title = _title_of(section)
    paragraphs = _block_paragraphs(section)
    subsections = _children(section, "section")
    if paragraphs or (title and subsections):
        text = "\n\n".join(([title] if title else []) + paragraphs)
        chapters.append(ParsedChapter(title=title or f"Section {len(chapters) + 1}", text=text))
    for sub in subsections:
        _walk_section(sub, chapters)


def _binary(root: etree._Element, binary_id: str) -> bytes | None:
    for binary in _children(root, "binary"):
        if binary.get("id") == binary_id and binary.text:
            try:
                return base64.b64decode(binary.text)
            except ValueError:
                return None
    return None
