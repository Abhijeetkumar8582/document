from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(50))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    stored_path: Mapped[str] = mapped_column(String(500))
    # Content hash of the original file; duplicate detection keys on this, never on job rows.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)

    # Which engine read the file and how sure it was.
    extraction_method: Mapped[str] = mapped_column(String(50), default="text")
    engine_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    engine_notes: Mapped[str] = mapped_column(Text, default="")

    student_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roll_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    term: Mapped[str | None] = mapped_column(String(100), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(50), nullable=True)
    result_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    total_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    credits_earned: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade_scale: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    review_status: Mapped[str] = mapped_column(String(30), default="needs_review")
    pii_redacted: Mapped[bool] = mapped_column(Boolean, default=False)

    raw_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    subjects: Mapped[list["Subject"]] = relationship(
        back_populates="record", cascade="all, delete-orphan", order_by="Subject.position"
    )


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    marks_obtained: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    credits: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    record: Mapped[Record] = relationship(back_populates="subjects")


class AuditEvent(Base):
    """FERPA-style access log: who did what to which education record, and when."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="anonymous")
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Batch(Base):
    """One bulk upload. Finished only when every job has reached a terminal state."""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    mode: Mapped[str] = mapped_column(String(20), default="auto")
    actor: Mapped[str] = mapped_column(String(120), default="anonymous")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|completed|attention|cancelled
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    jobs: Mapped[list["Job"]] = relationship(back_populates="batch", cascade="all, delete-orphan", order_by="Job.id")


class Job(Base):
    """One file inside a batch. The file is on disk before this row exists, so a crash cannot lose it."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(String(500))
    # "incoming": bytes in uploads/incoming/, moved to permanent storage when filed.
    # "storage":  already in permanent storage under stored_path (direct presigned upload).
    source: Mapped[str] = mapped_column(String(20), default="incoming")
    mode: Mapped[str] = mapped_column(String(20), default="auto")

    # queued -> processing -> done | failed(retry pending) -> dead ; or skipped / cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(60), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    batch: Mapped[Batch] = relationship(back_populates="jobs")
