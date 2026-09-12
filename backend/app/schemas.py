from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    code: str | None
    name: str
    marks_obtained: float | None
    max_marks: float | None
    grade: str | None
    credits: float | None
    grade_points: float | None


class SubjectIn(BaseModel):
    code: str | None = None
    name: str
    marks_obtained: float | None = None
    max_marks: float | None = None
    grade: str | None = None
    credits: float | None = None
    grade_points: float | None = None


class RecordSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    file_type: str
    file_size: int
    page_count: int
    extraction_method: str
    engine_confidence: float | None
    engine_model: str | None
    student_name: str | None
    roll_number: str | None
    institution: str | None
    program: str | None
    term: str | None
    academic_year: str | None
    result_status: str | None
    total_marks: float | None
    max_marks: float | None
    percentage: float | None
    gpa: float | None
    credits_earned: float | None
    grade_scale: str | None
    confidence: float
    review_status: str
    pii_redacted: bool
    subject_count: int
    created_at: datetime


class RecordDetail(RecordSummary):
    engine_notes: list[str]
    raw_text: str
    subjects: list[SubjectOut]


class RecordUpdate(BaseModel):
    student_name: str | None = None
    roll_number: str | None = None
    institution: str | None = None
    program: str | None = None
    term: str | None = None
    academic_year: str | None = None
    result_status: str | None = None
    gpa: float | None = None
    credits_earned: float | None = None
    grade_scale: Literal["4.0", "percentage", "other"] | None = None
    review_status: Literal["verified", "needs_review"] | None = None
    subjects: list[SubjectIn] | None = None


class RecordPage(BaseModel):
    items: list[RecordSummary]
    total: int
    page: int
    page_size: int


class Stats(BaseModel):
    total_records: int
    verified: int
    needs_review: int
    average_percentage: float | None
    average_gpa: float | None
    institutions: int
    by_engine: dict[str, int]
    recent: list[RecordSummary]


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    record_id: int | None
    action: str
    detail: str
    actor: str
    client_ip: str | None
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    total: int
    page: int
    page_size: int


# --- Bulk upload -----------------------------------------------------------------


class JobCounts(BaseModel):
    queued: int = 0
    processing: int = 0
    failed: int = 0
    done: int = 0
    skipped: int = 0
    dead: int = 0
    cancelled: int = 0


class BatchOut(BaseModel):
    id: int
    name: str
    mode: str
    actor: str
    status: str
    total_jobs: int
    total_bytes: int
    counts: JobCounts
    finished_jobs: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BatchPage(BaseModel):
    items: list[BatchOut]
    total: int
    page: int
    page_size: int


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    file_name: str
    file_size: int
    sha256: str
    source: str
    mode: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None
    worker_id: str | None
    progress_done: int
    progress_total: int
    stage: str
    error: str | None
    record_id: int | None
    duplicate_of: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class QueueSummary(BaseModel):
    queued: int
    processing: int
    dead: int
    running_batches: int
    workers: int
