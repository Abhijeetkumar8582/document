"""Google Document AI: OCR a scanned document and report how sure it was."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings


@dataclass
class DocAiResult:
    text: str
    confidence: float  # mean token confidence, 0..1
    page_count: int
    form_fields: dict[str, str] = field(default_factory=dict)
    tables: list[list[list[str | None]]] = field(default_factory=list)


class DocAiError(Exception):
    pass


def _anchor_text(full: str, anchor) -> str:
    if not anchor or not anchor.text_segments:
        return ""
    return "".join(full[int(seg.start_index) : int(seg.end_index)] for seg in anchor.text_segments).strip()


def process(data: bytes, mime_type: str) -> DocAiResult:
    if not settings.google_ready:
        raise DocAiError("Google Document AI is not configured.")
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai
    except ImportError as exc:
        raise DocAiError("google-cloud-documentai is not installed.") from exc

    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{settings.google_location}-documentai.googleapis.com")
    )
    name = client.processor_path(settings.google_project, settings.google_location, settings.google_processor)
    request = documentai.ProcessRequest(
        name=name, raw_document=documentai.RawDocument(content=data, mime_type=mime_type)
    )
    try:
        doc = client.process_document(request=request).document
    except Exception as exc:
        raise DocAiError(f"Document AI request failed: {exc}") from exc

    text = doc.text or ""
    confidences: list[float] = []
    form_fields: dict[str, str] = {}
    tables: list[list[list[str | None]]] = []
    for page in doc.pages:
        for token in page.tokens:
            if token.layout and token.layout.confidence:
                confidences.append(float(token.layout.confidence))
        for ff in page.form_fields:
            key = _anchor_text(text, ff.field_name.text_anchor)
            val = _anchor_text(text, ff.field_value.text_anchor)
            if key:
                form_fields[key.rstrip(":").strip()] = val
        for table in page.tables:
            rows: list[list[str | None]] = []
            for row in list(table.header_rows) + list(table.body_rows):
                rows.append([_anchor_text(text, cell.layout.text_anchor) for cell in row.cells])
            if len(rows) > 1:
                tables.append(rows)

    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return DocAiResult(
        text=text, confidence=round(confidence, 3), page_count=len(doc.pages), form_fields=form_fields, tables=tables
    )
