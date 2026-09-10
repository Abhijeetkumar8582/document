"""One call for everything the dashboard draws."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import worker_settings
from ..database import get_db
from ..services import pipeline

router = APIRouter(prefix="/api", tags=["dashboard"])


class DayPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class NamedCount(BaseModel):
    key: str
    label: str
    count: int


class Bucket(BaseModel):
    label: str
    lo: float
    hi: float
    count: int


class DashboardOut(BaseModel):
    total_records: int
    verified: int
    needs_review: int
    added_last_7: int
    added_prev_7: int
    average_gpa: float | None
    average_percentage: float | None
    average_confidence: float | None
    institutions: int
    pii_redacted: int
    by_day: list[DayPoint]
    by_engine: list[NamedCount]
    by_status: list[NamedCount]
    by_scale: list[NamedCount]
    gpa_buckets: list[Bucket]
    top_institutions: list[NamedCount]
    queue: schemas.QueueSummary
    recent_activity: list[schemas.AuditEventOut]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), days: int = Query(30, ge=7, le=180)):
    now = datetime.utcnow()
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    R = models.Record

    total = db.scalar(select(func.count(R.id))) or 0
    verified = db.scalar(select(func.count(R.id)).where(R.review_status == "verified")) or 0
    added_last_7 = db.scalar(select(func.count(R.id)).where(R.created_at >= now - timedelta(days=7))) or 0
    added_prev_7 = (
        db.scalar(select(func.count(R.id)).where(R.created_at >= now - timedelta(days=14), R.created_at < now - timedelta(days=7))) or 0
    )
    avg_gpa = db.scalar(select(func.avg(R.gpa)).where(R.gpa.is_not(None), R.grade_scale == "4.0"))
    avg_pct = db.scalar(select(func.avg(R.percentage)).where(R.percentage.is_not(None)))
    avg_conf = db.scalar(select(func.avg(R.confidence)))
    institutions = db.scalar(select(func.count(func.distinct(R.institution))).where(R.institution.is_not(None))) or 0
    pii = db.scalar(select(func.count(R.id)).where(R.pii_redacted.is_(True))) or 0

    # Records per day, zero-filled so the bars line up with the calendar.
    rows = db.execute(
        select(func.date(R.created_at), func.count(R.id)).where(R.created_at >= since).group_by(func.date(R.created_at))
    ).all()
    counts = {str(d): n for d, n in rows}
    by_day = [DayPoint(date=(since + timedelta(days=i)).strftime("%Y-%m-%d"), count=counts.get((since + timedelta(days=i)).strftime("%Y-%m-%d"), 0)) for i in range(days)]

    engine_rows = dict(db.execute(select(R.extraction_method, func.count(R.id)).group_by(R.extraction_method)).all())
    by_engine = [NamedCount(key=k, label=v, count=engine_rows.get(k, 0)) for k, v in pipeline.ENGINES.items()]

    by_status = [
        NamedCount(key="verified", label="Verified", count=verified),
        NamedCount(key="needs_review", label="Needs review", count=total - verified),
    ]
    scale_rows = dict(db.execute(select(R.grade_scale, func.count(R.id)).group_by(R.grade_scale)).all())
    by_scale = [
        NamedCount(key="4.0", label="4.0 scale", count=scale_rows.get("4.0", 0)),
        NamedCount(key="percentage", label="Marks based", count=scale_rows.get("percentage", 0)),
        NamedCount(key="other", label="Other / unknown", count=sum(n for k, n in scale_rows.items() if k not in ("4.0", "percentage"))),
    ]

    edges = [0.0, 2.0, 2.5, 3.0, 3.5, 4.01]
    labels = ["< 2.0", "2.0–2.49", "2.5–2.99", "3.0–3.49", "3.5–4.0"]
    gpas = db.scalars(select(R.gpa).where(R.gpa.is_not(None), R.grade_scale == "4.0")).all()
    buckets = []
    for i, label in enumerate(labels):
        lo, hi = edges[i], edges[i + 1]
        buckets.append(Bucket(label=label, lo=lo, hi=min(hi, 4.0), count=sum(1 for g in gpas if lo <= g < hi)))

    inst_rows = db.execute(
        select(R.institution, func.count(R.id)).where(R.institution.is_not(None)).group_by(R.institution).order_by(func.count(R.id).desc()).limit(6)
    ).all()
    top_institutions = [NamedCount(key=name, label=name, count=n) for name, n in inst_rows]

    job_rows = dict(db.execute(select(models.Job.status, func.count()).group_by(models.Job.status)).all())
    running = db.scalar(select(func.count()).select_from(models.Batch).where(models.Batch.status == "running")) or 0
    queue = schemas.QueueSummary(
        queued=job_rows.get("queued", 0) + job_rows.get("failed", 0),
        processing=job_rows.get("processing", 0),
        dead=job_rows.get("dead", 0),
        running_batches=running,
        workers=max(1, worker_settings.concurrency),
    )
    recent = db.scalars(select(models.AuditEvent).order_by(models.AuditEvent.created_at.desc()).limit(8)).all()

    return DashboardOut(
        total_records=total,
        verified=verified,
        needs_review=total - verified,
        added_last_7=added_last_7,
        added_prev_7=added_prev_7,
        average_gpa=round(avg_gpa, 2) if avg_gpa is not None else None,
        average_percentage=round(avg_pct, 2) if avg_pct is not None else None,
        average_confidence=round(avg_conf, 3) if avg_conf is not None else None,
        institutions=institutions,
        pii_redacted=pii,
        by_day=by_day,
        by_engine=by_engine,
        by_status=by_status,
        by_scale=by_scale,
        gpa_buckets=buckets,
        top_institutions=top_institutions,
        queue=queue,
        recent_activity=[schemas.AuditEventOut.model_validate(e) for e in recent],
    )
