"""Online metadata lookup (Open Library and Google Books)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "AudiobookStudio/1.0 (self-hosted audiobook manager)"}
TIMEOUT = 10.0


def _clean(text: Any) -> str:
    if isinstance(text, dict):
        text = text.get("value", "")
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return re.sub(r"\s+\n", "\n", text).strip()


def _genre_from_subjects(subjects: list[str]) -> str:
    keep = []
    for subject in subjects:
        s = subject.strip()
        if not s or len(s) > 40 or "--" in s or re.search(r"\d", s) or s.lower().startswith(("nyt:", "accessible")):
            continue
        s = s.split("/")[-1].strip().title()
        if s not in keep:
            keep.append(s)
        if len(keep) >= 3:
            break
    return ", ".join(keep)


def search_open_library(title: str, author: str = "", isbn: str = "", limit: int = 6) -> list[dict[str, Any]]:
    import httpx

    params: dict[str, Any] = {
        "limit": limit,
        "fields": "key,title,subtitle,author_name,first_publish_year,subject,isbn,cover_i,publisher,language,number_of_pages_median",
    }
    if isbn:
        params["isbn"] = isbn
    else:
        params["title"] = title
        if author:
            params["author"] = author
    response = httpx.get("https://openlibrary.org/search.json", params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    results = []
    for doc in response.json().get("docs", [])[:limit]:
        subjects = doc.get("subject") or []
        cover_id = doc.get("cover_i")
        isbns = doc.get("isbn") or []
        results.append({
            "source": "openlibrary",
            "source_id": doc.get("key", ""),
            "title": doc.get("title", ""),
            "subtitle": doc.get("subtitle", ""),
            "author": ", ".join((doc.get("author_name") or [])[:3]),
            "year": str(doc.get("first_publish_year") or ""),
            "publisher": (doc.get("publisher") or [""])[0],
            "genre": _genre_from_subjects(subjects),
            "tags": [s for s in subjects[:8] if len(s) < 30],
            "isbn": next((i for i in isbns if len(i) == 13), isbns[0] if isbns else ""),
            "language": {"eng": "en", "ger": "de", "fre": "fr", "spa": "es", "ita": "it"}.get((doc.get("language") or [""])[0], ""),
            "description": "",
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else "",
        })
    return results


def open_library_description(work_key: str) -> str:
    import httpx

    if not re.match(r"^/works/OL\d+W$", work_key or ""):
        return ""
    response = httpx.get(f"https://openlibrary.org{work_key}.json", headers=HEADERS, timeout=TIMEOUT)
    if response.status_code != 200:
        return ""
    return _clean(response.json().get("description", ""))


def search_google_books(title: str, author: str = "", isbn: str = "", limit: int = 6) -> list[dict[str, Any]]:
    import httpx

    if isbn:
        query = f"isbn:{isbn}"
    else:
        query = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")
    response = httpx.get(
        "https://www.googleapis.com/books/v1/volumes",
        params={"q": query, "maxResults": limit, "printType": "books"},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("items", [])[:limit]:
        info = item.get("volumeInfo", {})
        identifiers = {i.get("type"): i.get("identifier") for i in info.get("industryIdentifiers", [])}
        images = info.get("imageLinks", {})
        cover = images.get("extraLarge") or images.get("large") or images.get("medium") or images.get("thumbnail") or ""
        cover = cover.replace("http://", "https://").replace("&edge=curl", "")
        results.append({
            "source": "google",
            "source_id": item.get("id", ""),
            "title": info.get("title", ""),
            "subtitle": info.get("subtitle", ""),
            "author": ", ".join(info.get("authors", [])[:3]),
            "year": (info.get("publishedDate") or "")[:4],
            "publisher": info.get("publisher", ""),
            "genre": ", ".join(c.split("/")[-1].strip() for c in info.get("categories", [])[:2]),
            "tags": [],
            "isbn": identifiers.get("ISBN_13") or identifiers.get("ISBN_10") or "",
            "language": info.get("language", ""),
            "description": _clean(info.get("description", "")),
            "cover_url": cover,
        })
    return results


def search(title: str, author: str = "", isbn: str = "") -> dict[str, Any]:
    title, author, isbn = title.strip(), author.strip(), re.sub(r"[^\dXx]", "", isbn or "")
    if not (title or isbn):
        return {"results": [], "errors": ["Enter a title or ISBN"]}
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            "Open Library": pool.submit(search_open_library, title, author, isbn),
            "Google Books": pool.submit(search_google_books, title, author, isbn),
        }
        for name, future in futures.items():
            try:
                results.extend(future.result(timeout=TIMEOUT + 5))
            except Exception as exc:  # noqa: BLE001
                log.info("%s lookup failed: %s", name, exc)
                errors.append(f"{name}: {exc.__class__.__name__}")
    # Interleave sources so the best match of each comes first.
    google = [r for r in results if r["source"] == "google"]
    library = [r for r in results if r["source"] == "openlibrary"]
    merged = []
    for pair in zip(google, library):
        merged.extend(pair)
    merged.extend(google[len(library):])
    merged.extend(library[len(google):])
    return {"results": merged, "errors": errors}
