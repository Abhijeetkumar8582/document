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
from ..config import settings, worker_settings
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


def expand(files: list[Incoming]):
    """Yield supported files one at a time, unpacking ZIP archives as it goes.

    A generator, so a 1,000-file ZIP never has all its members in memory at once: each member is read,
    handed to the caller (which puts it in storage), and dropped before the next one is opened.
    """
    for f in files:
        if not f.file_name.lower().endswith(".zip"):
            yield f
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
            if m.file_size > settings.max_upload_bytes:
                raise BatchError(f"{name} inside {f.file_name} is larger than {settings.max_upload_bytes // (1024 * 1024)} MB.")
            yield Incoming(file_name=f"{Path(f.file_name).stem}/{name}", content_type=None, data=zf.read(m))


def create_batch(db: Session, files: list[Incoming], mode: str, actor: str, name: str = "") -> models.Batch:
    """Put every file into permanent storage and record a job row for it. Commit once, so the batch is all-or-nothing.

    Nothing is staged on local disk: with the S3 backend the bytes go straight to the bucket.
    """
    from . import storage as storage_svc

    store = storage_svc.get_storage()
    batch = models.Batch(name=name or "upload", mode=mode, actor=actor, total_jobs=0)
    db.add(batch)
    db.flush()

    written: list[str] = []
    seen_hashes: set[str] = set()
    count = 0
    try:
        for f in expand(files):
            count += 1
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
        if count == 0:
            raise BatchError("No supported files were found in the upload.")
        batch.total_jobs = count
        if not name:
            batch.name = f"{count} files"
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
        if key_in_use(db, it.key):
            raise BatchError(f"{it.file_name} has already been submitted. Upload it again to file it a second time.")
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


def key_in_use(db: Session, key: str) -> bool:
    """A storage key may back exactly one record or one live job; a second claim would let one delete the other's file."""
    if db.scalar(select(models.Record.id).where(models.Record.stored_path == key).limit(1)):
        return True
    return bool(
        db.scalar(select(models.Job.id).where(models.Job.stored_path == key, models.Job.status.not_in(("skipped", "cancelled"))).limit(1))
    )


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
    """Take the oldest runnable job. Returns None when there is nothing to do.

    The take is a conditional UPDATE (status must still be runnable), so two workers, or a worker and a
    hand retry, cannot both own one job. Jobs that have burnt all attempts through crashes are parked as dead.
    """
    runnable = or_(
        models.Job.status == "queued",
        (models.Job.status == "failed") & (models.Job.next_attempt_at <= datetime.utcnow()),
    )
    with _claim_lock:
        for _ in range(10):
            now = datetime.utcnow()
            job_id = db.scalar(
                select(models.Job.id).where(runnable).order_by(models.Job.next_attempt_at.asc().nulls_first(), models.Job.id.asc()).limit(1)
            )
            if job_id is None:
                return None
            job = db.get(models.Job, job_id)
            if job is None:
                continue
            if job.attempts >= job.max_attempts:
                # Claimed max_attempts times without ever reaching fail(): the process died mid-job each time.
                job.status = "dead"
                job.stage = "gave up"
                job.error = job.error or "The server stopped while processing this file, repeatedly."
                job.finished_at = now
                job.lease_expires_at = None
                _rollup(db, job.batch_id)
                db.commit()
                continue
            res = db.execute(
                update(models.Job)
                .where(models.Job.id == job_id, models.Job.status.in_(("queued", "failed")))
                .values(
                    status="processing",
                    worker_id=worker_id,
                    attempts=models.Job.attempts + 1,
                    started_at=job.started_at or now,
                    lease_expires_at=now + timedelta(seconds=worker_settings.lease_seconds),
                    stage="starting",
                    progress_done=0,
                    progress_total=0,
                    error=None,
                )
            )
            if not res.rowcount:
                db.rollback()
                continue
            batch = db.get(models.Batch, job.batch_id)
            if batch and batch.status in ("queued", "attention"):
                batch.status = "running"
                batch.started_at = batch.started_at or now
            db.commit()
            db.refresh(job)
            return job
        return None


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


def _still_mine(db: Session, job: models.Job) -> bool:
    """True only if this worker still holds the job. A lost lease means someone else owns it now."""
    return bool(
        db.scalar(
            select(models.Job.id).where(models.Job.id == job.id, models.Job.status == "processing", models.Job.worker_id == job.worker_id)
        )
    )


def complete(db: Session, job: models.Job, record_id: int) -> bool:
    """Mark filed. Returns False (and rolls back the caller's pending record) if the lease was lost meanwhile."""
    if not _still_mine(db, job):
        db.rollback()
        return False
    job.status = "done"
    job.record_id = record_id
    job.stage = "filed"
    job.finished_at = datetime.utcnow()
    job.lease_expires_at = None
    _rollup(db, job.batch_id)
    db.commit()
    return True


def fail(db: Session, job: models.Job, message: str, permanent: bool = False) -> bool:
    if not _still_mine(db, job):
        db.rollback()
        return False
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
    return True


def retry(db: Session, job: models.Job) -> bool:
    """Requeue by hand. Conditional so it cannot yank a job a worker has just taken."""
    res = db.execute(
        update(models.Job)
        .where(models.Job.id == job.id, models.Job.status.in_(("dead", "cancelled", "failed")))
        .values(status="queued", attempts=0, error=None, next_attempt_at=None, finished_at=None, worker_id=None, lease_expires_at=None, stage="requeued by hand")
    )
    if not res.rowcount:
        db.rollback()
        return False
    _rollup(db, job.batch_id)
    db.commit()
    db.refresh(job)
    return True


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


def backfill_record_hashes(db: Session, limit: int = 500) -> int:
    """Records filed before content hashes existed: compute them from stored bytes so dedupe covers them."""
    from . import storage as storage_svc

    store = storage_svc.get_storage()
    rows = db.scalars(select(models.Record).where(models.Record.sha256.is_(None)).limit(limit)).all()
    n = 0
    for rec in rows:
        try:
            rec.sha256 = hashlib.sha256(store.get(rec.stored_path)).hexdigest()
            n += 1
        except Exception:
            rec.sha256 = ""  # file gone; never mark as duplicate, never retry
    db.commit()
    return n


def detach_record(db: Session, record_id: int) -> None:
    """Called when a record is deleted: jobs that produced it must not keep pointing at a reusable id."""
    db.execute(
        update(models.Job)
        .where(or_(models.Job.record_id == record_id, models.Job.duplicate_of == record_id))
        .values(record_id=None, duplicate_of=None)
    )


def find_duplicate(db: Session, sha256: str, exclude_job_id: int) -> int | None:
    """A record already filed from identical bytes, in any earlier batch."""
    if not sha256:
        return None
    # Key on the record's own content hash. Job rows are not used: SQLite reuses ids after deletes, so a
    # stale job.record_id can point at an unrelated newer record.
    return db.scalar(
        select(models.Record.id).where(models.Record.sha256 == sha256, models.Record.sha256 != "").order_by(models.Record.id.asc()).limit(1)
    )
