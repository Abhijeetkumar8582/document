from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=schemas.AuditPage)
def list_events(
    db: Session = Depends(get_db),
    record_id: int | None = Query(None),
    action: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = select(models.AuditEvent)
    if record_id is not None:
        stmt = stmt.where(models.AuditEvent.record_id == record_id)
    if action:
        stmt = stmt.where(models.AuditEvent.action == action)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(models.AuditEvent.created_at.desc(), models.AuditEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return schemas.AuditPage(items=rows, total=total, page=page, page_size=page_size)
