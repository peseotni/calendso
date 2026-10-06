from __future__ import annotations

from pathlib import Path

import pytest

import samples
from audiobook_studio.ingest import IngestError, detect_format, parse_book

EXPECTED_TITLES = [t for t, _ in samples.CHAPTERS]


def _included_titles(book):
    return [c.title for c in book.chapters if c.include]


@pytest.mark.parametrize(
    "maker,filename",
    [
        (samples.make_epub3, "book.epub"),
        (samples.make_epub2_single_file, "book2.epub"),
        (samples.make_docx, "book.docx"),
        (samples.make_markdown, "book.md"),
        (samples.make_html, "book.html"),
        (samples.make_fb2, "book.fb2"),
        (samples.make_odt, "book.odt"),
    ],
)
def test_structured_formats(tmp_path, maker, filename):
    path = maker(tmp_path / filename)
    book = parse_book(path, detect_format(filename))
    assert book.title == samples.TITLE
    assert book.authors == [samples.AUTHOR]
    assert _included_titles(book) == EXPECTED_TITLES
    first = next(c for c in book.chapters if c.include)
    assert "The storm arrived an hour before midnight" in first.text
    assert book.language.startswith("en")


def test_epub3_metadata_and_cleanup(tmp_path):
    book = parse_book(samples.make_epub3(tmp_path / "b.epub"), "epub")
    assert book.series == "Coastal Tales" and book.series_index == "2"
    assert book.isbn == "9780000000002"
    assert book.year == "2024"
    assert book.publisher == "Harbor Press"
    assert book.description == "A keeper, a storm and a ship."
    assert book.cover and book.cover[:2] == b"\xff\xd8"
    copyright_chapter = book.chapters[0]
    assert copyright_chapter.title == "Copyright" and not copyright_chapter.include
    text = "\n".join(c.text for c in book.chapters)
    assert "footnote that should not be read" not in text
    assert "“Is it bad?”" in text  # utf-8 decoded correctly


def test_epub2_series_from_calibre_meta(tmp_path):
    book = parse_book(samples.make_epub2_single_file(tmp_path / "b.epub"), "epub")
    assert book.series == "Coastal Tales" and book.series_index == "3"
    assert book.authors == [samples.AUTHOR]  # illustrator is not an author


@pytest.mark.parametrize("outline", [True, False])
def test_pdf(tmp_path, outline):
    book = parse_book(samples.make_pdf(tmp_path / "b.pdf", outline=outline), "pdf")
    assert book.title == samples.TITLE
    assert _included_titles(book) == EXPECTED_TITLES
    text = "\n".join(c.text for c in book.chapters if c.include)
    assert "THE LIGHTHOUSE KEEPER" not in text  # running header removed
    assert "........" not in text  # table of contents removed
    assert book.cover is not None


def test_gutenberg_text(tmp_path):
    book = parse_book(samples.make_txt(tmp_path / "pg.txt"), "txt")
    assert book.title == samples.TITLE
    assert book.authors == [samples.AUTHOR]
    assert [c.title for c in book.chapters] == ["CHAPTER 1: The Storm", "CHAPTER 2: The Ship", "CHAPTER 3: Morning"]
    assert "License text" not in book.chapters[-1].text
    # hard-wrapped lines are joined into paragraphs
    assert "rolling over the cliffs like a tide of iron. Mara had kept" in book.chapters[0].text


def test_unknown_and_broken_files(tmp_path):
    assert detect_format("x.xyz") is None
    broken = tmp_path / "broken.epub"
    broken.write_bytes(b"not a zip")
    with pytest.raises(IngestError):
        parse_book(broken, "epub")


def _tessdata_available() -> bool:
    try:
        import pymupdf

        return bool(pymupdf.get_tessdata())
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _tessdata_available(), reason="Tesseract language data not installed")
def test_scanned_pdf_is_ocrd(tmp_path):
    import io

    import pymupdf
    from PIL import Image, ImageDraw, ImageFont

    pages = [
        ("Chapter One", "The storm arrived an hour before midnight. Mara kept the lamp burning all night long."),
        ("Chapter Two", "At dawn the ship turned toward the harbor and the keeper finally went to sleep."),
    ]
    doc = pymupdf.open()
    for title, body in pages:
        image = Image.new("RGB", (1240, 1754), "white")  # A4 at 150 dpi
        draw = ImageDraw.Draw(image)
        try:
            heading = ImageFont.truetype("DejaVuSerif-Bold.ttf", 64)
            font = ImageFont.truetype("DejaVuSerif.ttf", 36)
        except OSError:
            heading = font = ImageFont.load_default(size=40)
        draw.text((120, 200), title, font=heading, fill="black")
        words, line, y = body.split(), "", 340
        for word in words:
            if draw.textlength(f"{line} {word}", font=font) > 1000:
                draw.text((120, y), line, font=font, fill="black")
                line, y = word, y + 56
            else:
                line = f"{line} {word}".strip()
        draw.text((120, y), line, font=font, fill="black")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buffer.getvalue())
    path = tmp_path / "scan.pdf"
    doc.save(path)

    book = parse_book(path, "pdf", options={"ocr": "auto"})
    text = " ".join(c.text for c in book.chapters).lower()
    assert "storm arrived" in text and "harbor" in text
    assert any("OCR" in w for w in book.warnings)

    with pytest.raises(IngestError):
        parse_book(path, "pdf", options={"ocr": "off"})


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name", ["lighthouse.mobi", "lighthouse.azw3"])
def test_kindle_books(name):
    """Kindle files made from the sample EPUB with Calibre (old MOBI and KF8)."""
    book = parse_book(FIXTURES / name, detect_format(name))
    assert book.title == samples.TITLE and book.authors == [samples.AUTHOR]
    assert book.isbn == "9780000000002"
    assert book.cover and book.cover[:2] == b"\xff\xd8"
    assert _included_titles(book) == EXPECTED_TITLES  # Calibre's inline TOC page is dropped
    assert "The storm arrived an hour before midnight" in book.chapters[1].text


def test_drm_kindle_is_rejected(tmp_path):
    data = bytearray((FIXTURES / "lighthouse.mobi").read_bytes())
    record0 = int.from_bytes(data[78:82], "big")
    data[record0 + 12 : record0 + 14] = (2).to_bytes(2, "big")  # encryption type: Mobipocket DRM
    path = tmp_path / "locked.azw"
    path.write_bytes(bytes(data))
    with pytest.raises(IngestError, match="DRM"):
        parse_book(path, "mobi")
