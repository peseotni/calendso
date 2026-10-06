from __future__ import annotations

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
