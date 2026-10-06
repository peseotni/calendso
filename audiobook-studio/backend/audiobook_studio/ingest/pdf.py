"""PDF parser.

PDFs have no notion of paragraphs or chapters, so this module reconstructs
them: running headers/footers and page numbers are removed, lines are joined
into paragraphs (with de-hyphenation), table-of-contents pages are dropped and
chapters are found via the PDF outline, large/bold headings or chapter-like
lines. Scanned pages without a text layer are OCR'd when Tesseract language
data is available.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .base import (
    CHAPTER_RE,
    IngestError,
    ParsedBook,
    ParsedChapter,
    Para,
    ProgressFn,
    _split_evenly,
    clean_inline,
    count_words,
    first_year,
    guess_language,
    is_heading_like,
    join_wrapped,
    looks_like_front_matter,
    normalize_language,
    normalize_title,
)

log = logging.getLogger(__name__)

TERMINAL = ".!?:;\"”’'…)]»"
_PAGE_NUM_RE = re.compile(
    r"^\s*(?:page\s+)?(?:\d{1,4}|[ivxlcdm]{1,7})(?:\s*(?:of|/)\s*\d{1,4})?\s*$|^\s*[-–—]\s*\d{1,4}\s*[-–—]\s*$",
    re.IGNORECASE,
)
_TOC_LINE_RE = re.compile(r"^(.{2,}?)(?:\s*[.·…]{2,}\s*|\s+)(\d{1,4}|[ivxlc]{1,6})$", re.IGNORECASE)
_JUNK_TITLE_RE = re.compile(
    r"^(untitled.*|document\d*|title|book|ebook|.*\.(docx?|pdf|indd|qxd|tex|rtf|odt))$", re.IGNORECASE
)
OCR_LANGS = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "nl": "nld"}


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool
    block: int


@dataclass
class PPara:
    text: str
    size: float
    bold: bool
    page: int
    heading: bool = False


def _import_pymupdf():
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - dependency is required
        raise IngestError("PDF support requires the 'pymupdf' package.") from exc
    return pymupdf


def _page_lines(pymupdf, page, textpage=None) -> list[Line]:
    flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
    data = page.get_text("dict", flags=flags, textpage=textpage)
    lines: list[Line] = []
    for block_no, block in enumerate(data.get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            direction = line.get("dir", (1, 0))
            if abs(direction[1]) > 0.2:  # rotated / vertical text (margins, stamps)
                continue
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = clean_inline("".join(s.get("text", "") for s in line["spans"]))
            if not text:
                continue
            main = max(spans, key=lambda s: len(s.get("text", "")))
            font = (main.get("font") or "").lower()
            bold = bool(main.get("flags", 0) & 16) or "bold" in font or "black" in font
            x0, y0, x1, y1 = line["bbox"]
            lines.append(Line(text, x0, y0, x1, y1, round(main.get("size", 0.0), 1), bold, block_no))
    return lines


def _ocr_language(language: str, tessdata: str | None) -> str | None:
    if not tessdata:
        return None
    code = OCR_LANGS.get((language or "en")[:2], "eng")
    for candidate in (code, "eng"):
        if Path(tessdata, f"{candidate}.traineddata").exists():
            return candidate
    return None


def _tessdata(pymupdf) -> str | None:
    try:
        return pymupdf.get_tessdata()
    except Exception:  # noqa: BLE001 - tessdata missing
        return None


def _norm_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def _strip_running_lines(pages: list[list[Line]], heights: list[float], body_size: float) -> None:
    """Remove running headers/footers and page numbers."""
    occurrences: dict[str, list[int]] = {}
    for index, (lines, height) in enumerate(zip(pages, heights)):
        keys = {
            _norm_key(line.text)
            for line in lines
            if line.y1 <= height * 0.12 or line.y0 >= height * 0.88
        }
        for key in keys:
            occurrences.setdefault(key, []).append(index)

    running: set[str] = set()
    for key, where in occurrences.items():
        if len(where) < 3:
            continue
        span = where[-1] - where[0] + 1
        if len(where) / span >= 0.4:
            running.add(key)

    for index, (lines, height) in enumerate(zip(pages, heights)):
        kept = []
        for line in lines:
            in_zone = line.y1 <= height * 0.12 or line.y0 >= height * 0.88
            # Large text in the margins is a heading, not a running header.
            if in_zone and line.size < body_size * 1.2:
                if _norm_key(line.text) in running or _PAGE_NUM_RE.match(line.text):
                    continue
            kept.append(line)
        pages[index] = kept


def _is_toc_page(lines: list[Line]) -> bool:
    if len(lines) < 3:
        return False
    hits = sum(1 for line in lines if len(line.text) < 140 and _TOC_LINE_RE.match(line.text))
    titled = any(
        re.match(r"^\s*(table of )?contents|inhalt(sverzeichnis)?|sommaire|índice\s*$", line.text, re.IGNORECASE)
        for line in lines[:4]
    )
    if titled and hits >= 2:
        return True
    return len(lines) >= 5 and hits / len(lines) > 0.55


_join_lines = join_wrapped


def _paragraphs(lines: list[Line], page_no: int, body_size: float) -> list[PPara]:
    if not lines:
        return []
    body_lines = [l for l in lines if abs(l.size - body_size) <= 1.0] or lines
    lefts = sorted(l.x0 for l in body_lines)
    rights = sorted(l.x1 for l in body_lines)
    col_left = lefts[len(lefts) // 10]
    col_right = rights[(len(rights) * 9) // 10]
    col_width = max(col_right - col_left, 1.0)

    paras: list[PPara] = []
    current: PPara | None = None
    prev: Line | None = None
    for line in lines:
        new = prev is None or current is None
        if not new:
            assert prev is not None
            height = max(prev.y1 - prev.y0, line.size, 1.0)
            gap = line.y0 - prev.y1
            ends_sentence = prev.text.rstrip()[-1:] in TERMINAL
            indented = line.x0 - col_left > max(line.size * 0.9, 6)
            prev_short = prev.x1 < col_right - col_width * 0.15
            if abs(line.size - prev.size) > 1.0 or (prev.bold != line.bold and count_words(prev.text) < 12):
                new = True
            elif gap > height * 0.9 or gap < -height * 3:
                new = True
            elif ends_sentence and (indented or prev_short):
                new = True
            elif line.block != prev.block and ends_sentence:
                new = True
        if new:
            if current is not None:
                paras.append(current)
            current = PPara(text=line.text, size=line.size, bold=line.bold, page=page_no)
        else:
            assert current is not None
            current.text = _join_lines(current.text, line.text)
            current.bold = current.bold and line.bold
        prev = line
    if current is not None:
        paras.append(current)
    return paras


def _is_heading(para: PPara, body_size: float) -> bool:
    text = para.text.strip()
    words = count_words(text)
    if words == 0 or words > 18 or len(text) > 150 or len(text) < 2:
        return False
    if text[-1:] in ".,;" and not is_heading_like(text):
        return False
    if para.size >= body_size * 1.25:
        return True
    if (para.bold or para.size >= body_size * 1.1) and is_heading_like(text):
        return True
    return bool(CHAPTER_RE.match(text)) and words <= 8


def _merge_across_pages(paras: list[PPara]) -> list[PPara]:
    merged: list[PPara] = []
    for para in paras:
        if merged:
            prev = merged[-1]
            if (
                para.page == prev.page + 1
                and not prev.heading
                and not para.heading
                and abs(prev.size - para.size) <= 1.0
                and prev.text.rstrip()[-1:] not in TERMINAL
                and (para.text[:1].islower() or prev.text.rstrip()[-1:] in ",-–—" or prev.text[-1:].isalpha())
            ):
                prev.text = _join_lines(prev.text, para.text)
                continue
        merged.append(para)
    return merged


def _fix_drop_caps(paras: list[PPara], body_size: float) -> list[PPara]:
    result: list[PPara] = []
    skip = False
    for i, para in enumerate(paras):
        if skip:
            skip = False
            continue
        text = para.text.strip()
        if len(text) == 1 and text.isalpha() and para.size > body_size * 1.4 and i + 1 < len(paras):
            nxt = paras[i + 1]
            nxt.text = text + nxt.text.lstrip()
            result.append(nxt)
            skip = True
            continue
        result.append(para)
    return result


def _clean_title(value: str) -> str:
    value = re.sub(r"^Microsoft Word\s*-\s*", "", (value or "").strip(), flags=re.IGNORECASE)
    value = clean_inline(value)
    if not value or _JUNK_TITLE_RE.match(value):
        return ""
    return value


def parse_pdf(path: Path, progress: ProgressFn | None = None, options: dict | None = None) -> ParsedBook:
    pymupdf = _import_pymupdf()
    options = options or {}
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Could not open PDF: {exc}") from exc
    if doc.needs_pass:
        raise IngestError("This PDF is password protected.")
    if doc.page_count == 0:
        raise IngestError("This PDF has no pages.")

    book = ParsedBook()
    meta = doc.metadata or {}
    book.title = _clean_title(meta.get("title", ""))
    author = clean_inline(meta.get("author") or "")
    if author and not re.match(r"^(unknown|admin|user|owner)$", author, re.IGNORECASE):
        book.authors = [a.strip() for a in re.split(r"\s*(?:;|&| and )\s*", author) if a.strip()]
    book.year = first_year(meta.get("creationDate") or "")
    keywords = meta.get("keywords") or ""
    book.subjects = [k.strip() for k in re.split(r"[,;]", keywords) if k.strip()][:10]
    subject = clean_inline(meta.get("subject") or "")
    if len(subject) > 40:
        book.description = subject

    ocr_mode = options.get("ocr", "auto")
    tessdata = _tessdata(pymupdf) if ocr_mode != "off" else None
    ocr_lang = _ocr_language(options.get("language", ""), tessdata)
    ocr_pages = 0

    pages: list[list[Line]] = []
    heights: list[float] = []
    total = doc.page_count
    for number, page in enumerate(doc):
        lines = _page_lines(pymupdf, page)
        char_count = sum(len(l.text) for l in lines)
        needs_ocr = ocr_mode == "force" or (char_count < 25 and page.get_images())
        if needs_ocr and ocr_mode != "off" and ocr_lang:
            try:
                textpage = page.get_textpage_ocr(language=ocr_lang, dpi=300, full=True, tessdata=tessdata)
                lines = _page_lines(pymupdf, page, textpage=textpage)
                ocr_pages += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("OCR failed on page %s: %s", number + 1, exc)
        pages.append(lines)
        heights.append(page.rect.height or 792.0)
        if progress and (number % 5 == 0 or number == total - 1):
            label = "Running OCR" if ocr_pages else "Reading"
            progress(0.05 + 0.8 * (number + 1) / total, f"{label} page {number + 1} of {total}")

    all_lines = [line for lines in pages for line in lines]
    if not all_lines:
        if not tessdata:
            raise IngestError(
                "This PDF contains no text layer (scanned images). Install Tesseract OCR "
                "language data to convert scanned books."
            )
        raise IngestError("No text could be extracted from this PDF.")
    if ocr_pages:
        book.warnings.append(f"{ocr_pages} scanned page(s) were converted with OCR - please proofread.")

    size_weights: Counter[float] = Counter()
    for line in all_lines:
        size_weights[line.size] += len(line.text)
    body_size = size_weights.most_common(1)[0][0] or 10.0

    _strip_running_lines(pages, heights, body_size)

    # Title fallback: the largest text on the first pages.
    if not book.title:
        candidates = [l for lines in pages[:2] for l in lines if 1 <= count_words(l.text) <= 15]
        if candidates:
            biggest = max(candidates, key=lambda l: l.size)
            if biggest.size >= body_size * 1.3:
                book.title = biggest.text
    if not book.title:
        book.title = re.sub(r"[_]+", " ", path.stem).strip()

    paras: list[PPara] = []
    toc_scan_limit = max(20, total // 6)
    for number, lines in enumerate(pages):
        if number < toc_scan_limit and _is_toc_page(lines):
            continue
        paras.extend(_paragraphs(lines, number, body_size))
    paras = _fix_drop_caps(paras, body_size)
    for para in paras:
        para.heading = _is_heading(para, body_size)
    paras = _merge_across_pages(paras)

    book.chapters = _chapters(doc, paras, body_size)
    book.cover = _render_cover(pymupdf, doc)
    if not book.language:
        book.language = normalize_language(options.get("language", "")) or guess_language(
            " ".join(p.text for p in paras[:400])
        )
    doc.close()
    return book


def _chapters(doc, paras: list[PPara], body_size: float) -> list[ParsedChapter]:
    if not paras:
        return []
    boundaries = _outline_boundaries(doc, paras) or _heading_boundaries(paras)
    if not boundaries:
        return _split_evenly([Para(p.text) for p in paras], "Part", 4000)

    chapters: list[ParsedChapter] = []
    first = boundaries[0][0]
    if first > 0:
        front = paras[:first]
        text = "\n\n".join(p.text for p in front)
        title = next((p.text for p in front if p.heading), "Front matter")
        include = not looks_like_front_matter(title, text) and count_words(text) > 150
        chapters.append(ParsedChapter(title=title[:200], text=text, kind="front", include=include))

    for n, (start, title) in enumerate(boundaries):
        end = boundaries[n + 1][0] if n + 1 < len(boundaries) else len(paras)
        text = "\n\n".join(p.text for p in paras[start:end])
        if not text.strip():
            continue
        chapter = ParsedChapter(title=title[:200], text=text)
        if looks_like_front_matter(title, text):
            chapter.include = False
        chapters.append(chapter)
    return chapters


def _outline_boundaries(doc, paras: list[PPara]) -> list[tuple[int, str]]:
    try:
        toc = doc.get_toc(simple=True)
    except Exception:  # noqa: BLE001
        return []
    entries = [(lvl, clean_inline(title), page - 1) for lvl, title, page in toc if page >= 1 and clean_inline(title)]
    if len(entries) < 2:
        return []
    levels = Counter(lvl for lvl, _, _ in entries)
    use_level = 1
    if levels.get(1, 0) < 3 and levels.get(2, 0) >= 3:
        use_level = 2
    elif levels.get(1, 0) and levels.get(2, 0) >= levels.get(1, 0) * 2 and levels.get(1, 0) <= 12:
        use_level = 2
    chosen = [(title, page) for lvl, title, page in entries if lvl <= use_level]

    first_on_page: dict[int, int] = {}
    for index, para in enumerate(paras):
        first_on_page.setdefault(para.page, index)
    pages_sorted = sorted(first_on_page)

    result: dict[int, str] = {}
    for title, page in chosen:
        wanted = normalize_title(title)
        index = None
        for i in range(first_on_page.get(page, len(paras)), len(paras)):
            if paras[i].page != page:
                break
            got = normalize_title(paras[i].text)
            if got and (got.startswith(wanted) or (wanted.startswith(got) and len(got) > 3)):
                index = i
                break
        if index is None:
            following = next((p for p in pages_sorted if p >= page), None)
            if following is None:
                continue
            index = first_on_page[following]
        if index in result:
            if normalize_title(title) not in normalize_title(result[index]):
                result[index] = f"{result[index]} – {title}"
        else:
            result[index] = title
    boundaries = sorted(result.items())
    return boundaries if len(boundaries) >= 2 else []


def _heading_boundaries(paras: list[PPara]) -> list[tuple[int, str]]:
    boundaries: list[tuple[int, str]] = []
    index = 0
    first_page = paras[0].page
    while index < len(paras):
        para = paras[index]
        if para.heading and not (para.page == first_page and index < 6 and not is_heading_like(para.text)):
            title = para.text.strip()
            nxt = index + 1
            # Merge "Chapter 1" + "The Beginning" style heading pairs.
            if nxt < len(paras) and paras[nxt].heading and paras[nxt].page == para.page and count_words(title) <= 4:
                title = f"{title}: {paras[nxt].text.strip()}"
                nxt += 1
            boundaries.append((index, title))
            index = nxt
            continue
        index += 1
    if len(boundaries) < 2:
        return []
    # Too many "headings" (e.g. bold first words everywhere) - not trustworthy.
    if len(boundaries) > max(60, len(paras) // 4):
        chapter_like = [(i, t) for i, t in boundaries if is_heading_like(t.split(":")[0])]
        return chapter_like if len(chapter_like) >= 2 else []
    return boundaries


def _render_cover(pymupdf, doc) -> bytes | None:
    try:
        page = doc[0]
        width = page.rect.width or 600
        zoom = min(3.0, max(0.5, 700 / width))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("jpeg")
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not render PDF cover: %s", exc)
        return None
