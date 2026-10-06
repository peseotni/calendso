"""EPUB 2/3 parser: metadata, cover, spine and table-of-contents based chapters."""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from .base import (
    FRONT_MATTER_RE,
    IngestError,
    ParsedBook,
    ParsedChapter,
    ProgressFn,
    clean_inline,
    count_words,
    extract_isbn,
    first_year,
    guess_language,
    looks_like_front_matter,
    normalize_language,
    normalize_title,
    strip_html,
)
from .html import Block, document_title, extract_blocks, parse_html_document

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=True)
_HTML_TYPES = {"application/xhtml+xml", "text/html", "application/x-dtbook+xml"}
BACK_MATTER_RE = re.compile(
    r"^\s*(index|bibliography|references|endnotes|notes|glossary|also by|copyright|colophon)\b",
    re.IGNORECASE,
)


@dataclass
class ManifestItem:
    id: str
    href: str
    media_type: str
    properties: str


@dataclass
class TocEntry:
    title: str
    href: str
    fragment: str
    depth: int


class _Zip:
    def __init__(self, path: Path):
        try:
            self.zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise IngestError("This file is not a valid EPUB (it is not a zip archive).") from exc
        self.names = set(self.zf.namelist())
        self.lower = {name.lower(): name for name in self.names}

    def resolve(self, name: str) -> str | None:
        name = name.lstrip("/")
        if name in self.names:
            return name
        return self.lower.get(name.lower())

    def read(self, name: str) -> bytes | None:
        real = self.resolve(name)
        if real is None:
            return None
        return self.zf.read(real)

    def xml(self, name: str) -> etree._Element | None:
        data = self.read(name)
        if data is None:
            return None
        try:
            return etree.fromstring(data, _XML_PARSER)
        except etree.XMLSyntaxError:
            return None


def _join(base: str, href: str) -> tuple[str, str]:
    href = unquote(href.strip())
    path, _, fragment = href.partition("#")
    if not path:
        return base, fragment
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), path)), fragment


def _check_drm(z: _Zip) -> None:
    if z.resolve("META-INF/rights.xml"):
        raise IngestError("This EPUB is DRM-protected and cannot be converted.")
    enc = z.xml("META-INF/encryption.xml")
    if enc is None:
        return
    for ref in enc.iter("{*}CipherReference"):
        uri = (ref.get("URI") or "").lower()
        if uri.endswith((".html", ".xhtml", ".htm", ".xml")):
            raise IngestError("This EPUB is DRM-protected and cannot be converted.")


def _opf_path(z: _Zip) -> str:
    container = z.xml("META-INF/container.xml")
    if container is not None:
        rootfile = container.find(".//c:rootfile", NS)
        if rootfile is None:
            rootfile = container.find(".//{*}rootfile")
        if rootfile is not None and rootfile.get("full-path"):
            return rootfile.get("full-path")
    for name in z.names:
        if name.lower().endswith(".opf"):
            return name
    raise IngestError("Invalid EPUB: no package document (.opf) found.")


def _text(el: etree._Element | None) -> str:
    if el is None:
        return ""
    return clean_inline("".join(el.itertext()))


