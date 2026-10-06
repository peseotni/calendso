from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import samples


def _upload(client, path: Path, **form):
    with path.open("rb") as handle:
        response = client.post("/api/projects/upload", files={"files": (path.name, handle)}, data=form)
    assert response.status_code == 200, response.text
    return response.json()[0]


def _ffprobe_chapters(path: Path) -> list[str]:
    import json

    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return [c["tags"]["title"] for c in json.loads(out)["chapters"]]


@pytest.fixture(scope="module")
def rendered_book(client, tmp_path_factory, run_jobs=None):
    """Upload an EPUB, render it with the test engine and return (project, book)."""
    from audiobook_studio.jobs.runner import runner

    folder = tmp_path_factory.mktemp("upload")
    project = _upload(client, samples.make_epub3(folder / "lighthouse.epub"))
    assert project["status"] == "importing"
    runner.run_pending()
    detail = client.get(f"/api/projects/{project['id']}").json()
    assert detail["status"] == "ready"
    response = client.patch(f"/api/projects/{project['id']}", json={
        "genre": "Fiction",
        "settings": {"engine": "tone", "voice": "beep", "dialogue_enabled": True, "dialogue_engine": "tone",
                     "dialogue_voice": "boop", "output_format": "m4b", "normalize": False},
    })
    assert response.status_code == 200, response.text
    job = client.post(f"/api/projects/{project['id']}/render").json()
    assert job["kind"] == "render"
    runner.run_pending()
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done", job["log"]
    detail = client.get(f"/api/projects/{project['id']}").json()
    book = client.get(f"/api/books/{detail['book_id']}").json()
    return detail, book


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_import_project(client, run_jobs, tmp_path):
    project = _upload(client, samples.make_epub3(tmp_path / "import.epub"))
    run_jobs()
    detail = client.get(f"/api/projects/{project['id']}").json()
    assert detail["title"] == samples.TITLE
    assert detail["author"] == samples.AUTHOR
    assert detail["series"] == "Coastal Tales"
    assert detail["cover_url"]
    assert client.get(detail["cover_url"]).headers["content-type"] == "image/jpeg"
    titles = [c["title"] for c in detail["chapters"]]
    assert titles == ["Copyright"] + [t for t, _ in samples.CHAPTERS]
    assert detail["chapters"][0]["include"] is False
    assert detail["estimated_seconds"] > 0
    assert detail["settings"]["engine"]  # a default voice was chosen

    # unsupported uploads are rejected
    bad = tmp_path / "notes.xyz"
    bad.write_text("hello")
    with bad.open("rb") as handle:
        assert client.post("/api/projects/upload", files={"files": ("notes.xyz", handle)}).status_code == 400


def test_chapter_editing(client, run_jobs, tmp_path):
    project = _upload(client, samples.make_docx(tmp_path / "edit.docx"))
    run_jobs()
    detail = client.get(f"/api/projects/{project['id']}").json()
    pid = detail["id"]
    first, second = detail["chapters"][0], detail["chapters"][1]

    chapter = client.get(f"/api/projects/{pid}/chapters/{first['id']}").json()
    offset = chapter["text"].index("“Is it bad?”")
    detail = client.post(f"/api/projects/{pid}/chapters/{first['id']}/split", json={"offset": offset, "title": "Tobias"}).json()
    assert [c["title"] for c in detail["chapters"]][:2] == ["Chapter 1: The Storm", "Tobias"]

    detail = client.post(f"/api/projects/{pid}/chapters/merge",
                         json={"chapter_ids": [detail["chapters"][0]["id"], detail["chapters"][1]["id"]]}).json()
    assert len(detail["chapters"]) == 3

    updated = client.patch(f"/api/projects/{pid}/chapters/{second['id']}",
                           json={"title": "The Ship!", "include": False, "text": "Short new text."}).json()
    assert updated["title"] == "The Ship!" and updated["word_count"] == 3 and not updated["include"]

    ids = [c["id"] for c in detail["chapters"]][::-1]
    detail = client.post(f"/api/projects/{pid}/chapters/reorder", json={"chapter_ids": ids}).json()
    assert [c["id"] for c in detail["chapters"]] == ids

    detail = client.post(f"/api/projects/{pid}/chapters", json={"title": "Credits", "text": "Narrated by a robot."}).json()
    assert detail["chapters"][-1]["title"] == "Credits"

    export = client.get(f"/api/projects/{pid}/export.txt")
    assert export.status_code == 200 and "Credits" in export.text

    assert client.patch(f"/api/projects/{pid}", json={"settings": {"speed": 5}}).status_code == 422


def test_previews(client, rendered_book):
    project, _ = rendered_book
    response = client.post(f"/api/projects/{project['id']}/preview", json={})
    assert response.status_code == 200 and response.headers["content-type"] in ("audio/mpeg", "audio/wav")
    assert len(response.content) > 1000
    response = client.post("/api/tts/preview", json={"engine": "tone", "voice": "beep", "text": "Hello world"})
    assert response.status_code == 200
    response = client.post("/api/tts/preview", json={"engine": "nope", "voice": "x", "text": "Hello"})
    assert response.status_code == 400


