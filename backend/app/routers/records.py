from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, models, schemas
from ..config import settings
from ..database import get_db
from ..services import ingest, parser, pipeline, storage

router = APIRouter(prefix="/api", tags=["records"])

MAX_BYTES = settings.max_upload_bytes


def _summary(rec: models.Record) -> schemas.RecordSummary:
    skip = {"raw_text", "engine_notes"}
    data = {c.name: getattr(rec, c.name) for c in models.Record.__table__.columns if c.name not in skip}
    data["subject_count"] = len(rec.subjects)
    return schemas.RecordSummary(**data)


def _detail(rec: models.Record) -> schemas.RecordDetail:
    data = _summary(rec).model_dump()
    data["raw_text"] = rec.raw_text
    try:
        data["engine_notes"] = json.loads(rec.engine_notes) if rec.engine_notes else []
    except json.JSONDecodeError:
        data["engine_notes"] = [rec.engine_notes]
    data["subjects"] = [schemas.SubjectOut.model_validate(s) for s in rec.subjects]
    return schemas.RecordDetail(**data)


def _load(db: Session, record_id: int) -> models.Record:
    rec = db.scalar(
        select(models.Record).options(selectinload(models.Record.subjects)).where(models.Record.id == record_id)
    )
    if not rec:
        raise HTTPException(404, "Record not found")
    return rec


def _recompute(rec: models.Record) -> None:
    with_marks = [s for s in rec.subjects if s.marks_obtained is not None]
    if with_marks:
        rec.total_marks = round(sum(s.marks_obtained or 0 for s in with_marks), 2)
        if all(s.max_marks for s in with_marks):
            rec.max_marks = round(sum(s.max_marks or 0 for s in with_marks), 2)
            rec.percentage = round(rec.total_marks / rec.max_marks * 100, 2) if rec.max_marks else None
    graded = [s for s in rec.subjects if s.credits and parser.grade_points_for(s.grade) is not None]
    if graded and rec.grade_scale == "4.0":
        cred = sum(s.credits or 0 for s in graded)
        pts = 0.0
        for s in graded:
            gp = parser.grade_points_for(s.grade) or 0.0
            s.grade_points = s.grade_points if s.grade_points is not None else round(gp * (s.credits or 0), 2)
            pts += s.grade_points
        if cred:
            rec.gpa = round(pts / cred, 2)
        rec.credits_earned = round(sum(s.credits or 0 for s in rec.subjects if s.credits and (s.grade or "").upper() not in {"F", "W", "NP", "U", "I", "IP"}), 1)


@router.get("/engines")
def engines():
    return pipeline.engine_status()


