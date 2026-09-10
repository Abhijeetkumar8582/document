"""Durable job queue on top of the database.

Guarantees:
  * A file is written to disk and its Job row committed before the upload request returns.
  * A job is claimed with a lease. If the worker dies, the lease expires and another worker picks it up.
  * Failures retry with exponential backoff up to max_attempts, then park as `dead` for a manual retry.
  * A batch is finished only when every job is in a terminal state (done, skipped, dead, cancelled).

SQLite: claims are serialised with a process-level lock, which is correct for one API process.
Postgres: replace `claim()` with `SELECT ... FOR UPDATE SKIP LOCKED` and run workers in as many processes as you like.
"""
from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .. import models
from ..config import worker_settings
from . import extractor

# Legacy staging directory. New batches never write here; the worker still reads it for jobs created before
# uploads went straight to storage.
INCOMING_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "incoming"

TERMINAL = ("done", "skipped", "dead", "cancelled")
_claim_lock = threading.Lock()


@dataclass
class Incoming:
    file_name: str
    content_type: str | None
    data: bytes


class BatchError(Exception):
    pass


# --- Intake ----------------------------------------------------------------------


def expand(files: list[Incoming]) -> list[Incoming]:
    """Unpack ZIP archives into their supported member files. Everything else passes through."""
    out: list[Incoming] = []
    for f in files:
        if not f.file_name.lower().endswith(".zip"):
            out.append(f)
            continue
        try:
            zf = zipfile.ZipFile(io.BytesIO(f.data))
        except zipfile.BadZipFile as exc:
            raise BatchError(f"{f.file_name} is not a valid ZIP archive.") from exc
        members = [m for m in zf.infolist() if not m.is_dir() and not m.filename.startswith("__MACOSX/")]
        if len(members) > worker_settings.max_zip_entries:
            raise BatchError(f"{f.file_name} holds {len(members)} files; the limit is {worker_settings.max_zip_entries}.")
        total = sum(m.file_size for m in members)
        if total > worker_settings.max_batch_bytes:
            raise BatchError(f"{f.file_name} expands to {total / 1e9:.1f} GB, above the batch limit.")
        for m in members:
            name = Path(m.filename).name
            try:
                extractor.detect_kind(name, None)
            except extractor.UnsupportedFile:
                continue  # readme.txt would pass; .DS_Store and friends do not
            out.append(Incoming(file_name=f"{Path(f.file_name).stem}/{name}", content_type=None, data=zf.read(m)))
    return out


def create_batch(db: Session, files: list[Incoming], mode: str, actor: str, name: str = "") -> models.Batch:
    """Put every file into permanent storage and record a job row for it. Commit once, so the batch is all-or-nothing.

    Nothing is staged on local disk: with the S3 backend the bytes go straight to the bucket.
    """
    from . import storage as storage_svc

    files = expand(files)
    if not files:
        raise BatchError("No supported files were found in the upload.")
    store = storage_svc.get_storage()
    batch = models.Batch(name=name or f"{len(files)} files", mode=mode, actor=actor, total_jobs=len(files))
    db.add(batch)
    db.flush()

    written: list[str] = []
    seen_hashes: set[str] = set()
    try:
        for f in files:
            digest = hashlib.sha256(f.data).hexdigest()
            key = storage_svc.new_key(f.file_name)
            job = models.Job(
                batch_id=batch.id,
                file_name=f.file_name[:255],
                content_type=f.content_type,
                file_size=len(f.data),
                sha256=digest,
                stored_path=key,
                source="storage",
                mode=mode,
                max_attempts=worker_settings.max_attempts,
            )
            # Same bytes twice in one batch: store and file it once, mark the twin as skipped.
            if digest in seen_hashes:
                job.status = "skipped"
                job.error = "Identical file already in this batch."
                job.finished_at = datetime.utcnow()
            else:
                store.put(key, f.data, f.content_type)
                written.append(key)
            seen_hashes.add(digest)
            batch.total_bytes += len(f.data)
            db.add(job)
        db.commit()
    except Exception:
        db.rollback()
        for k in written:
            try:
                store.delete(k)
            except Exception:
                pass
        raise
    db.refresh(batch)
    return batch


@dataclass
class StoredItem:
    key: str
    file_name: str
    content_type: str | None = None
    size: int = 0


def create_batch_from_keys(db: Session, items: list[StoredItem], mode: str, actor: str, name: str = "") -> models.Batch:
    """Batch over objects the browser already put in storage with presigned POSTs. Nothing is copied."""
    from . import storage as storage_svc

    if not items:
        raise BatchError("No uploaded files were listed.")
    store = storage_svc.get_storage()
    for it in items:
        if not storage_svc.valid_key(it.key) or not it.key.startswith("records/"):
            raise BatchError(f"Invalid storage key for {it.file_name}.")
        if not store.exists(it.key):
            raise BatchError(f"{it.file_name} was not found in storage. The upload may not have finished.")
    batch = models.Batch(name=name or f"{len(items)} files", mode=mode, actor=actor, total_jobs=len(items))
    db.add(batch)
    db.flush()
    seen: set[str] = set()
    for it in items:
        job = models.Job(
            batch_id=batch.id,
            file_name=it.file_name[:255],
            content_type=it.content_type,
            file_size=it.size,
            sha256="",  # computed by the worker once it reads the object
            stored_path=it.key,
            source="storage",
            mode=mode,
            max_attempts=worker_settings.max_attempts,
        )
        if it.key in seen:
            job.status = "skipped"
            job.error = "Listed twice in this batch."
            job.finished_at = datetime.utcnow()
        seen.add(it.key)
        batch.total_bytes += it.size
        db.add(job)
    db.commit()
    db.refresh(batch)
    return batch