def test_render_creates_library_book(client, rendered_book, data_dir):
    project, book = rendered_book
    assert project["status"] == "done"
    assert all(c["audio_state"] == "ready" for c in project["chapters"] if c["include"])
    assert book["title"] == samples.TITLE and book["format"] == "m4b"
    assert book["path"] == f"{samples.AUTHOR}/Coastal Tales/2 - {samples.TITLE}"
    assert [c["title"] for c in book["chapters"]] == [t for t, _ in samples.CHAPTERS]
    assert book["duration"] > 5
    m4b = data_dir / "library" / book["files"][0]["path"]
    assert m4b.exists()
    assert _ffprobe_chapters(m4b) == [t for t, _ in samples.CHAPTERS]
    folder = m4b.parent
    assert (folder / "cover.jpg").exists() and (folder / "metadata.json").exists()

    # streaming supports HTTP range requests
    response = client.get(f"/api/books/{book['id']}/files/0", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206 and len(response.content) == 100

    # a re-render without changes reuses every chapter
    from audiobook_studio.jobs.runner import runner

    job = client.post(f"/api/projects/{project['id']}/render").json()
    runner.run_pending()
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done" and job["result"]["rendered_chapters"] == 0
    assert client.get(f"/api/projects/{project['id']}").json()["book_id"] == book["id"]


def test_library_queries(client, rendered_book):
    _, book = rendered_book
    books = client.get("/api/books", params={"q": "lighthouse"}).json()
    assert any(b["id"] == book["id"] for b in books)
    assert client.get("/api/books", params={"genre": "Fiction"}).json()
    assert not client.get("/api/books", params={"genre": "Horror"}).json()
    facets = client.get("/api/books/facets").json()
    assert {"value": samples.AUTHOR, "count": 1} in facets["author"]
    for sort in ("title", "author", "added", "duration", "series", "last_played", "rating"):
        assert client.get("/api/books", params={"sort": sort, "order": "asc"}).status_code == 200


def test_progress_and_collections(client, rendered_book):
    _, book = rendered_book
    updated = client.put(f"/api/books/{book['id']}/progress", json={"position": 12.5}).json()
    assert updated["progress"] == 12.5 and updated["last_played_at"]
    assert client.get("/api/books", params={"status": "in_progress"}).json()

    collection = client.post("/api/collections", json={"name": "Sea stories"}).json()
    assert client.post("/api/collections", json={"name": "Sea stories"}).status_code == 409
    collection = client.post(f"/api/collections/{collection['id']}/books", json={"book_ids": [book["id"]]}).json()
    assert collection["book_count"] == 1
    assert client.get("/api/books", params={"collection": collection["id"]}).json()[0]["id"] == book["id"]
    client.delete(f"/api/collections/{collection['id']}/books/{book['id']}")
    assert client.delete(f"/api/collections/{collection['id']}").json()["ok"]


def test_metadata_edit_moves_and_retags(client, rendered_book, run_jobs, data_dir):
    from audiobook_studio.audio.tags import read_tags

    _, book = rendered_book
    response = client.patch(f"/api/books/{book['id']}", json={"author": "A. Winterbourne", "genre": "Sea Fiction", "rating": 4})
    assert response.status_code == 200
    run_jobs()
    book = client.get(f"/api/books/{book['id']}").json()
    assert book["path"].startswith("A. Winterbourne/") and book["rating"] == 4
    m4b = data_dir / "library" / book["files"][0]["path"]
    assert m4b.exists()
    tags = read_tags(m4b)
    assert tags["artist"] == "A. Winterbourne" and tags["genre"] == "Sea Fiction"
    assert not (data_dir / "library" / samples.AUTHOR).exists()  # old folder cleaned up


def test_organize_with_new_template(client, rendered_book, run_jobs, data_dir):
    _, book = rendered_book
    preview = client.post("/api/library/organize/preview", json={"template": "{genre}/{author} - {title}"}).json()
    assert any(m["book_id"] == book["id"] for m in preview["moves"])
    examples = client.post("/api/library/template-preview", json={"template": "{genre}/{title}"}).json()["examples"]
    assert examples
    client.post("/api/library/organize", json={"template": "{genre}/{author} - {title}"})
    run_jobs()
    moved = client.get(f"/api/books/{book['id']}").json()
    assert moved["path"] == f"Sea Fiction/A. Winterbourne - {samples.TITLE}"
    assert (data_dir / "library" / moved["files"][0]["path"]).exists()
    # back to the default layout
    client.post("/api/library/organize", json={"template": "{author}/[{series}/][{series_index} - ]{title}"})
    run_jobs()


def test_scan_imports_existing_audiobooks(client, run_jobs, data_dir):
    folder = data_dir / "library" / "Jane Doe" / "Old Recording"
    folder.mkdir(parents=True)
    for n in (1, 2):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
                        "-metadata", "album=Old Recording", "-metadata", "artist=Jane Doe",
                        "-metadata", f"title=Part {n}", "-metadata", f"track={n}", "-c:a", "libmp3lame",
                        str(folder / f"{n:02d} part.mp3")], check=True)
    job = client.post("/api/library/scan", json={}).json()
    run_jobs()
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["status"] == "done" and result["result"]["added"] == 1
    imported = [b for b in client.get("/api/books", params={"source": "import"}).json() if b["title"] == "Old Recording"]
    assert len(imported) == 1
    assert imported[0]["author"] == "Jane Doe" and len(imported[0]["files"]) == 2
    assert [c["title"] for c in imported[0]["chapters"]] == ["Part 1", "Part 2"]
    # scanning again does not duplicate
    client.post("/api/library/scan", json={})
    run_jobs()
    assert len([b for b in client.get("/api/books").json() if b["title"] == "Old Recording"]) == 1


