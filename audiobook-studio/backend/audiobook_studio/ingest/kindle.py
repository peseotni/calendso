"""MOBI / AZW / AZW3 parser (DRM-free files only).

KindleUnpack (via the ``mobi`` package) converts KF8 books to EPUB and older
MOBI books to HTML, which are then handled by the regular parsers. PyMuPDF,
which can read MOBI natively, is used as a fallback.
"""

from __future__ import annotations

import logging
import shutil
import struct
from pathlib import Path

from lxml import etree

from .base import IngestError, ParsedBook, ParsedChapter, ProgressFn, clean_inline, guess_language
from .epub import parse_epub
from .html import parse_html_file

log = logging.getLogger(__name__)


def _is_encrypted(path: Path) -> bool:
    """Read the PalmDOC header's encryption field of the first record."""
    try:
        with path.open("rb") as handle:
            head = handle.read(86)
            if len(head) < 86:
                return False
            (record0,) = struct.unpack(">I", head[78:82])
            handle.seek(record0 + 12)
            raw = handle.read(2)
            return len(raw) == 2 and struct.unpack(">H", raw)[0] != 0
    except OSError:
        return False


def parse_mobi(path: Path, progress: ProgressFn | None = None) -> ParsedBook:
    if _is_encrypted(path):
        raise IngestError("This Kindle book is DRM-protected and cannot be converted.")
    tempdir: str | None = None
    try:
        try:
            import mobi
        except ImportError:
            mobi = None
        if mobi is not None:
            try:
                if progress:
                    progress(0.1, "Unpacking Kindle book")
                tempdir, extracted = mobi.extract(str(path))
                result = Path(extracted)
                if result.suffix.lower() == ".epub":
                    return parse_epub(result, progress)
                if result.suffix.lower() in (".html", ".htm"):
                    book = parse_html_file(result)
                    _apply_opf_metadata(result.parent, book)
                    if book.title in ("book", ""):
                        book.title = path.stem
                    return book
            except IngestError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.info("KindleUnpack failed for %s: %s", path.name, exc)
                if "drm" in str(exc).lower() or "encrypt" in str(exc).lower():
                    raise IngestError("This Kindle book is DRM-protected and cannot be converted.") from exc
        return _parse_with_pymupdf(path)
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)


def _apply_opf_metadata(folder: Path, book: ParsedBook) -> None:
    for opf in folder.glob("*.opf"):
        try:
            root = etree.parse(str(opf), etree.XMLParser(resolve_entities=False, no_network=True, recover=True)).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        title = root.findtext(".//{http://purl.org/dc/elements/1.1/}title")
        creator = root.findtext(".//{http://purl.org/dc/elements/1.1/}creator")
        if title:
            book.title = clean_inline(title)
        if creator:
            book.authors = [clean_inline(creator)]
        break


def _parse_with_pymupdf(path: Path) -> ParsedBook:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise IngestError("Could not read this Kindle file.") from exc
    try:
        doc = pymupdf.open(str(path), filetype="mobi")
    except Exception as exc:  # noqa: BLE001
        raise IngestError(
            "Could not read this Kindle file. It may be DRM-protected or in an unsupported format."
        ) from exc
    book = ParsedBook()
    meta = doc.metadata or {}
    book.title = clean_inline(meta.get("title") or "") or path.stem
    if meta.get("author"):
        book.authors = [clean_inline(meta["author"])]
    toc = doc.get_toc(simple=True)
    page_texts = [page.get_text("text") for page in doc]
    starts = sorted({max(0, page - 1): title for _lvl, title, page in toc if page >= 1}.items())
    if len(starts) >= 2:
        for n, (start, title) in enumerate(starts):
            end = starts[n + 1][0] if n + 1 < len(starts) else len(page_texts)
            text = "\n\n".join(clean_inline(t) for t in page_texts[start:end] if t.strip())
            if text:
                book.chapters.append(ParsedChapter(title=clean_inline(title), text=text))
    else:
        text = "\n\n".join(clean_inline(t) for t in page_texts if t.strip())
        book.chapters = [ParsedChapter(title=book.title, text=text)]
    book.language = guess_language(" ".join(page_texts[:20]))
    return book
