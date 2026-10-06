"""Ebook/document ingestion: turn a source file into metadata + chapters."""

from __future__ import annotations

from pathlib import Path

from .base import IngestError, ParsedBook, ParsedChapter, ProgressFn, clean_inline, count_words, normalize_title

FORMATS: dict[str, str] = {
    ".epub": "epub",
    ".pdf": "pdf",
    ".docx": "docx",
    ".odt": "odt",
    ".txt": "txt",
    ".text": "txt",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".fb2": "fb2",
    ".mobi": "mobi",
    ".azw": "mobi",
    ".azw3": "mobi",
    ".prc": "mobi",
}
FORMAT_LABELS = {
    "epub": "EPUB",
    "pdf": "PDF",
    "docx": "Word",
    "odt": "OpenDocument",
    "txt": "Text",
    "markdown": "Markdown",
    "html": "HTML",
    "fb2": "FictionBook",
    "mobi": "Kindle",
}


def detect_format(filename: str) -> str | None:
    name = filename.lower()
    if name.endswith(".fb2.zip"):
        return "fb2"
    return FORMATS.get(Path(name).suffix)


def supported_extensions() -> list[str]:
    return sorted(set(FORMATS) | {".fb2.zip"})


def parse_book(
    path: Path,
    fmt: str,
    progress: ProgressFn | None = None,
    options: dict | None = None,
) -> ParsedBook:
    options = options or {}
    if fmt == "epub":
        from .epub import parse_epub

        book = parse_epub(path, progress)
    elif fmt == "pdf":
        from .pdf import parse_pdf

        book = parse_pdf(path, progress, options)
    elif fmt == "docx":
        from .office import parse_docx

        book = parse_docx(path)
    elif fmt == "odt":
        from .office import parse_odt

        book = parse_odt(path)
    elif fmt == "txt":
        from .plain import parse_text

        book = parse_text(path)
    elif fmt == "markdown":
        from .plain import parse_markdown

        book = parse_markdown(path)
    elif fmt == "html":
        from .html import parse_html_file

        book = parse_html_file(path)
    elif fmt == "fb2":
        from .fb2 import parse_fb2

        book = parse_fb2(path)
    elif fmt == "mobi":
        from .kindle import parse_mobi

        book = parse_mobi(path, progress)
    else:
        raise IngestError(f"Unsupported file format: {path.suffix}")
    return finalize(book)


_CONTENTS = {"contents", "table of contents", "inhalt", "inhaltsverzeichnis", "sommaire", "indice", "contenido"}


def _is_toc_remnant(index: int, chapter: ParsedChapter, titles: list[str]) -> bool:
    """A chapter that only lists other chapters' titles (an inline table of contents)."""
    paragraphs = [normalize_title(p) for p in chapter.text.split("\n\n") if p.strip()]
    paragraphs = [p for p in paragraphs if p not in _CONTENTS]
    if not paragraphs or count_words(chapter.text) > 300:
        return False
    others = {t for i, t in enumerate(titles) if i != index and t}
    return sum(1 for p in paragraphs if p in others) >= max(1, round(len(paragraphs) * 0.8))


def finalize(book: ParsedBook) -> ParsedBook:
    """Normalise parser output: trim titles, drop empty chapters and TOC remnants."""
    titles = [normalize_title(c.title) for c in book.chapters]
    chapters: list[ParsedChapter] = []
    for index, chapter in enumerate(book.chapters):
        text = chapter.text.strip()
        if not text or count_words(text) == 0:
            continue
        if _is_toc_remnant(index, chapter, titles):
            continue
        title = clean_inline(chapter.title).replace("\n", " ")[:200] or f"Chapter {len(chapters) + 1}"
        chapters.append(ParsedChapter(title=title, text=text, kind=chapter.kind, include=chapter.include))
    if not chapters:
        raise IngestError("No readable text was found in this document.")
    if not any(c.include for c in chapters):
        for c in chapters:
            c.include = True
    book.chapters = chapters
    book.title = clean_inline(book.title).replace("\n", " ")[:300]
    book.authors = [clean_inline(a) for a in book.authors if clean_inline(a)]
    return book


__all__ = [
    "FORMATS",
    "FORMAT_LABELS",
    "IngestError",
    "ParsedBook",
    "ParsedChapter",
    "detect_format",
    "parse_book",
    "supported_extensions",
]