# --- Worker side --------------------------------------------------------------------


def reclaim_stale(db: Session) -> int:
    """Jobs whose worker went silent go back to the queue. Called on startup and periodically."""
    now = datetime.utcnow()
    res = db.execute(
        update(models.Job)
        .where(models.Job.status == "processing", models.Job.lease_expires_at < now)
        .values(status="queued", worker_id=None, lease_expires_at=None, stage="requeued after lost lease")
    )
    db.commit()
    return res.rowcount or 0


def repair_batches(db: Session) -> int:
    """Recompute status for every batch that thinks it is still moving. Run at startup."""
    ids = db.scalars(select(models.Batch.id).where(models.Batch.status.in_(("queued", "running")))).all()
    for batch_id in ids:
        _rollup(db, batch_id)
    db.commit()
    return len(ids)


def claim(db: Session, worker_id: str) -> models.Job | None:
    """Take the oldest runnable job. Returns None when there is nothing to do."""
    now = datetime.utcnow()
    with _claim_lock:
        job = db.scalar(
            select(models.Job)
            .where(
                or_(
                    models.Job.status == "queued",
                    (models.Job.status == "failed") & (models.Job.next_attempt_at <= now),
                )
            )
            .order_by(models.Job.next_attempt_at.asc().nulls_first(), models.Job.id.asc())
            .limit(1)
        )
        if job is None:
            return None
        job.status = "processing"
        job.worker_id = worker_id
        job.attempts += 1
        job.started_at = job.started_at or now
        job.lease_expires_at = now + timedelta(seconds=worker_settings.lease_seconds)
        job.stage = "starting"
        job.progress_done = 0
        job.progress_total = 0
        job.error = None
        batch = db.get(models.Batch, job.batch_id)
        if batch and batch.status in ("queued", "attention"):
            batch.status = "running"
            batch.started_at = batch.started_at or now
        db.commit()
        db.refresh(job)
        return job


def heartbeat(db: Session, job_id: int, stage: str, done: int, total: int) -> None:
    db.execute(
        update(models.Job)
        .where(models.Job.id == job_id)
        .values(
            stage=stage[:60],
            progress_done=done,
            progress_total=total,
            lease_expires_at=datetime.utcnow() + timedelta(seconds=worker_settings.lease_seconds),
        )
    )
    db.commit()


def complete(db: Session, job: models.Job, record_id: int) -> None:
    job.status = "done"
    job.record_id = record_id
    job.stage = "filed"
    job.finished_at = datetime.utcnow()
    job.lease_expires_at = None
    _rollup(db, job.batch_id)
    db.commit()


def fail(db: Session, job: models.Job, message: str, permanent: bool = False) -> None:
    job.error = message[:2000]
    job.lease_expires_at = None
    if permanent or job.attempts >= job.max_attempts:
        job.status = "dead"
        job.stage = "gave up" if not permanent else "rejected"
        job.finished_at = datetime.utcnow()
    else:
        delay = worker_settings.backoff_base_seconds * (2 ** (job.attempts - 1))
        job.status = "failed"
        job.stage = f"retry in {delay}s"
        job.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
    _rollup(db, job.batch_id)
    db.commit()


def retry(db: Session, job: models.Job) -> None:
    job.status = "queued"
    job.attempts = 0
    job.error = None
    job.next_attempt_at = None
    job.finished_at = None
    job.stage = "requeued by hand"
    _rollup(db, job.batch_id)
    db.commit()


def cancel_batch(db: Session, batch: models.Batch) -> int:
    n = 0
    for job in batch.jobs:
        if job.status in ("queued", "failed"):
            job.status = "cancelled"
            job.finished_at = datetime.utcnow()
            job.stage = "cancelled"
            n += 1
    _rollup(db, batch.id)
    db.commit()
    return n


def _rollup(db: Session, batch_id: int) -> None:
    """Derive batch status from its jobs. The batch is finished only when nothing is still runnable."""
    db.flush()  # the session has autoflush off; make this job's own transition visible to the count below
    batch = db.get(models.Batch, batch_id)
    if not batch:
        return
    counts = dict(
        db.execute(select(models.Job.status, func.count()).where(models.Job.batch_id == batch_id).group_by(models.Job.status)).all()
    )
    active = counts.get("queued", 0) + counts.get("processing", 0) + counts.get("failed", 0)
    if active:
        batch.status = "running"
        batch.finished_at = None
    elif counts.get("dead", 0):
        batch.status = "attention"
        batch.finished_at = datetime.utcnow()
    elif counts.get("cancelled", 0) and not counts.get("done", 0):
        batch.status = "cancelled"
        batch.finished_at = datetime.utcnow()
    else:
        batch.status = "completed"
        batch.finished_at = datetime.utcnow()


def counts_for(db: Session, batch_id: int) -> dict[str, int]:
    rows = db.execute(select(models.Job.status, func.count()).where(models.Job.batch_id == batch_id).group_by(models.Job.status)).all()
    return {status: n for status, n in rows}


def find_duplicate(db: Session, sha256: str, exclude_job_id: int) -> int | None:
    """A record already filed from identical bytes, in any earlier batch."""
    if not sha256:
        return None
    # Join to records so a file whose earlier record was deleted is filed again, not skipped.
    return db.scalar(
        select(models.Job.record_id)
        .join(models.Record, models.Record.id == models.Job.record_id)
        .where(models.Job.sha256 == sha256, models.Job.status == "done", models.Job.id != exclude_job_id)
        .order_by(models.Job.id.asc())
        .limit(1)
    )
