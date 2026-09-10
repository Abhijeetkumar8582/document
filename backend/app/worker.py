"""Background workers: N threads that drain the job queue while the API serves requests.

Each thread: claim -> heartbeat while working -> file the record -> complete, or fail with backoff.
Started and stopped by the FastAPI lifespan. Safe to run with concurrency 1 for LLM rate limits.
"""
from __future__ import annotations

import hashlib
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime

from . import models
from .config import worker_settings
from .database import SessionLocal
from .services import ingest, queue, storage

log = logging.getLogger("registrar.worker")


class WorkerPool:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._wake = threading.Event()
        self.host = f"{socket.gethostname()}:{os.getpid()}"

    # -- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        with SessionLocal() as db:
            reclaimed = queue.reclaim_stale(db)
            if reclaimed:
                log.warning("reclaimed %d job(s) left mid-flight by a previous run", reclaimed)
            repaired = queue.repair_batches(db)
            if repaired:
                log.info("re-rolled status for %d open batch(es)", repaired)
        for i in range(max(1, worker_settings.concurrency)):
            t = threading.Thread(target=self._run, name=f"worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        janitor = threading.Thread(target=self._janitor, name="worker-janitor", daemon=True)
        janitor.start()
        self._threads.append(janitor)
        log.info("started %d worker thread(s)", worker_settings.concurrency)

    def stop(self, timeout: float = 30.0) -> None:
        """Let in-flight jobs finish; anything still running when we exit is reclaimed by lease expiry."""
        self._stop.set()
        self._wake.set()
        deadline = time.time() + timeout
        for t in self._threads:
            t.join(max(0.0, deadline - time.time()))

    def nudge(self) -> None:
        """Called after a batch is created so workers do not wait for the next poll."""
        self._wake.set()

    # -- loops ------------------------------------------------------------------------

    def _janitor(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(worker_settings.lease_seconds / 2)
            if self._stop.is_set():
                break
            try:
                with SessionLocal() as db:
                    n = queue.reclaim_stale(db)
                    if n:
                        log.warning("janitor requeued %d stale job(s)", n)
                        self._wake.set()
            except Exception:
                log.exception("janitor pass failed")

    def _run(self) -> None:
        worker_id = f"{self.host}/{threading.current_thread().name}/{uuid.uuid4().hex[:6]}"
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    job = queue.claim(db, worker_id)
                if job is None:
                    self._wake.wait(worker_settings.poll_seconds)
                    self._wake.clear()
                    continue
                self._process(job.id, worker_id)
            except Exception:
                log.exception("worker loop error")
                time.sleep(worker_settings.poll_seconds)

    def _process(self, job_id: int, worker_id: str) -> None:
        with SessionLocal() as db:
            job = db.get(models.Job, job_id)
            if job is None:
                return
            store = storage.get_storage()
            last_beat = {"t": 0.0}

            def progress(stage: str, done: int, total: int) -> None:
                now = time.time()
                if now - last_beat["t"] < 1.0 and done < total:
                    return  # do not hammer the database on tight loops
                last_beat["t"] = now
                with SessionLocal() as hb:
                    queue.heartbeat(hb, job_id, stage, done, total)

            # -- fetch bytes -------------------------------------------------------------
            progress("reading", 0, 1)
            incoming_path = None
            try:
                if job.source == "storage":
                    data = store.get(job.stored_path)
                    key = job.stored_path
                else:
                    incoming_path = queue.INCOMING_DIR / job.stored_path
                    if not incoming_path.exists():
                        queue.fail(db, job, "The stored file is missing from disk.", permanent=True)
                        return
                    data = incoming_path.read_bytes()
                    key = storage.new_key(job.file_name.split("/")[-1])
            except storage.StorageError as exc:
                queue.fail(db, job, f"The uploaded object is missing from storage: {exc}", permanent=True)
                return

            if not job.sha256:
                job.sha256 = hashlib.sha256(data).hexdigest()
                job.file_size = job.file_size or len(data)
                db.commit()

            # Same bytes filed before? Point at that record instead of creating a twin.
            dup = queue.find_duplicate(db, job.sha256, job.id)
            if dup:
                job.status = "skipped"
                job.duplicate_of = dup
                job.record_id = dup
                job.stage = "duplicate"
                job.finished_at = datetime.utcnow()
                queue._rollup(db, job.batch_id)
                db.commit()
                if job.source == "storage":
                    store.delete(job.stored_path)  # the twin object is not needed
                elif incoming_path:
                    incoming_path.unlink(missing_ok=True)
                return

            # -- extract and file -----------------------------------------------------------
            try:
                rec = ingest.build_record(
                    data, job.file_name.split("/")[-1], job.content_type, job.mode, progress=progress, stored_name=key
                )
                if incoming_path is not None:
                    store.move_in(incoming_path, key)  # incoming/ -> permanent store (disk or bucket)
                ingest.save(db, rec)
                db.add(
                    models.AuditEvent(
                        record_id=rec.id,
                        action="upload",
                        detail=f"{job.file_name} via {ingest.engine_label(rec.extraction_method)} (batch #{job.batch_id}, {store.backend})",
                        actor=job.batch.actor,
                        client_ip=None,
                    )
                )
                queue.complete(db, job, rec.id)
                log.info("job %d filed as record %d by %s", job.id, rec.id, worker_id)
            except ingest.IngestError as exc:
                db.rollback()
                job = db.get(models.Job, job_id)
                queue.fail(db, job, str(exc), permanent=exc.permanent)
                if exc.permanent and job.source == "storage":
                    store.delete(job.stored_path)
            except Exception as exc:  # network blips, rate limits, transient IO
                db.rollback()
                job = db.get(models.Job, job_id)
                log.exception("job %d attempt %d failed", job_id, job.attempts)
                queue.fail(db, job, f"{type(exc).__name__}: {exc}")


pool = WorkerPool()
