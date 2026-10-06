"""Watch folder: ebooks dropped into the inbox are imported automatically."""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
from pathlib import Path

from . import settings_store, studio
from .config import get_config
from .db import session_scope
from .ingest import detect_format

log = logging.getLogger(__name__)

SKIP_DIRS = {"failed", "processed", ".tmp"}


class InboxWatcher:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[Path, tuple[int, float]] = {}
        self.last_scan: float | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="inbox-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            interval = 30
            try:
                settings = settings_store.current()
                interval = settings.inbox_interval
                if settings.inbox_enabled:
                    self.scan_once(settings.inbox_auto_render)
            except Exception:  # noqa: BLE001 - keep watching
                log.exception("Inbox scan failed")
            self._stop.wait(interval)

    def candidates(self) -> list[Path]:
        root = get_config().inbox_path
        if not root.exists():
            return []
        files = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
                continue
            if detect_format(path.name):
                files.append(path)
        return files

    def scan_once(self, auto_render: bool = False, require_stable: bool = True) -> int:
        """Import stable files; returns the number of projects created."""
        import time

        self.last_scan = time.time()
        created = 0
        current = set()
        for path in self.candidates():
            current.add(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            signature = (stat.st_size, stat.st_mtime)
            if require_stable and self._seen.get(path) != signature:
                self._seen[path] = signature  # wait one more round until the copy finished
                continue
            self._seen.pop(path, None)
            if self._import(path, auto_render):
                created += 1
        for path in list(self._seen):
            if path not in current:
                self._seen.pop(path, None)
        return created

    def _import(self, path: Path, auto_render: bool) -> bool:
        root = get_config().inbox_path
        tmp_dir = Path(tempfile.mkdtemp(dir=get_config().tmp_path))
        staged = tmp_dir / path.name
        try:
            shutil.move(str(path), staged)
            with session_scope() as session:
                project = studio.create_project_from_file(
                    session, path.name, staged, {"auto_render": auto_render, "origin": "inbox"}
                )
                log.info("Inbox: imported %s as project %s", path.name, project.id)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Inbox: could not import %s: %s", path.name, exc)
            failed = root / "failed"
            failed.mkdir(parents=True, exist_ok=True)
            if staged.exists():
                shutil.move(str(staged), failed / path.name)
            (failed / f"{path.name}.error.txt").write_text(str(exc), encoding="utf-8")
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


watcher = InboxWatcher()
