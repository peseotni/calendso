"""Plain text and Markdown parsers (with Project Gutenberg awareness)."""

from __future__ import annotations

import re
from pathlib import Path

from .base import (
    ParsedBook,
    Para,
    chapters_from_paras,
    clean_inline,
    first_year,
    guess_language,
    join_wrapped,
    normalize_language,
)

_GUTENBERG_START = re.compile(r"^\*{3}\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*$", re.MULTILINE | re.IGNORECASE)
_GUTENBERG_END = re.compile(r"^\*{3}\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*$", re.MULTILINE | re.IGNORECASE)
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    return decode_text(raw)


def decode_text(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None:
            return str(best)
    except Exception:  # noqa: BLE001
        pass
    return raw.decode("latin-1")


def split_text_paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    blocks = re.split(r"\n[ \t]*\n", text)
    if len(blocks) <= 2 and text.count("\n") > 20:
        blocks = text.split("\n")  # one paragraph per line
    paragraphs: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if len(lines) >= 3 and max(len(line) for line in lines) < 55:
            paragraphs.append("\n".join(lines))  # verse / poetry: keep the lines
            continue
        joined = lines[0]
        for line in lines[1:]:
            joined = join_wrapped(joined, line)
        paragraphs.append(clean_inline(joined))
    return [p for p in paragraphs if p]


def _gutenberg(text: str, book: ParsedBook) -> str:
    start = _GUTENBERG_START.search(text)
    if not start:
        return text
    header = text[: start.start()]
    fields = {}
    for key in ("Title", "Author", "Language", "Release date", "Release Date"):
        match = re.search(rf"^{key}:\s*(.+)$", header, re.MULTILINE)
        if match:
            fields[key.lower()] = match.group(1).strip()
    book.title = fields.get("title", "")
    if fields.get("author"):
        book.authors = [fields["author"]]
    book.language = normalize_language(fields.get("language", ""))
    book.publisher = "Project Gutenberg"
    body = text[start.end():]
    end = _GUTENBERG_END.search(body)
    if end:
        body = body[: end.start()]
    # Drop "Produced by ..." credits at the very start.
    body = re.sub(r"\A\s*(?:Produced by|E-text prepared by|Transcribed from)[^\n]*(?:\n[^\n]+)*\n", "", body)
    return body


def _title_from_filename(path: Path, book: ParsedBook) -> None:
    stem = re.sub(r"[_]+", " ", path.stem).strip()
    if " - " in stem and not book.title:
        author, title = stem.split(" - ", 1)
        book.title = title.strip()
        if not book.authors:
            book.authors = [author.strip()]
    if not book.title:
        book.title = stem


def strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\^[^\]]+\]", "", text)  # footnote markers
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", text)
    text = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", text)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    return text


def parse_text(path: Path) -> ParsedBook:
    book = ParsedBook()
    text = _gutenberg(read_text_file(path), book)
    paras = [Para(p) for p in split_text_paragraphs(text)]
    book.chapters = chapters_from_paras(paras, fallback_title="Part")
    _title_from_filename(path, book)
    if not book.language:
        book.language = guess_language(text[:60000])
    return book


def parse_markdown(path: Path) -> ParsedBook:
    book = ParsedBook()
    text = read_text_file(path).replace("\r\n", "\n")
    front = _FRONT_MATTER.match(text)
    if front:
        for line in front.group(1).splitlines():
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip().strip("'\"")
            if key == "title":
                book.title = value
            elif key in ("author", "authors") and value:
                book.authors = [a.strip() for a in value.strip("[]").split(",") if a.strip()]
            elif key in ("lang", "language"):
                book.language = normalize_language(value)
            elif key == "date":
                book.year = first_year(value)
            elif key == "description":
                book.description = value
        text = text[front.end():]

    # Remove fenced code blocks entirely.
    text = re.sub(r"^```.*?^```\s*$", "", text, flags=re.MULTILINE | re.DOTALL)
    paras: list[Para] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            for paragraph in split_text_paragraphs(strip_markdown("\n".join(buffer))):
                paras.append(Para(paragraph))
            buffer.clear()

    lines = text.split("\n")
    for i, line in enumerate(lines):
        heading = _MD_HEADING.match(line)
        setext = i + 1 < len(lines) and line.strip() and re.match(r"^\s*(=+|-{3,})\s*$", lines[i + 1])
        if heading:
            flush()
            paras.append(Para(clean_inline(strip_markdown(heading.group(2))), level=len(heading.group(1))))
        elif setext:
            flush()
            level = 1 if lines[i + 1].strip().startswith("=") else 2
            paras.append(Para(clean_inline(strip_markdown(line)), level=level))
        elif re.match(r"^\s*(=+|-{3,}|\*{3,}|_{3,})\s*$", line):
            flush()
            if not (i > 0 and lines[i - 1].strip() and not _MD_HEADING.match(lines[i - 1])):
                paras.append(Para("* * *"))  # thematic break
        else:
            buffer.append(line)
    flush()

    h1 = [p for p in paras if p.level == 1]
    if len(h1) == 1 and paras and paras[0] is h1[0]:
        # A single top-level heading at the start is the document title.
        book.title = book.title or h1[0].text
        paras = paras[1:]
    book.chapters = chapters_from_paras(paras, fallback_title="Part")
    _title_from_filename(path, book)
    if not book.language:
        book.language = guess_language(" ".join(p.text for p in paras[:300]))
    return book


def parse_pasted_text(title: str, text: str, author: str = "") -> ParsedBook:
    book = ParsedBook(title=title or "Untitled", authors=[author] if author else [])
    is_markdown = bool(re.search(r"^#{1,3}\s+\S", text, re.MULTILINE))
    if is_markdown:
        tmp_paras: list[Para] = []
        for block in re.split(r"\n\s*\n", text):
            heading = _MD_HEADING.match(block.strip())
            if heading:
                tmp_paras.append(Para(heading.group(2), level=len(heading.group(1))))
            else:
                tmp_paras.extend(Para(p) for p in split_text_paragraphs(strip_markdown(block)))
        paras = tmp_paras
    else:
        paras = [Para(p) for p in split_text_paragraphs(text)]
    book.chapters = chapters_from_paras(paras, fallback_title="Part")
    if len(book.chapters) == 1 and book.chapters[0].title in ("Full text", "Part 1"):
        book.chapters[0].title = book.title
    book.language = guess_language(text[:60000])
    return book
