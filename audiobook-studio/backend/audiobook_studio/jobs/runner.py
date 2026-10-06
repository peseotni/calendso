"""A small persistent background job queue.

Jobs are stored in the database so they survive restarts. Worker threads are
grouped in *lanes*: heavy text-to-speech rendering runs in the ``render`` lane
while light work (imports, downloads, library maintenance) runs in the
``general`` lane, so an hours-long render never blocks a quick import.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Job, utcnow

log = logging.getLogger(__name__)

MAX_LOG_CHARS = 30_000


class JobCancelled(Exception):
    """Raised inside a handler when the job was cancelled."""


@dataclass
class JobSnapshot:
    id: int
    kind: str
    payload: dict[str, Any]
    project_id: int | None
    book_id: int | None
    title: str


HandlerFn = Callable[["JobContext"], dict[str, Any] | None]
_HANDLERS: dict[str, tuple[HandlerFn, str]] = {}


def handler(kind: str, lane: str = "general") -> Callable[[HandlerFn], HandlerFn]:
    def decorator(fn: HandlerFn) -> HandlerFn:
        _HANDLERS[kind] = (fn, lane)
        return fn

    return decorator


def lane_for(kind: str) -> str:
    entry = _HANDLERS.get(kind)
    return entry[1] if entry else "general"


@dataclass
class JobContext:
    job: JobSnapshot
    runner: JobRunner
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _progress: float = 0.0
    _message: str = ""
    _log_lines: list[str] = field(default_factory=list)
    _dirty: bool = False
    _last_flush: float = 0.0
    started: float = field(default_factory=time.monotonic)

    @property
    def payload(self) -> dict[str, Any]:
        return self.job.payload

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()

    def progress(self, fraction: float | None = None, message: str | None = None) -> None:
        if fraction is not None:
            self._progress = max(0.0, min(1.0, fraction))
        if message is not None and message != self._message:
            self._message = message
            self._dirty = True
            self.flush(force=True)
            return
        self._dirty = True
        self.flush()

    def log(self, line: str) -> None:
        log.info("[job %s] %s", self.job.id, line)
        self._log_lines.append(f"{time.strftime('%H:%M:%S')} {line}")
        self._dirty = True
        self.flush()

    def flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if not self._dirty or (not force and now - self._last_flush < 0.75):
            return
        self._last_flush = now
        self._dirty = False
        lines, self._log_lines = self._log_lines, []
        try:
            with session_scope() as session:
                job = session.get(Job, self.job.id)
                if job is None:
                    return
                job.progress = self._progress
                job.message = self._message[:500]
                if lines:
                    job.log = ((job.log or "") + "\n".join(lines) + "\n")[-MAX_LOG_CHARS:]
                if job.status == "cancelled" or (job.status != "running"):
                    # Cancelled from another process / deleted state
                    self.cancel_event.set()
        except Exception:  # pragma: no cover - progress must never kill a job
            log.exception("Could not persist job progress")


class JobRunner:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._claim_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._active: dict[int, JobContext] = {}

    # ----------------------------------------------------------- lifecycle
    def start(self, lanes: dict[str, int]) -> None:
        self.recover()
        self._stop.clear()
        for lane, count in lanes.items():
            for index in range(max(1, count)):
                thread = threading.Thread(
                    target=self._loop, args=(lane,), name=f"jobs-{lane}-{index}", daemon=True
                )
                thread.start()
                self._threads.append(thread)
        log.info("Job runner started with lanes %s", lanes)

    def stop(self) -> None:
        self._stop.set()
        for ctx in list(self._active.values()):
            ctx.cancel_event.set()
        with self._cond:
            self._cond.notify_all()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()

    def recover(self) -> None:
        """Re-queue jobs that were running when the process stopped."""
        with session_scope() as session:
            stale = session.query(Job).filter(Job.status == "running").all()
            for job in stale:
                job.status = "queued"
                job.started_at = None
                job.message = "Resuming after restart"

    def notify(self) -> None:
        with self._cond:
            self._cond.notify_all()

    # ------------------------------------------------------------- queueing
    def enqueue(
        self,
        session: Session,
        kind: str,
        title: str,
        payload: dict[str, Any] | None = None,
        project_id: int | None = None,
        book_id: int | None = None,
    ) -> Job:
        job = Job(
            kind=kind,
            lane=lane_for(kind),
            title=title,
            payload=payload or {},
            project_id=project_id,
            book_id=book_id,
            status="queued",
        )
        session.add(job)
        session.commit()
        self.notify()
        return job

    def cancel(self, job_id: int) -> bool:
        ctx = self._active.get(job_id)
        if ctx is not None:
            ctx.cancel_event.set()
            return True
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None and job.status in ("queued", "running"):
                job.status = "cancelled"
                job.finished_at = utcnow()
                job.message = "Cancelled"
                return True
        return False

    def is_active(self, job_id: int) -> bool:
        return job_id in self._active

    # -------------------------------------------------------------- workers
    def _claim(self, lane: str) -> JobSnapshot | None:
        with self._claim_lock, session_scope() as session:
            running_projects = {
                pid
                for (pid,) in session.query(Job.project_id).filter(
                    Job.status == "running", Job.project_id.isnot(None)
                )
            }
            candidates = (
                session.query(Job)
                .filter(Job.status == "queued", Job.lane == lane)
                .order_by(Job.id)
                .limit(50)
                .all()
            )
            for job in candidates:
                if job.project_id is not None and job.project_id in running_projects:
                    continue
                job.status = "running"
                job.started_at = utcnow()
                job.finished_at = None
                job.progress = 0.0
                job.error = ""
                job.message = "Starting"
                return JobSnapshot(
                    id=job.id,
                    kind=job.kind,
                    payload=dict(job.payload or {}),
                    project_id=job.project_id,
                    book_id=job.book_id,
                    title=job.title,
                )
        return None

    def _loop(self, lane: str) -> None:
        while not self._stop.is_set():
            try:
                snapshot = self._claim(lane)
            except Exception:  # pragma: no cover - db hiccup
                log.exception("Failed to claim job")
                snapshot = None
            if snapshot is None:
                with self._cond:
                    self._cond.wait(timeout=2.0)
                continue
            self.execute(snapshot)

    def execute(self, snapshot: JobSnapshot) -> None:
        entry = _HANDLERS.get(snapshot.kind)
        ctx = JobContext(job=snapshot, runner=self)
        self._active[snapshot.id] = ctx
        status, error, result = "done", "", {}
        try:
            if entry is None:
                raise RuntimeError(f"No handler for job kind '{snapshot.kind}'")
            result = entry[0](ctx) or {}
        except JobCancelled:
            status = "cancelled"
            ctx.log("Cancelled")
        except Exception as exc:  # noqa: BLE001 - report every failure
            status = "error"
            error = str(exc) or exc.__class__.__name__
            log.exception("Job %s (%s) failed", snapshot.id, snapshot.kind)
            ctx.log("Error: " + error)
            ctx._log_lines.append(traceback.format_exc()[-4000:])
        finally:
            self._active.pop(snapshot.id, None)

        ctx._dirty = True
        ctx.flush(force=True)
        with session_scope() as session:
            job = session.get(Job, snapshot.id)
            if job is not None:
                job.status = status
                job.error = error
                job.result = result
                job.finished_at = utcnow()
                if status == "done":
                    job.progress = 1.0
                    job.message = result.get("message", "Finished") if result else "Finished"
                elif status == "cancelled":
                    job.message = "Cancelled"
                else:
                    job.message = "Failed"
        self.notify()

    def run_pending(self, lane: str | None = None, limit: int = 100) -> int:
        """Synchronously process queued jobs (used by tests and the CLI)."""
        count = 0
        lanes = [lane] if lane else sorted({entry[1] for entry in _HANDLERS.values()} | {"general"})
        while count < limit:
            snapshot = None
            for current in lanes:
                snapshot = self._claim(current)
                if snapshot:
                    break
            if snapshot is None:
                break
            self.execute(snapshot)
            count += 1
        return count


runner = JobRunner()
