from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, models, schemas, worker
from ..database import get_db
from ..services import queue

router = APIRouter(prefix="/api", tags=["batches"])

MAX_FILE_BYTES = 25 * 1024 * 1024


def _batch_out(db: Session, b: models.Batch) -> schemas.BatchOut:
    counts = queue.counts_for(db, b.id)
    done = counts.get("done", 0) + counts.get("skipped", 0) + counts.get("dead", 0) + counts.get("cancelled", 0)
    return schemas.BatchOut(
        id=b.id,
        name=b.name,
        mode=b.mode,
        actor=b.actor,
        status=b.status,
        total_jobs=b.total_jobs,
        total_bytes=b.total_bytes,
        counts=schemas.JobCounts(**{k: counts.get(k, 0) for k in schemas.JobCounts.model_fields}),
        finished_jobs=done,
        created_at=b.created_at,
        started_at=b.started_at,
        finished_at=b.finished_at,
    )


@router.post("/batches", response_model=schemas.BatchOut, status_code=202)
async def create_batch(
    request: Request,
    files: list[UploadFile],
    mode: str = Query("auto", pattern="^(auto|text|google_docai|llm_vision|ocr)$"),
    name: str = Query(""),
    db: Session = Depends(get_db),
):
    incoming: list[queue.Incoming] = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        if len(data) > MAX_FILE_BYTES and not (f.filename or "").lower().endswith(".zip"):
            raise HTTPException(413, f"{f.filename} is larger than 25 MB.")
        incoming.append(queue.Incoming(file_name=f.filename or "upload", content_type=f.content_type, data=data))
    if not incoming:
        raise HTTPException(400, "No files were received.")
    try:
        batch = queue.create_batch(db, incoming, mode, audit.actor_of(request), name)
    except queue.BatchError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit.log(db, request, "batch_upload", None, f"batch #{batch.id}: {batch.total_jobs} files, {batch.total_bytes:,} bytes")
    db.commit()
    worker.pool.nudge()
    return _batch_out(db, batch)


class KeyItem(BaseModel):
    key: str
    file_name: str
    content_type: str | None = None
    size: int = 0


class FromKeysRequest(BaseModel):
    items: list[KeyItem]
    mode: str = "auto"
    name: str = ""


@router.post("/batches/from-keys", response_model=schemas.BatchOut, status_code=202)
def create_batch_from_keys(body: FromKeysRequest, request: Request, db: Session = Depends(get_db)):
    """Batch over files the browser already uploaded with presigned POSTs. Processing runs in the background."""
    mode = body.mode if body.mode in ("auto", "text", "google_docai", "llm_vision", "ocr") else "auto"
    items = [queue.StoredItem(key=i.key, file_name=i.file_name, content_type=i.content_type, size=i.size) for i in body.items]
    try:
        batch = queue.create_batch_from_keys(db, items, mode, audit.actor_of(request), body.name)
    except queue.BatchError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit.log(db, request, "batch_upload", None, f"batch #{batch.id}: {batch.total_jobs} files (direct to storage)")
    db.commit()
    worker.pool.nudge()
    return _batch_out(db, batch)


@router.get("/batches", response_model=schemas.BatchPage)
def list_batches(
    db: Session = Depends(get_db),
    status: str | None = Query(None, pattern="^(queued|running|completed|attention|cancelled)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    stmt = select(models.Batch)
    if status:
        stmt = stmt.where(models.Batch.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(models.Batch.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return schemas.BatchPage(items=[_batch_out(db, b) for b in rows], total=total, page=page, page_size=page_size)


@router.get("/batches/summary", response_model=schemas.QueueSummary)
def queue_summary(db: Session = Depends(get_db)):
    rows = db.execute(select(models.Job.status, func.count()).group_by(models.Job.status)).all()
    counts = {s: n for s, n in rows}
    active = db.scalar(select(func.count()).select_from(models.Batch).where(models.Batch.status == "running")) or 0
    return schemas.QueueSummary(
        queued=counts.get("queued", 0) + counts.get("failed", 0),
        processing=counts.get("processing", 0),
        dead=counts.get("dead", 0),
        running_batches=active,
        workers=max(1, worker.worker_settings.concurrency),
    )


@router.get("/batches/{batch_id}", response_model=schemas.BatchOut)
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    b = db.get(models.Batch, batch_id)
    if not b:
        raise HTTPException(404, "Batch not found")
    return _batch_out(db, b)


@router.get("/batches/{batch_id}/jobs", response_model=schemas.JobPage)
def list_jobs(
    batch_id: int,
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    if not db.get(models.Batch, batch_id):
        raise HTTPException(404, "Batch not found")
    stmt = select(models.Job).where(models.Job.batch_id == batch_id)
    if status:
        stmt = stmt.where(models.Job.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(models.Job.id.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return schemas.JobPage(items=rows, total=total, page=page, page_size=page_size)


@router.post("/batches/{batch_id}/retry", response_model=schemas.BatchOut)
def retry_batch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    """Requeue every dead job in the batch."""
    b = db.scalar(select(models.Batch).options(selectinload(models.Batch.jobs)).where(models.Batch.id == batch_id))
    if not b:
        raise HTTPException(404, "Batch not found")
    n = 0
    for job in b.jobs:
        if job.status == "dead":
            queue.retry(db, job)
            n += 1
    audit.log(db, request, "batch_retry", None, f"batch #{b.id}: {n} job(s) requeued")
    db.commit()
    worker.pool.nudge()
    return _batch_out(db, b)


@router.post("/batches/{batch_id}/cancel", response_model=schemas.BatchOut)
def cancel_batch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    b = db.scalar(select(models.Batch).options(selectinload(models.Batch.jobs)).where(models.Batch.id == batch_id))
    if not b:
        raise HTTPException(404, "Batch not found")
    n = queue.cancel_batch(db, b)
    audit.log(db, request, "batch_cancel", None, f"batch #{b.id}: {n} job(s) cancelled")
    db.commit()
    return _batch_out(db, b)


@router.post("/jobs/{job_id}/retry", response_model=schemas.JobOut)
def retry_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("dead", "cancelled", "failed"):
        raise HTTPException(409, f"Job is {job.status}; only dead, failed or cancelled jobs can be retried.")
    queue.retry(db, job)
    audit.log(db, request, "job_retry", job.record_id, f"job #{job.id} ({job.file_name}) requeued")
    db.commit()
    worker.pool.nudge()
    return schemas.JobOut.model_validate(job)
