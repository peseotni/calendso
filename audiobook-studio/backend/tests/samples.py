"""Generators for small sample documents in every supported format."""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

TITLE = "The Lighthouse Keeper"
AUTHOR = "Ada Winterbourne"

CHAPTERS = [
    (
        "Chapter 1: The Storm",
        [
            "The storm arrived an hour before midnight, rolling over the cliffs like a tide of iron. "
            "Mara had kept the lamp burning for eleven years, and she knew the sound of every kind of weather.",
            "“Is it bad?” asked Tobias from the stairwell. He was only nine, and the wind frightened him.",
            "“It is only loud,” Mara said. “Loud is not the same as dangerous. Mr. Hale taught me that.”",
            "Outside, the sea threw itself against the rocks again and again, as if it had forgotten something "
            "important and hoped the shore might remember it.",
        ],
    ),
    (
        "Chapter 2: The Ship",
        [
            "At two in the morning a light appeared on the horizon, small and uncertain, a ship fighting the swell.",
            "Mara climbed to the gallery and trimmed the wick. The beam swept across the water, steady and bright.",
            "The ship turned, slowly at first and then with purpose, away from the reef and toward the harbor.",
        ],
    ),
    (
        "Chapter 3: Morning",
        [
            "By dawn the storm had worn itself out. The sky was the color of pearl, and the gulls returned.",
            "Tobias found a piece of rope on the beach, knotted in a way neither of them had seen before.",
            "“We kept them safe,” he said. Mara smiled and put the kettle on.",
        ],
    ),
]

def _cover_jpeg() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (300, 450), (30, 60, 120))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def _xhtml(title: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>{title}</title></head><body>{body}</body></html>"
    )