def test_lexicon(client):
    rule = client.post("/api/lexicon", json={"pattern": "Tobias", "replacement": "Toe-bye-us"}).json()
    assert client.post("/api/lexicon", json={"pattern": "(", "is_regex": True}).status_code == 400
    result = client.post("/api/lexicon/test", json={"text": "Tobias waved at Mr. Hale."}).json()
    assert result["result"] == "Toe-bye-us waved at Mister Hale."
    exported = client.get("/api/lexicon/export").json()["rules"]
    assert exported[0]["pattern"] == "Tobias"
    assert client.patch(f"/api/lexicon/{rule['id']}", json={"enabled": False}).json()["enabled"] is False
    assert client.delete(f"/api/lexicon/{rule['id']}").json()["ok"]


def test_feeds(client, rendered_book):
    _, book = rendered_book
    feed = client.get(f"/feeds/books/{book['id']}.xml")
    assert feed.status_code == 200 and "<enclosure" in feed.text
    library = client.get("/feeds/library.xml")
    assert f"/api/books/{book['id']}/files/0" in library.text


def test_stats_and_system(client, rendered_book):
    stats = client.get("/api/stats").json()
    assert stats["books"] >= 1 and stats["total_duration"] > 0
    system = client.get("/api/system").json()
    assert system["ffmpeg"] != "not installed"
    engines = {e["id"]: e for e in client.get("/api/tts/engines").json()}
    assert "kokoro" in engines and "piper" in engines
    models = client.get("/api/tts/models").json()
    assert [m["id"] for m in models["kokoro"]] == ["kokoro-v1.0", "kokoro-v1.0-int8"]


def test_settings_and_auth(client, rendered_book):
    _, book = rendered_book
    settings = client.get("/api/settings").json()
    assert "password_hash" not in settings and settings["password_set"] is False
    updated = client.patch("/api/settings", json={"render_defaults": {"speed": 1.2}, "inbox_interval": 60}).json()
    assert updated["render_defaults"]["speed"] == 1.2 and updated["render_defaults"]["engine"]
    assert client.patch("/api/settings", json={"inbox_interval": 1}).status_code == 422

    assert client.post("/api/settings/password", json={"new_password": "s3cret"}).json()["enabled"]
    client.cookies.clear()
    assert client.get("/api/books").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "s3cret"}).status_code == 200
    assert client.get("/api/books").status_code == 200
    token = client.get("/api/feeds").json()["library"].split("token=")[1]
    client.cookies.clear()
    assert client.get(f"/api/books/{book['id']}/files/0", params={"token": token}).status_code == 200
    assert client.get(f"/api/books/{book['id']}", params={"token": token}).status_code == 401
    assert client.get("/feeds/library.xml", params={"token": "nope"}).status_code == 401
    client.post("/api/auth/login", json={"password": "s3cret"})
    assert client.post("/api/settings/password", json={"current_password": "s3cret", "new_password": ""}).json()["enabled"] is False


def test_text_project_and_delete(client, run_jobs):
    detail = client.post("/api/projects/text", json={
        "title": "Notes", "text": "# Intro\n\nHello there.\n\n# Outro\n\nGoodbye now."}).json()
    assert [c["title"] for c in detail["chapters"]] == ["Intro", "Outro"]
    client.patch(f"/api/projects/{detail['id']}", json={"settings": {"engine": "tone", "voice": "beep", "output_format": "mp3"}})
    client.post(f"/api/projects/{detail['id']}/render")
    run_jobs()
    detail = client.get(f"/api/projects/{detail['id']}").json()
    book = client.get(f"/api/books/{detail['book_id']}").json()
    assert book["format"] == "mp3" and len(book["files"]) == 2
    assert client.get(f"/api/books/{book['id']}/download").headers["content-type"] == "application/zip"
    assert client.delete(f"/api/projects/{detail['id']}", params={"delete_book": True}).json()["ok"]
    assert client.get(f"/api/books/{book['id']}").status_code == 404


def test_inbox(client, data_dir, run_jobs):
    from audiobook_studio.inbox import watcher

    target = data_dir / "inbox" / "dropped.md"
    samples.make_markdown(target)
    assert watcher.scan_once() == 0  # first sighting: wait until the file is stable
    assert watcher.scan_once() == 1
    assert not target.exists()
    run_jobs()
    projects = client.get("/api/projects").json()
    assert any(p["source_filename"] == "dropped.md" and p["status"] == "ready" for p in projects)
