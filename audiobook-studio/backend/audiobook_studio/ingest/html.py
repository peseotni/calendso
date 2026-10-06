"""(X)HTML text extraction shared by the EPUB, MOBI and HTML parsers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree, html as lxml_html

from .base import ParsedBook, Para, chapters_from_paras, clean_inline, guess_language, normalize_language

BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "section",
    "article", "header", "footer", "aside", "figure", "figcaption", "table", "tr", "dt",
    "dd", "ul", "ol", "dl", "main", "body", "hr", "address", "center", "caption", "tbody",
    "thead", "tfoot", "nav", "details", "summary", "hgroup",
}
HEADING_LEVEL = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIP_TAGS = {
    "script", "style", "head", "title", "noscript", "svg", "math", "rt", "rp", "iframe",
    "object", "audio", "video", "template", "button", "select", "input", "textarea", "form",
    "img", "image", "canvas", "map",
}
_NOTE_TYPES = ("footnote", "endnote", "rearnote", "noteref", "pagebreak", "footnotes", "endnotes")
_NOTE_ROLES = ("doc-footnote", "doc-endnote", "doc-noteref", "doc-pagebreak", "doc-endnotes")
_NOTE_MARK_RE = re.compile(r"^\s*[\[(]?(?:\d{1,3}|[ivxlc]{1,5}|[*†‡§¶#]+|[a-z])[\])]?\s*$", re.IGNORECASE)


@dataclass
class Block:
    text: str
    level: int = 0  # heading level, 0 for body text
    ids: set[str] = field(default_factory=set)


def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _epub_type(el: etree._Element) -> str:
    for key, value in el.attrib.items():
        # "epub:type" with the HTML parser, "{http://www.idpf.org/2007/ops}type" with XML
        if key == "epub:type" or (key.startswith("{") and key.endswith("}type")):
            return value or ""
    return ""


def _skip_element(el: etree._Element, tag: str) -> bool:
    if tag in SKIP_TAGS:
        return True
    epub_type = _epub_type(el).lower()
    role = (el.get("role") or "").lower()
    if any(t in epub_type.split() for t in _NOTE_TYPES) or role in _NOTE_ROLES:
        return True
    classes = set((el.get("class") or "").lower().split())
    if classes & {"footnotes", "endnotes", "pagenum", "page-number", "pagebreak", "noteref"}:
        return True
    if el.get("hidden") is not None:
        return True
    style = (el.get("style") or "").replace(" ", "").lower()
    if "display:none" in style or "visibility:hidden" in style:
        return True
    if tag in ("sup", "a"):
        text = "".join(el.itertext())
        href = el.get("href") or ""
        if tag == "sup" and _NOTE_MARK_RE.match(text or ""):
            return True
        if tag == "a" and "#" in href and _NOTE_MARK_RE.match(text or ""):
            return True
    return False


class _Extractor:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.buf: list[str] = []
        self.ids: set[str] = set()
        self.pending_ids: set[str] = set()
        self.level_stack: list[int] = [0]

    def flush(self) -> None:
        text = clean_inline("".join(self.buf))
        if text:
            self.blocks.append(Block(text=text, level=self.level_stack[-1], ids=self.ids | self.pending_ids))
            self.pending_ids = set()
        else:
            self.pending_ids |= self.ids
        self.buf = []
        self.ids = set()

    def walk(self, el: etree._Element) -> None:
        tag = _local(el.tag)
        if not tag:  # comments, processing instructions
            if el.tail:
                self.buf.append(el.tail)
            return
        if _skip_element(el, tag):
            if el.tail:
                self.buf.append(el.tail)
            return

        anchor = el.get("id") or (el.get("name") if tag == "a" else None)
        is_block = tag in BLOCK_TAGS
        if is_block:
            self.flush()
            # Block elements nested in a heading keep the heading level.
            self.level_stack.append(HEADING_LEVEL.get(tag, 0) or self.level_stack[-1])
        if anchor:
            self.ids.add(anchor)
        if tag == "br":
            self.buf.append("\n")
        elif tag in ("td", "th"):
            self.buf.append(" ")
        if el.text:
            self.buf.append(el.text)
        for child in el:
            self.walk(child)
        if tag in ("td", "th"):
            self.buf.append(", ")
        if is_block:
            self.flush()
            self.level_stack.pop()
        if el.tail:
            self.buf.append(el.tail)


_XML_DECL_RE = re.compile(rb"^\s*<\?xml[^>]*?encoding=[\"']([\w.:-]+)[\"'][^>]*\?>", re.IGNORECASE)
_META_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", re.IGNORECASE)


def _detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8"
    for pattern in (_XML_DECL_RE, _META_CHARSET_RE):
        match = pattern.search(data[:2048])
        if match:
            name = match.group(1).decode("ascii", "ignore").lower()
            try:
                "".encode(name)
                return name
            except LookupError:
                break
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def parse_html_document(data: bytes | str) -> etree._Element:
    if isinstance(data, str):
        data = data.encode("utf-8")
    encoding = _detect_encoding(data)
    # Strip the XML declaration, lxml's HTML parser dislikes some of them.
    data = re.sub(rb"^\s*(?:\xef\xbb\xbf)?<\?xml[^>]*\?>", b"", data)
    parser = lxml_html.HTMLParser(encoding=encoding, remove_comments=True)
    try:
        return lxml_html.document_fromstring(data, parser=parser)
    except (etree.ParserError, ValueError, LookupError):
        return lxml_html.document_fromstring(b"<html><body></body></html>")


def extract_blocks(data: bytes | str | etree._Element) -> list[Block]:
    root = data if isinstance(data, etree._Element) else parse_html_document(data)
    body = root.find(".//body")
    if body is None:
        body = root
    extractor = _Extractor()
    extractor.walk(body)
    extractor.flush()
    return extractor.blocks


def document_title(root: etree._Element) -> str:
    title = root.findtext(".//title") or ""
    return clean_inline(title)


def parse_html_file(path: Path) -> ParsedBook:
    data = path.read_bytes()
    root = parse_html_document(data)
    blocks = extract_blocks(root)
    book = ParsedBook()
    book.title = document_title(root)
    h1 = next((b.text for b in blocks if b.level == 1), "")
    if not book.title or book.title.lower() in ("untitled", "document"):
        book.title = h1 or path.stem
    for meta in root.iter("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        content = (meta.get("content") or "").strip()
        if not content:
            continue
        if name in ("author", "dc.creator", "article:author", "book:author"):
            book.authors.append(content)
        elif name in ("description", "og:description", "dc.description") and not book.description:
            book.description = content
        elif name in ("keywords",):
            book.subjects = [k.strip() for k in content.split(",") if k.strip()][:10]
    book.language = normalize_language(root.get("lang") or "")

    paras = [Para(text=b.text, level=b.level) for b in blocks]
    # A single <h1> at the very start is the document title, not a chapter.
    if sum(1 for p in paras if p.level == 1) == 1 and paras and paras[0].level == 1:
        paras = paras[1:]
    book.chapters = chapters_from_paras(paras, fallback_title="Part")
    if not book.language:
        book.language = guess_language(" ".join(p.text for p in paras[:300]))
    return book