def _parse_metadata(opf: etree._Element, book: ParsedBook) -> None:
    md = opf.find("opf:metadata", NS)
    if md is None:
        md = opf.find(".//{*}metadata")
    if md is None:
        return

    refines: dict[str, dict[str, str]] = {}
    for meta in md.findall("{*}meta"):
        target = (meta.get("refines") or "").lstrip("#")
        prop = meta.get("property")
        if target and prop:
            refines.setdefault(target, {})[prop] = _text(meta)

    titles = md.findall("dc:title", NS)
    for title in titles:
        kind = refines.get(title.get("id") or "", {}).get("title-type", "")
        if kind == "subtitle" and not book.subtitle:
            book.subtitle = _text(title)
        elif not book.title and kind in ("", "main"):
            book.title = _text(title)
    if not book.title and titles:
        book.title = _text(titles[0])

    narrators: list[str] = []
    for creator in md.findall("dc:creator", NS):
        name = _text(creator)
        if not name:
            continue
        role = creator.get(f"{{{NS['opf']}}}role") or refines.get(creator.get("id") or "", {}).get("role", "")
        role = role.lower()
        if role in ("", "aut"):
            book.authors.append(name)
        elif role == "nrt":
            narrators.append(name)
    if not book.authors:
        book.authors = [_text(c) for c in md.findall("dc:contributor", NS) if _text(c)][:1]

    book.language = normalize_language(_text(md.find("dc:language", NS)))
    book.publisher = _text(md.find("dc:publisher", NS))
    book.year = first_year(_text(md.find("dc:date", NS)))
    book.description = strip_html(_text(md.find("dc:description", NS)) or "")
    book.subjects = [s for s in (_text(x) for x in md.findall("dc:subject", NS)) if s][:15]
    for ident in md.findall("dc:identifier", NS):
        scheme = (ident.get(f"{{{NS['opf']}}}scheme") or "").lower()
        value = _text(ident)
        isbn = extract_isbn(value) if (scheme == "isbn" or "isbn" in value.lower() or value[:3] in ("978", "979")) else ""
        if isbn:
            book.isbn = isbn
            break

    for meta in md.findall("{*}meta"):
        name = meta.get("name") or ""
        prop = meta.get("property") or ""
        if name == "calibre:series":
            book.series = meta.get("content") or ""
        elif name == "calibre:series_index":
            book.series_index = _format_index(meta.get("content") or "")
        elif prop == "belongs-to-collection" and not book.series:
            book.series = _text(meta)
            extra = refines.get(meta.get("id") or "", {})
            book.series_index = _format_index(extra.get("group-position", ""))
    if narrators:
        book.warnings.append("Narrator in source metadata: " + ", ".join(narrators))


