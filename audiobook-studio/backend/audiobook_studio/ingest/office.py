"""Word (.docx) and OpenDocument (.odt) parsers."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

from .base import (
    IngestError,
    ParsedBook,
    Para,
    chapters_from_paras,
    clean_inline,
    first_year,
    guess_language,
    normalize_language,
)

_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=True)


def parse_docx(path: Path) -> ParsedBook:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise IngestError("DOCX support requires the 'python-docx' package.") from exc
    try:
        document = docx.Document(str(path))
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Could not open Word document: {exc}") from exc

    book = ParsedBook()
    props = document.core_properties
    book.title = clean_inline(props.title or "")
    if props.author:
        book.authors = [clean_inline(props.author)]
    book.language = normalize_language(props.language or "")
    book.description = clean_inline(props.subject or props.comments or "")
    if props.keywords:
        book.subjects = [k.strip() for k in re.split(r"[,;]", props.keywords) if k.strip()][:10]
    if props.created:
        book.year = str(props.created.year)

    paras: list[Para] = []
    for paragraph in document.paragraphs:
        text = clean_inline(paragraph.text)
        if not text:
            continue
        style = (paragraph.style.name if paragraph.style is not None else "").lower()
        if style == "title":
            book.title = book.title or text
            continue
        if style == "subtitle":
            book.subtitle = book.subtitle or text
            continue
        match = re.match(r"heading\s*(\d)", style)
        level = int(match.group(1)) if match else 0
        paras.append(Para(text=text, level=level))

    book.chapters = chapters_from_paras(paras, fallback_title="Part")
    if not book.title:
        book.title = re.sub(r"[_]+", " ", path.stem)
    if not book.language:
        book.language = guess_language(" ".join(p.text for p in paras[:300]))
    return book


_ODT = {
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "dc": "http://purl.org/dc/elements/1.1/",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
}


def _odt_text(el: etree._Element) -> str:
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        tag = node.tag if isinstance(node.tag, str) else ""
        local = tag.rsplit("}", 1)[-1]
        if local in ("note", "annotation", "bookmark-ref", "tracked-changes"):
            if node.tail:
                parts.append(node.tail)
            return
        if local == "s":
            parts.append(" " * int(node.get(f"{{{_ODT['text']}}}c", "1")))
        elif local == "tab":
            parts.append(" ")
        elif local == "line-break":
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
        if node is not el and node.tail:
            parts.append(node.tail)

    walk(el)
    return clean_inline("".join(parts))


def parse_odt(path: Path) -> ParsedBook:
    try:
        archive = zipfile.ZipFile(path)
        content = etree.fromstring(archive.read("content.xml"), _XML_PARSER)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise IngestError("This is not a valid OpenDocument text file.") from exc

    book = ParsedBook()
    try:
        meta = etree.fromstring(archive.read("meta.xml"), _XML_PARSER)
        book.title = clean_inline(meta.findtext(".//dc:title", "", _ODT))
        creator = meta.findtext(".//meta:initial-creator", "", _ODT) or meta.findtext(".//dc:creator", "", _ODT)
        if creator.strip():
            book.authors = [clean_inline(creator)]
        book.language = normalize_language(meta.findtext(".//dc:language", "", _ODT))
        book.description = clean_inline(meta.findtext(".//dc:description", "", _ODT))
        book.subjects = [clean_inline(k.text or "") for k in meta.iterfind(".//meta:keyword", _ODT) if k.text][:10]
        book.year = first_year(meta.findtext(".//meta:creation-date", "", _ODT))
    except KeyError:
        pass

    body = content.find(".//office:text", _ODT)
    paras: list[Para] = []
    if body is not None:
        for el in body.iter(f"{{{_ODT['text']}}}h", f"{{{_ODT['text']}}}p"):
            # Skip paragraphs nested inside notes / other paragraphs.
            parent = el.getparent()
            if parent is not None and parent.tag.rsplit("}", 1)[-1] in ("note-body", "p", "h"):
                continue
            text = _odt_text(el)
            if not text:
                continue
            level = 0
            if el.tag.endswith("}h"):
                level = int(el.get(f"{{{_ODT['text']}}}outline-level", "1") or 1)
            style = (el.get(f"{{{_ODT['text']}}}style-name") or "").lower()
            if style == "title":
                book.title = book.title or text
                continue
            paras.append(Para(text=text, level=level))

    book.chapters = chapters_from_paras(paras, fallback_title="Part")
    if not book.title:
        book.title = re.sub(r"[_]+", " ", path.stem)
    if not book.language:
        book.language = guess_language(" ".join(p.text for p in paras[:300]))
    return book