@router.post("/records/upload", response_model=schemas.RecordDetail, status_code=201)
async def upload_record(
    request: Request,
    file: UploadFile,
    mode: str = Query("auto", pattern="^(auto|text|google_docai|llm_vision|ocr)$"),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Files must be 25 MB or smaller.")
    filename = file.filename or "upload"
    try:
        rec = ingest.build_record(data, filename, file.content_type, mode)
    except ingest.IngestError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except Exception as exc:  # corrupt file, encrypted PDF, etc.
        raise HTTPException(422, f"Could not read {filename}: {exc}") from exc
    ingest.save(db, rec)
    audit.log(db, request, "upload", rec.id, f"{filename} via {ingest.engine_label(rec.extraction_method)}")
    db.commit()
    db.refresh(rec)
    return _detail(rec)


@router.get("/records", response_model=schemas.RecordPage)
def list_records(
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    status: str | None = Query(None, pattern="^(verified|needs_review)$"),
    engine: str | None = Query(None, pattern="^(text|google_docai|llm_vision|ocr)$"),
    sort: str = Query("created_at"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    stmt = select(models.Record).options(selectinload(models.Record.subjects))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                models.Record.student_name.ilike(like),
                models.Record.roll_number.ilike(like),
                models.Record.institution.ilike(like),
                models.Record.program.ilike(like),
                models.Record.file_name.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(models.Record.review_status == status)
    if engine:
        stmt = stmt.where(models.Record.extraction_method == engine)

    sortable = {
        "created_at": models.Record.created_at,
        "student_name": models.Record.student_name,
        "institution": models.Record.institution,
        "percentage": models.Record.percentage,
        "gpa": models.Record.gpa,
        "confidence": models.Record.confidence,
        "academic_year": models.Record.academic_year,
    }
    col = sortable.get(sort, models.Record.created_at)
    stmt = stmt.order_by(col.asc().nulls_last() if order == "asc" else col.desc().nulls_last())

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return schemas.RecordPage(items=[_summary(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/records/stats", response_model=schemas.Stats)
def stats(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(models.Record.id))) or 0
    verified = db.scalar(select(func.count(models.Record.id)).where(models.Record.review_status == "verified")) or 0
    avg = db.scalar(select(func.avg(models.Record.percentage)).where(models.Record.percentage.is_not(None)))
    avg_gpa = db.scalar(
        select(func.avg(models.Record.gpa)).where(models.Record.gpa.is_not(None), models.Record.grade_scale == "4.0")
    )
    institutions = (
        db.scalar(select(func.count(func.distinct(models.Record.institution))).where(models.Record.institution.is_not(None)))
        or 0
    )
    by_engine = {
        k: v
        for k, v in db.execute(
            select(models.Record.extraction_method, func.count(models.Record.id)).group_by(models.Record.extraction_method)
        ).all()
    }
    recent = db.scalars(
        select(models.Record)
        .options(selectinload(models.Record.subjects))
        .order_by(models.Record.created_at.desc())
        .limit(5)
    ).all()
    return schemas.Stats(
        total_records=total,
        verified=verified,
        needs_review=total - verified,
        average_percentage=round(avg, 2) if avg is not None else None,
        average_gpa=round(avg_gpa, 2) if avg_gpa is not None else None,
        institutions=institutions,
        by_engine=by_engine,
        recent=[_summary(r) for r in recent],
    )


@router.get("/records/export.csv")
def export_csv(request: Request, db: Session = Depends(get_db)):
    """US-style register report: one row per course, for reporting or spreadsheet work."""
    rows = db.scalars(
        select(models.Record).options(selectinload(models.Record.subjects)).order_by(models.Record.created_at.desc())
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Record ID", "Student Name", "Student ID", "Institution", "Program", "Term", "Academic Year",
            "Result", "Grade Scale", "Cumulative GPA", "Credits Earned", "Percentage", "Review Status",
            "Processing Engine", "Uploaded (UTC)",
            "Course Code", "Course Title", "Grade", "Credits", "Grade Points", "Marks", "Max Marks",
        ]
    )
    for r in rows:
        base = [
            r.id, r.student_name or "", r.roll_number or "", r.institution or "", r.program or "", r.term or "",
            r.academic_year or "", r.result_status or "", r.grade_scale or "", r.gpa if r.gpa is not None else "",
            r.credits_earned if r.credits_earned is not None else "", r.percentage if r.percentage is not None else "",
            r.review_status, pipeline.ENGINES.get(r.extraction_method, r.extraction_method),
            r.created_at.strftime("%m/%d/%Y %H:%M"),
        ]
        if not r.subjects:
            w.writerow(base + [""] * 7)
        for s in r.subjects:
            w.writerow(
                base
                + [
                    s.code or "", s.name, s.grade or "", s.credits if s.credits is not None else "",
                    s.grade_points if s.grade_points is not None else "",
                    s.marks_obtained if s.marks_obtained is not None else "", s.max_marks if s.max_marks is not None else "",
                ]
            )
    audit.log(db, request, "export", None, f"{len(rows)} records exported to CSV")
    db.commit()
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="academic-records.csv"'},
    )


@router.get("/records/{record_id}", response_model=schemas.RecordDetail)
def get_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    rec = _load(db, record_id)
    audit.log(db, request, "view", rec.id)
    db.commit()
    return _detail(rec)


@router.patch("/records/{record_id}", response_model=schemas.RecordDetail)
def update_record(record_id: int, payload: schemas.RecordUpdate, request: Request, db: Session = Depends(get_db)):
    rec = _load(db, record_id)
    changes = payload.model_dump(exclude_unset=True)
    subjects = changes.pop("subjects", None)
    changed = [k for k, v in changes.items() if getattr(rec, k) != v]
    for key, value in changes.items():
        setattr(rec, key, value)
    if subjects is not None:
        rec.subjects.clear()
        for i, s in enumerate(subjects):
            rec.subjects.append(models.Subject(position=i, **s))
        changed.append(f"subjects({len(subjects)})")
        _recompute(rec)
    action = "status_change" if changed == ["review_status"] else "edit"
    audit.log(db, request, action, rec.id, ", ".join(changed) or "no changes")
    db.commit()
    db.refresh(rec)
    return _detail(rec)


class BulkDeleteRequest(BaseModel):
    ids: list[int]


class BulkDeleteResponse(BaseModel):
    deleted: int
    missing: list[int]


@router.post("/records/bulk-delete", response_model=BulkDeleteResponse)
def bulk_delete(body: BulkDeleteRequest, request: Request, db: Session = Depends(get_db)):
    """Delete several records and their stored files in one request. Each deletion is written to the audit log."""
    ids = sorted({i for i in body.ids if i > 0})
    if not ids:
        raise HTTPException(400, "No record ids were given.")
    if len(ids) > 500:
        raise HTTPException(413, "Delete at most 500 records per request.")
    rows = db.scalars(select(models.Record).options(selectinload(models.Record.subjects)).where(models.Record.id.in_(ids))).all()
    found = {r.id for r in rows}
    store = storage.get_storage()
    for rec in rows:
        try:
            store.delete(rec.stored_path)
        except Exception:
            pass
        audit.log(db, request, "delete", rec.id, f"{rec.file_name} ({rec.student_name or 'unnamed'}) via bulk delete")
        db.delete(rec)
    db.commit()
    return BulkDeleteResponse(deleted=len(rows), missing=[i for i in ids if i not in found])


@router.delete("/records/{record_id}", status_code=204)
def delete_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    rec = _load(db, record_id)
    try:
        storage.get_storage().delete(rec.stored_path)
    except storage.StorageError:
        pass
    audit.log(db, request, "delete", rec.id, f"{rec.file_name} ({rec.student_name or 'unnamed'})")
    db.delete(rec)
    db.commit()


@router.get("/records/{record_id}/file")
def download_file(record_id: int, request: Request, db: Session = Depends(get_db)):
    rec = _load(db, record_id)
    store = storage.get_storage()
    if not store.exists(rec.stored_path):
        raise HTTPException(404, "The original file is no longer in storage.")
    audit.log(db, request, "download", rec.id, rec.file_name)
    db.commit()
    if store.backend == "local":
        return FileResponse(store.local_path(rec.stored_path), filename=rec.file_name)
    try:
        signed = store.presign_get(rec.stored_path, rec.file_name, None, inline=False)
    except Exception as exc:
        raise HTTPException(503, f"Storage is not reachable: {type(exc).__name__}") from exc
    return RedirectResponse(signed.url, status_code=307)
