"""Turn bytes into a filed Record. Shared by the single-upload endpoint and the bulk workers."""
from __future__ import annotations

import json
from typing import Callable

from sqlalchemy.orm import Session

from .. import models
from . import extractor, parser, pipeline, storage

UPLOAD_DIR = storage.UPLOAD_DIR

Progress = Callable[[str, int, int], None]  # (stage, done, total)


class IngestError(Exception):
    """A problem reading this file. `permanent` says whether a retry could possibly help."""

    def __init__(self, message: str, status: int = 422, permanent: bool = False):
        super().__init__(message)
        self.status = status
        self.permanent = permanent


def build_record(
    data: bytes,
    filename: str,
    content_type: str | None,
    mode: str = "auto",
    progress: Progress | None = None,
    stored_name: str | None = None,
) -> models.Record:
    """Read, parse and assemble a Record (not yet added to a session)."""
    try:
        processed = pipeline.process(data, filename, content_type, mode, progress=progress)
    except extractor.UnsupportedFile as exc:
        raise IngestError(str(exc), 415, permanent=True) from exc
    except pipeline.ProcessingError as exc:
        raise IngestError(str(exc), 422, permanent=exc.permanent) from exc

    extraction = processed.extraction
    if not extraction.text.strip() and not extraction.structured_subjects:
        raise IngestError(
            "No text could be found in this file. Steps tried: " + " ".join(processed.notes), 422, permanent=True
        )

    if progress:
        progress("parsing", 0, 1)
    parsed = parser.parse(extraction)

    if stored_name is None:
        stored_name = storage.new_key(filename)
        storage.get_storage().put(stored_name, data, content_type)

    rec = models.Record(
        file_name=filename,
        file_type=extractor.detect_kind(filename, content_type),
        file_size=len(data),
        stored_path=stored_name,
        page_count=extraction.page_count,
        extraction_method=processed.engine,
        engine_confidence=processed.engine_confidence,
        engine_model=processed.model,
        engine_notes=json.dumps(processed.notes),
        student_name=parsed.student_name,
        roll_number=parsed.roll_number,
        institution=parsed.institution,
        program=parsed.program,
        term=parsed.term,
        academic_year=parsed.academic_year,
        result_status=parsed.result_status,
        total_marks=parsed.total_marks,
        max_marks=parsed.max_marks,
        percentage=parsed.percentage,
        gpa=parsed.gpa,
        credits_earned=parsed.credits_earned,
        grade_scale=parsed.grade_scale,
        confidence=parsed.confidence,
        review_status="verified" if parsed.confidence >= 0.75 else "needs_review",
        pii_redacted=parsed.pii_redacted,
        raw_text=extraction.text,
    )
    for i, s in enumerate(parsed.subjects):
        rec.subjects.append(
            models.Subject(
                position=i,
                code=s.code,
                name=s.name,
                marks_obtained=s.marks_obtained,
                max_marks=s.max_marks,
                grade=s.grade,
                credits=s.credits,
                grade_points=s.grade_points,
            )
        )
    if progress:
        progress("parsing", 1, 1)
    return rec


def engine_label(engine: str) -> str:
    return pipeline.ENGINES.get(engine, engine)


def save(db: Session, rec: models.Record) -> models.Record:
    db.add(rec)
    db.flush()
    return rec
