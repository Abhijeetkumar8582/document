"""Write one audit row per access to an education record."""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from . import models


def actor_of(request: Request) -> str:
    # Wire this to your SSO / reverse proxy. Until then the header is the identity.
    return (request.headers.get("x-user") or request.headers.get("x-forwarded-user") or "anonymous")[:120]


def log(db: Session, request: Request, action: str, record_id: int | None = None, detail: str = "") -> None:
    db.add(
        models.AuditEvent(
            record_id=record_id,
            action=action,
            detail=detail[:2000],
            actor=actor_of(request),
            client_ip=(request.client.host if request.client else None),
        )
    )
