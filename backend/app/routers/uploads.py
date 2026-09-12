"""Direct-to-storage uploads and document previews.

    1. POST /api/uploads/presign            -> presigned POST (url + fields) and a key
    2. browser POSTs the file to that url    (S3 directly, or this API's local endpoint)
    3. POST /api/records/from-upload         -> server reads the object by key, extracts, files the record
    4. GET  /api/records/{id}/preview        -> presigned GET for an inline preview
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit, models, schemas
from ..config import settings
from ..database import get_db
from ..services import extractor, ingest, queue, storage
from .records import _detail

router = APIRouter(prefix="/api", tags=["uploads"])

PREVIEWABLE = {"pdf": "application/pdf"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}


class PresignRequest(BaseModel):
    file_name: str
    content_type: str | None = None
    size: int | None = None


class PresignResponse(BaseModel):
    key: str
    method: str = "POST"
    url: str
    fields: dict[str, str]
    expires_at: int
    max_bytes: int
    backend: str


class FromUploadRequest(BaseModel):
    key: str
    file_name: str
    content_type: str | None = None
    mode: str = "auto"


class PreviewResponse(BaseModel):
    url: str
    expires_at: int
    content_type: str | None
    kind: str  # pdf | image | other
    file_name: str
    backend: str


def _storage_problem(store, exc: Exception) -> str:
    name = type(exc).__name__
    # botocore raises NoCredentialsError on signed calls, but presigned POST trips over the missing
    # credentials object first and surfaces as AttributeError: 'NoneType' ... 'access_key'.
    if store.backend == "s3" and (name in ("NoCredentialsError", "PartialCredentialsError") or "access_key" in str(exc)):
        return "S3 storage is selected but no AWS credentials are configured. Add AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to backend/.env and restart."
    return f"Storage ({store.backend}) is not reachable: {name}: {exc}"


def _content_type_for(file_name: str, declared: str | None) -> str | None:
    ext = Path(file_name).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in IMAGE_MIME:
        return IMAGE_MIME[ext]
    return declared


@router.get("/storage")
def storage_status():
    return storage.status()


@router.post("/uploads/presign", response_model=PresignResponse)
def presign_upload(body: PresignRequest, request: Request):
    try:
        extractor.detect_kind(body.file_name, body.content_type)
    except extractor.UnsupportedFile as exc:
        raise HTTPException(415, str(exc)) from exc
    if body.size and body.size > settings.max_upload_bytes:
        raise HTTPException(413, f"Files must be {settings.max_upload_bytes // (1024 * 1024)} MB or smaller.")
    store = storage.get_storage()
    key = storage.new_key(body.file_name)
    try:
        post = store.presign_post(key, _content_type_for(body.file_name, body.content_type), settings.max_upload_bytes)
    except Exception as exc:
        raise HTTPException(503, _storage_problem(store, exc)) from exc
    return PresignResponse(
        key=post.key, url=post.url, fields=post.fields, expires_at=post.expires_at, max_bytes=post.max_bytes, backend=store.backend
    )


@router.post("/uploads/local/{key:path}", status_code=204)
def local_upload_target(key: str, file: UploadFile, exp: int = Query(...), sig: str = Query(...)):
    """The POST target a local presign hands out. Not used when STORAGE_BACKEND=s3."""
    store = storage.get_storage()
    if store.backend != "local":
        raise HTTPException(404, "Local uploads are disabled; the bucket accepts uploads directly.")
    if not storage.valid_key(key) or not store.verify("put", key, exp, sig):
        raise HTTPException(403, "This upload link is invalid or has expired. Ask for a new one.")
    if store.exists(key):
        raise HTTPException(409, "This upload link has already been used. Ask for a new one.")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"Files must be {settings.max_upload_bytes // (1024 * 1024)} MB or smaller.")
    store.put(key, data, file.content_type)


@router.post("/records/from-upload", response_model=schemas.RecordDetail, status_code=201)
def record_from_upload(body: FromUploadRequest, request: Request, db: Session = Depends(get_db)):
    """Turn an object already in storage into a record. The file is never re-uploaded through the API."""
    if not storage.valid_key(body.key) or not body.key.startswith("records/"):
        raise HTTPException(400, "Invalid storage key.")
    if queue.key_in_use(db, body.key):
        raise HTTPException(409, "That upload has already been filed. Upload the file again to create a new record.")
    store = storage.get_storage()
    try:
        data = store.get(body.key)
    except storage.StorageNotFound as exc:
        raise HTTPException(404, f"Nothing was uploaded for that key yet: {exc}") from exc
    except storage.StorageError as exc:
        raise HTTPException(503, _storage_problem(store, exc)) from exc
    if len(data) > settings.max_upload_bytes:
        store.delete(body.key)
        raise HTTPException(413, "The uploaded object is larger than the allowed size and was removed.")
    mode = body.mode if body.mode in ("auto", "text", "google_docai", "llm_vision", "ocr") else "auto"
    try:
        rec = ingest.build_record(data, body.file_name, body.content_type, mode, stored_name=body.key)
    except ingest.IngestError as exc:
        store.delete(body.key)
        raise HTTPException(exc.status, str(exc)) from exc
    except Exception as exc:
        store.delete(body.key)
        raise HTTPException(422, f"Could not read {body.file_name}: {exc}") from exc
    ingest.save(db, rec)
    audit.log(db, request, "upload", rec.id, f"{body.file_name} via {ingest.engine_label(rec.extraction_method)} (direct to {store.backend})")
    db.commit()
    db.refresh(rec)
    return _detail(rec)


@router.get("/records/{record_id}/preview", response_model=PreviewResponse)
def preview_url(record_id: int, request: Request, db: Session = Depends(get_db)):
    """A short-lived link the browser can embed to show the original document."""
    rec = db.scalar(select(models.Record).options(selectinload(models.Record.subjects)).where(models.Record.id == record_id))
    if not rec:
        raise HTTPException(404, "Record not found")
    store = storage.get_storage()
    try:
        present = store.exists(rec.stored_path)
    except Exception as exc:
        raise HTTPException(503, _storage_problem(store, exc)) from exc
    if not present:
        raise HTTPException(404, "The original file is no longer in storage.")
    ext = Path(rec.file_name).suffix.lower()
    if rec.file_type == "pdf":
        kind, ctype = "pdf", "application/pdf"
    elif rec.file_type == "image":
        kind, ctype = "image", IMAGE_MIME.get(ext, "image/png")
    else:
        kind, ctype = "other", None
    try:
        signed = store.presign_get(rec.stored_path, rec.file_name, ctype, inline=True)
    except Exception as exc:
        raise HTTPException(503, _storage_problem(store, exc)) from exc
    audit.log(db, request, "preview", rec.id, rec.file_name)
    db.commit()
    return PreviewResponse(url=signed.url, expires_at=signed.expires_at, content_type=ctype, kind=kind, file_name=rec.file_name, backend=store.backend)


@router.get("/files/{key:path}")
def serve_local_file(key: str, exp: int = Query(...), sig: str = Query(...), as_: str = Query("inline", alias="as"), name: str = Query("")):
    """Serves a locally stored object from a signed link. Not used when STORAGE_BACKEND=s3."""
    store = storage.get_storage()
    local = store if store.backend == "local" else store._legacy  # S3 mode still serves pre-switch files from disk
    disposition = "inline" if as_ == "inline" else "attachment"
    if not storage.valid_key(key) or not local.verify("get", key, exp, sig, disposition):
        raise HTTPException(403, "This link is invalid or has expired. Reload the record to get a new one.")
    path = local.local_path(key)
    if not path.exists():
        raise HTTPException(404, "File not found.")
    ext = path.suffix.lower()
    media = "application/pdf" if ext == ".pdf" else IMAGE_MIME.get(ext, "application/octet-stream")
    shown = (name or path.name).replace('"', "").replace("\r", "").replace("\n", "")[:150] or path.name
    headers = {"Content-Disposition": f'{disposition}; filename="{shown}"', "Cache-Control": f"private, max-age={max(0, exp - int(time.time()))}"}
    return FileResponse(path, media_type=media, headers=headers)
