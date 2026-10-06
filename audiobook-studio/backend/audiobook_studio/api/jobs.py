"""Background job queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..jobs.runner import runner
from ..models import Job, Project
from ..schemas import JobDetail, JobOut
from .common import get_or_404, job_out

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(status: str | None = None, limit: int = 100, session: Session = Depends(get_db)):
    query = session.query(Job)
    if status == "active":
        query = query.filter(Job.status.in_(("queued", "running")))
    elif status:
        query = query.filter(Job.status == status)
    jobs = query.order_by(Job.id.desc()).limit(max(1, min(limit, 500))).all()
    return [job_out(j) for j in jobs]


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int, session: Session = Depends(get_db)):
    return job_out(get_or_404(session, Job, job_id, "Job"), detail=True)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, session: Session = Depends(get_db)):
    job = get_or_404(session, Job, job_id, "Job")
    ok = runner.cancel(job.id)
    if ok and job.project_id and job.kind == "render":
        project = session.get(Project, job.project_id)
        session.refresh(job)
        if project is not None and project.status == "queued":
            project.status = "ready"
            session.commit()
    return {"ok": ok}


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, session: Session = Depends(get_db)):
    job = get_or_404(session, Job, job_id, "Job")
    if job.status not in ("error", "cancelled"):
        raise HTTPException(400, "Only failed or cancelled jobs can be retried.")
    if job.kind == "render" and job.project_id:
        project = session.get(Project, job.project_id)
        if project is None:
            raise HTTPException(404, "The project no longer exists.")
        project.status = "queued"
        project.error = ""
    if job.kind == "ingest" and job.project_id:
        project = session.get(Project, job.project_id)
        if project is not None:
            project.status = "importing"
            project.error = ""
    session.commit()
    new_job = runner.enqueue(session, job.kind, job.title, dict(job.payload or {}), job.project_id, job.book_id)
    return job_out(new_job)


@router.delete("/{job_id}")
def delete_job(job_id: int, session: Session = Depends(get_db)):
    job = get_or_404(session, Job, job_id, "Job")
    if job.status in ("queued", "running"):
        raise HTTPException(400, "Cancel the job before removing it.")
    session.delete(job)
    session.commit()
    return {"ok": True}


@router.post("/clear")
def clear_finished(session: Session = Depends(get_db)):
    count = session.query(Job).filter(Job.status.in_(("done", "cancelled", "error"))).delete(synchronize_session=False)
    session.commit()
    return {"removed": count}