def make_epub3(path: Path) -> Path:
    cover = _cover_jpeg()
    docs = {
        "cover.xhtml": _xhtml("Cover", '<div><img src="images/cover.jpg" alt="Cover"/></div>'),
        "copyright.xhtml": _xhtml(
            "Copyright",
            "<p>Copyright © 2024 Ada Winterbourne. All rights reserved.</p><p>ISBN 978-0-00-000000-2</p>",
        ),
    }
    for n, (title, paras) in enumerate(CHAPTERS, start=1):
        body = f'<section epub:type="chapter"><h1 id="c{n}">{title}</h1>'
        for i, p in enumerate(paras):
            note = '<a epub:type="noteref" href="#fn1">1</a>' if (n == 1 and i == 0) else ""
            pagebreak = f'<span epub:type="pagebreak" title="{n * 10}">{n * 10}</span>' if i == 1 else ""
            body += f"<p>{pagebreak}{p}{note}</p>"
        if n == 1:
            body += '<aside epub:type="footnote" id="fn1"><p>A footnote that should not be read.</p></aside>'
        body += "</section>"
        docs[f"chapter{n}.xhtml"] = _xhtml(title, body)

    nav = _xhtml(
        "Contents",
        '<nav epub:type="toc"><h1>Contents</h1><ol>'
        + "".join(f'<li><a href="chapter{n}.xhtml#c{n}">{t}</a></li>' for n, (t, _) in enumerate(CHAPTERS, 1))
        + "</ol></nav>",
    )
    manifest = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="cover-img" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>'
        '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="copyright" href="copyright.xhtml" media-type="application/xhtml+xml"/>'
        + "".join(
            f'<item id="ch{n}" href="chapter{n}.xhtml" media-type="application/xhtml+xml"/>'
            for n in range(1, len(CHAPTERS) + 1)
        )
    )
    spine = '<itemref idref="cover"/><itemref idref="copyright"/>' + "".join(
        f'<itemref idref="ch{n}"/>' for n in range(1, len(CHAPTERS) + 1)
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="uid">urn:isbn:9780000000002</dc:identifier>'
        f"<dc:title>{TITLE}</dc:title>"
        f'<dc:creator id="a1">{AUTHOR}</dc:creator>'
        '<meta refines="#a1" property="role" scheme="marc:relators">aut</meta>'
        "<dc:language>en-GB</dc:language>"
        "<dc:publisher>Harbor Press</dc:publisher>"
        "<dc:date>2024-03-01</dc:date>"
        "<dc:description>&lt;p&gt;A keeper, a storm and a ship.&lt;/p&gt;</dc:description>"
        "<dc:subject>Fiction</dc:subject>"
        '<meta property="belongs-to-collection" id="s1">Coastal Tales</meta>'
        '<meta refines="#s1" property="collection-type">series</meta>'
        '<meta refines="#s1" property="group-position">2</meta>'
        "</metadata>"
        f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/images/cover.jpg", cover)
        for name, content in docs.items():
            z.writestr(f"OEBPS/{name}", content)
    return path


def make_epub2_single_file(path: Path) -> Path:
    """EPUB 2 with an NCX where all chapters live in one document (fragment anchors)."""
    body = ""
    for n, (title, paras) in enumerate(CHAPTERS, start=1):
        body += f'<h2 id="ch{n}">{title}</h2>' + "".join(f"<p>{p}</p>" for p in paras)
    content = _xhtml(TITLE, body)
    ncx = (
        '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>'
        + "".join(
            f'<navPoint id="n{n}" playOrder="{n}"><navLabel><text>{t}</text></navLabel>'
            f'<content src="text/book.html#ch{n}"/></navPoint>'
            for n, (t, _) in enumerate(CHAPTERS, 1)
        )
        + "</navMap></ncx>"
    )
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
        f"<dc:title>{TITLE}</dc:title>"
        f'<dc:creator opf:role="aut">{AUTHOR}</dc:creator>'
        '<dc:creator opf:role="ill">Some Illustrator</dc:creator>'
        '<dc:identifier id="id" opf:scheme="ISBN">978-0-00-000000-2</dc:identifier>'
        '<meta name="calibre:series" content="Coastal Tales"/>'
        '<meta name="calibre:series_index" content="3.0"/>'
        "</metadata><manifest>"
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="book" href="text/book.html" media-type="application/xhtml+xml"/>'
        '</manifest><spine toc="ncx"><itemref idref="book"/></spine></package>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr("content.opf", opf)
        z.writestr("toc.ncx", ncx)
        z.writestr("text/book.html", content)
    return path


def make_pdf(path: Path, outline: bool = True) -> Path:
    import pymupdf

    doc = pymupdf.open()
    width, height = 432, 648
    toc = []

    def new_page(number: int):
        page = doc.new_page(width=width, height=height)
        page.insert_text((60, 40), "THE LIGHTHOUSE KEEPER", fontsize=8)
        page.insert_text((width / 2 - 5, height - 30), str(number), fontsize=8)
        return page

    # Title page
    page = doc.new_page(width=width, height=height)
    page.insert_text((60, 200), TITLE, fontsize=24)
    page.insert_text((60, 240), AUTHOR, fontsize=14)
    # Copyright page
    page = new_page(2)
    page.insert_text((60, 300), "Copyright 2024 Ada Winterbourne. All rights reserved.", fontsize=9)
    # Contents page
    page = new_page(3)
    page.insert_text((60, 100), "Contents", fontsize=16)
    for n, (title, _) in enumerate(CHAPTERS):
        page.insert_text((60, 140 + n * 20), f"{title} ........ {4 + n * 2}", fontsize=10)

    page_number = 4
    for title, paras in CHAPTERS:
        page = new_page(page_number)
        toc.append([1, title, page_number])
        page.insert_text((60, 120), title, fontsize=18)
        y = 160
        for para in paras:
            rect = pymupdf.Rect(60, y, width - 60, height - 60)
            words = para.split()
            # first paragraph of chapter 1 gets a forced hyphenation across lines
            text = " ".join(words)
            rc = page.insert_textbox(rect, text, fontsize=11, align=0)
            used = (len(text) // 58 + 1) * 14
            y += used + 10
            if y > height - 120:
                page_number += 1
                page = new_page(page_number)
                y = 70
        page_number += 1
    if outline:
        doc.set_toc(toc)
    doc.set_metadata({"title": TITLE, "author": AUTHOR, "creationDate": "D:20240301000000"})
    doc.save(path)
    return path


def make_docx(path: Path) -> Path:
    import docx

    document = docx.Document()
    document.core_properties.title = TITLE
    document.core_properties.author = AUTHOR
    document.add_paragraph(TITLE, style="Title")
    for title, paras in CHAPTERS:
        document.add_heading(title, level=1)
        for p in paras:
            document.add_paragraph(p)
    document.save(str(path))
    return path


def make_txt(path: Path, gutenberg: bool = True) -> Path:
    lines = []
    if gutenberg:
        lines += [
            f"The Project Gutenberg eBook of {TITLE}",
            "",
            f"Title: {TITLE}",
            f"Author: {AUTHOR}",
            "Language: English",
            "",
            f"*** START OF THE PROJECT GUTENBERG EBOOK {TITLE.upper()} ***",
            "",
        ]
    for title, paras in CHAPTERS:
        number, name = title.split(": ")
        lines += [number.upper() + ".", "", name, ""]
        for p in paras:
            # hard wrap at ~70 chars
            words, line = p.split(), ""
            for w in words:
                if len(line) + len(w) + 1 > 70:
                    lines.append(line)
                    line = w
                else:
                    line = f"{line} {w}".strip()
            lines += [line, ""]
    if gutenberg:
        lines += [f"*** END OF THE PROJECT GUTENBERG EBOOK {TITLE.upper()} ***", "", "License text..."]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def make_markdown(path: Path) -> Path:
    out = ["---", f"title: {TITLE}", f"author: {AUTHOR}", "language: en", "---", "", f"# {TITLE}", ""]
    for title, paras in CHAPTERS:
        out += [f"## {title}", ""]
        for p in paras:
            out += [p.replace("storm", "**storm**", 1), ""]
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def make_html(path: Path) -> Path:
    body = f"<h1>{TITLE}</h1>"
    for title, paras in CHAPTERS:
        body += f"<h2>{title}</h2>" + "".join(f"<p>{p}</p>" for p in paras)
    path.write_text(
        f'<!doctype html><html lang="en"><head><title>{TITLE}</title>'
        f'<meta name="author" content="{AUTHOR}"></head><body>{body}</body></html>',
        encoding="utf-8",
    )
    return path


def make_fb2(path: Path) -> Path:
    sections = "".join(
        f"<section><title><p>{t}</p></title>" + "".join(f"<p>{p}</p>" for p in ps) + "</section>"
        for t, ps in CHAPTERS
    )
    cover = base64.b64encode(_cover_jpeg()).decode()
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">'
        "<description><title-info><genre>prose_contemporary</genre>"
        "<author><first-name>Ada</first-name><last-name>Winterbourne</last-name></author>"
        f"<book-title>{TITLE}</book-title><annotation><p>A keeper and a storm.</p></annotation>"
        '<date value="2024-01-01">2024</date><coverpage><image l:href="#cover.jpg"/></coverpage>'
        '<lang>en</lang><sequence name="Coastal Tales" number="2"/></title-info></description>'
        f"<body>{sections}</body>"
        '<body name="notes"><section id="n1"><p>Note text</p></section></body>'
        f'<binary id="cover.jpg" content-type="image/jpeg">{cover}</binary>'
        "</FictionBook>"
    )
    path.write_text(xml, encoding="utf-8")
    return path


def make_odt(path: Path) -> Path:
    ns = (
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"'
    )
    body = ""
    for title, paras in CHAPTERS:
        body += f'<text:h text:outline-level="1">{title}</text:h>'
        body += "".join(f"<text:p>{p}</text:p>" for p in paras)
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns}>'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    meta = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-meta {ns}><office:meta>'
        f"<dc:title>{TITLE}</dc:title><meta:initial-creator>{AUTHOR}</meta:initial-creator>"
        "<dc:language>en-US</dc:language></office:meta></office:document-meta>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", content)
        z.writestr("meta.xml", meta)
    return path