def _format_index(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value.strip()
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _parse_nav(z: _Zip, nav_href: str) -> list[TocEntry]:
    data = z.read(nav_href)
    if data is None:
        return []
    root = parse_html_document(data)
    navs = list(root.iter("nav"))
    toc_nav = None
    for nav in navs:
        types = " ".join(v for k, v in nav.attrib.items() if k.endswith("type")).lower()
        if "toc" in types.split():
            toc_nav = nav
            break
    if toc_nav is None and navs:
        toc_nav = navs[0]
    if toc_nav is None:
        return []
    entries: list[TocEntry] = []

    def walk(ol: etree._Element, depth: int) -> None:
        for li in ol.findall("li"):
            link = li.find("a")
            label = link if link is not None else li.find("span")
            title = _text(label)
            href = link.get("href") if link is not None else None
            if href and title:
                path, fragment = _join(nav_href, href)
                entries.append(TocEntry(title, path, fragment, depth))
            for child in li.findall("ol"):
                walk(child, depth + 1)

    for ol in toc_nav.findall("ol"):
        walk(ol, 1)
    return entries


def _parse_ncx(z: _Zip, ncx_href: str) -> list[TocEntry]:
    ncx = z.xml(ncx_href)
    if ncx is None:
        return []
    nav_map = ncx.find(".//{*}navMap")
    if nav_map is None:
        return []
    entries: list[TocEntry] = []

    def walk(parent: etree._Element, depth: int) -> None:
        for point in parent.findall("{*}navPoint"):
            title = _text(point.find("{*}navLabel/{*}text"))
            content = point.find("{*}content")
            src = content.get("src") if content is not None else None
            if src and title:
                path, fragment = _join(ncx_href, src)
                entries.append(TocEntry(title, path, fragment, depth))
            walk(point, depth + 1)

    walk(nav_map, 1)
    return entries


def _find_cover(z: _Zip, opf: etree._Element, manifest: dict[str, ManifestItem], spine: list[ManifestItem]) -> bytes | None:
    candidates: list[str] = []
    for item in manifest.values():
        if "cover-image" in item.properties.split():
            candidates.append(item.href)
    for meta in opf.iter("{*}meta"):
        if meta.get("name") == "cover":
            item = manifest.get(meta.get("content") or "")
            if item and item.media_type.startswith("image/"):
                candidates.append(item.href)
    for item in manifest.values():
        if item.media_type.startswith("image/") and "cover" in (item.id + item.href).lower():
            candidates.append(item.href)
    # Cover page: first image of the first spine document
    if spine:
        data = z.read(spine[0].href)
        if data:
            root = parse_html_document(data)
            for img in root.iter("img", "image"):
                src = img.get("src") or img.get("{http://www.w3.org/1999/xlink}href") or img.get("xlink:href")
                if src:
                    candidates.append(_join(spine[0].href, src)[0])
                    break
    for href in candidates:
        data = z.read(href)
        if data and len(data) > 1000:
            return data
    return None


def _chapter_title_from_blocks(blocks: list[Block]) -> str:
    headings: list[str] = []
    for block in blocks[:3]:
        if block.level and count_words(block.text) <= 15:
            headings.append(block.text)
        else:
            break
    return ": ".join(headings[:2])


def parse_epub(path: Path, progress: ProgressFn | None = None) -> ParsedBook:
    z = _Zip(path)
    _check_drm(z)
    opf_path = _opf_path(z)
    opf = z.xml(opf_path)
    if opf is None:
        raise IngestError("Invalid EPUB: the package document could not be read.")

    book = ParsedBook()
    _parse_metadata(opf, book)

    manifest: dict[str, ManifestItem] = {}
    for item in opf.iter("{*}item"):
        item_id, href = item.get("id"), item.get("href")
        if not item_id or not href:
            continue
        manifest[item_id] = ManifestItem(
            id=item_id,
            href=_join(opf_path, href)[0],
            media_type=(item.get("media-type") or "").lower(),
            properties=item.get("properties") or "",
        )

    spine_el = opf.find(".//{*}spine")
    spine: list[ManifestItem] = []
    if spine_el is not None:
        for ref in spine_el.findall("{*}itemref"):
            item = manifest.get(ref.get("idref") or "")
            if item is None or (ref.get("linear") or "").lower() == "no":
                continue
            if item.media_type in _HTML_TYPES or item.href.lower().endswith((".xhtml", ".html", ".htm")):
                spine.append(item)
    if not spine:
        raise IngestError("This EPUB has no readable content documents.")

    toc: list[TocEntry] = []
    nav = next((i for i in manifest.values() if "nav" in i.properties.split()), None)
    if nav is not None:
        toc = _parse_nav(z, nav.href)
    if not toc and spine_el is not None and spine_el.get("toc") in manifest:
        toc = _parse_ncx(z, manifest[spine_el.get("toc")].href)
    if not toc:
        ncx = next((i for i in manifest.values() if i.media_type == "application/x-dtbncx+xml"), None)
        if ncx is not None:
            toc = _parse_ncx(z, ncx.href)

    book.cover = _find_cover(z, opf, manifest, spine)

    # Extract text blocks of every spine document.
    docs: list[list[Block]] = []
    doc_titles: list[str] = []
    for n, item in enumerate(spine):
        data = z.read(item.href) or b""
        root = parse_html_document(data)
        docs.append([b for b in extract_blocks(root) if b.level >= 0])
        doc_titles.append(document_title(root))
        if progress:
            progress(0.1 + 0.8 * (n + 1) / len(spine), f"Reading section {n + 1} of {len(spine)}")

    book.chapters = _build_chapters(spine, docs, doc_titles, toc)
    if not book.chapters:
        raise IngestError("No text could be extracted from this EPUB (is it image-only?).")
    if not book.language:
        sample = " ".join(c.text[:3000] for c in book.chapters[:5])
        book.language = guess_language(sample)
    if not book.title:
        book.title = path.stem
    return book


CONTENTS_TITLES = {"contents", "table of contents", "inhalt", "inhaltsverzeichnis", "sommaire", "table des matieres",
                   "indice", "contenido", "inhoud", "spis tresci"}


def _is_toc_doc(blocks: list[Block], doc_title: str, toc_titles: set[str]) -> bool:
    """An (often generated) table-of-contents page: a heading plus chapter titles."""
    texts = [normalize_title(b.text) for b in blocks]
    if not texts:
        return False
    titled = texts[0] in CONTENTS_TITLES or normalize_title(doc_title) in CONTENTS_TITLES
    entries = texts[1:] if texts[0] in CONTENTS_TITLES else texts
    matches = sum(1 for t in entries if t in toc_titles)
    return bool(entries) and matches >= 2 and matches >= 0.7 * len(entries) and (titled or matches == len(entries))


def _build_chapters(
    spine: list[ManifestItem],
    docs: list[list[Block]],
    doc_titles: list[str],
    toc: list[TocEntry],
) -> list[ParsedChapter]:
    toc_titles = {normalize_title(e.title) for e in toc}
    docs = [[] if _is_toc_doc(blocks, title, toc_titles) else blocks for blocks, title in zip(docs, doc_titles)]
    doc_index = {item.href: i for i, item in enumerate(spine)}
    doc_index_lower = {item.href.lower(): i for i, item in enumerate(spine)}

    # Resolve TOC entries to (doc, block) positions.
    max_depth = 2
    positions: dict[tuple[int, int], list[TocEntry]] = {}
    usable = [e for e in toc if e.depth <= max_depth]
    if len({doc_index.get(e.href, doc_index_lower.get(e.href.lower())) for e in usable} - {None}) < 2:
        usable = toc  # shallow TOC is not useful, use everything
    for entry in usable:
        di = doc_index.get(entry.href, doc_index_lower.get(entry.href.lower()))
        if di is None:
            continue
        bi = 0
        if entry.fragment:
            found = next((i for i, b in enumerate(docs[di]) if entry.fragment in b.ids), None)
            if found is None:
                wanted = normalize_title(entry.title)
                found = next(
                    (i for i, b in enumerate(docs[di]) if b.level and normalize_title(b.text) == wanted),
                    0,
                )
            bi = found
        positions.setdefault((di, bi), []).append(entry)

    chapters: list[ParsedChapter] = []
    current: ParsedChapter | None = None

    def finish() -> None:
        nonlocal current
        if current is not None and current.text.strip():
            chapters.append(current)
        current = None

    if len(positions) >= 2:
        first_pos = min(positions)
        for di, blocks in enumerate(docs):
            for bi, block in enumerate(blocks):
                if (di, bi) in positions:
                    finish()
                    entries = positions[(di, bi)]
                    titles: list[str] = []
                    for e in entries:
                        if e.title not in titles:
                            titles.append(e.title)
                    current = ParsedChapter(title=" – ".join(titles)[:200], text="")
                elif current is None or (di, bi) < first_pos and bi == 0:
                    # Content before the first TOC entry: one section per document.
                    finish()
                    title = _chapter_title_from_blocks(blocks) or doc_titles[di] or "Front matter"
                    current = ParsedChapter(title=title[:200], text="", kind="front")
                current.text = (current.text + "\n\n" + block.text) if current.text else block.text
        finish()
    else:
        # No usable TOC: a document starting with a heading starts a chapter.
        for di, blocks in enumerate(docs):
            if not blocks:
                continue
            starts_with_heading = blocks[0].level > 0
            if current is None or starts_with_heading:
                finish()
                title = _chapter_title_from_blocks(blocks) or doc_titles[di] or f"Section {len(chapters) + 1}"
                current = ParsedChapter(title=title[:200], text="")
            for block in blocks:
                current.text = (current.text + "\n\n" + block.text) if current.text else block.text
        finish()

    # Classify and default-include.
    for n, chapter in enumerate(chapters):
        if BACK_MATTER_RE.match(chapter.title) and n > len(chapters) / 2:
            chapter.kind = "back"
        if looks_like_front_matter(chapter.title, chapter.text) or (
            chapter.kind == "back" and BACK_MATTER_RE.match(chapter.title)
        ):
            chapter.include = False
        elif chapter.kind == "front" and FRONT_MATTER_RE.search(chapter.title):
            chapter.include = False
    return chapters
