"""Google Document AI: OCR a scanned document and report how sure it was.

Mirrors Google's "send a processing request" Python sample (regional endpoint, processor path, RawDocument,
ProcessRequest, document.text). On top of that it reads per-token confidence, form fields and tables, and it
splits long PDFs into chunks so the online-processing page limit is never exceeded.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from ..config import settings

# Online (synchronous) processing accepts at most this many pages per request for OCR and Form Parser
# processors. Longer PDFs are split and the results are stitched back together.
ONLINE_PAGE_LIMIT = 15
ONLINE_BYTE_LIMIT = 20 * 1024 * 1024


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


def _client_and_name():
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai
    except ImportError as exc:
        raise DocAiError("google-cloud-documentai is not installed.") from exc

    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{settings.google_location}-documentai.googleapis.com")
    )
    if settings.google_processor_version:
        name = client.processor_version_path(
            settings.google_project, settings.google_location, settings.google_processor, settings.google_processor_version
        )
    else:
        name = client.processor_path(settings.google_project, settings.google_location, settings.google_processor)
    return client, name, documentai


def _chunks(data: bytes, mime_type: str) -> list[bytes]:
    """Split a PDF into pieces of at most ONLINE_PAGE_LIMIT pages. Images and short PDFs pass through unchanged."""
    if mime_type != "application/pdf":
        return [data]
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return [data]
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) <= ONLINE_PAGE_LIMIT:
        return [data]
    out: list[bytes] = []
    for start in range(0, len(reader.pages), ONLINE_PAGE_LIMIT):
        writer = PdfWriter()
        for page in reader.pages[start : start + ONLINE_PAGE_LIMIT]:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        out.append(buf.getvalue())
    return out


def _process_one(client, name, documentai, data: bytes, mime_type: str):
    if len(data) > ONLINE_BYTE_LIMIT:
        raise DocAiError(f"Document AI online processing accepts files up to 20 MB; this piece is {len(data) / 1e6:.1f} MB.")
    request = documentai.ProcessRequest(name=name, raw_document=documentai.RawDocument(content=data, mime_type=mime_type))
    try:
        return client.process_document(request=request).document
    except Exception as exc:
        text = str(exc)
        if "credentials" in text.lower() or "DefaultCredentialsError" in type(exc).__name__:
            raise DocAiError(
                "Document AI credentials were not found. Set GOOGLE_APPLICATION_CREDENTIALS to the service-account "
                "JSON path, or run `gcloud auth application-default login` on this machine."
            ) from exc
        raise DocAiError(f"Document AI request failed: {exc}") from exc


def process(data: bytes, mime_type: str) -> DocAiResult:
    if not settings.google_ready:
        raise DocAiError("Google Document AI is not configured.")
    client, name, documentai = _client_and_name()

    texts: list[str] = []
    confidences: list[float] = []
    form_fields: dict[str, str] = {}
    tables: list[list[list[str | None]]] = []
    page_count = 0

    for piece in _chunks(data, mime_type):
        doc = _process_one(client, name, documentai, piece, mime_type)
        text = doc.text or ""
        texts.append(text)
        page_count += len(doc.pages)
        for page in doc.pages:
            for token in page.tokens:
                if token.layout and token.layout.confidence:
                    confidences.append(float(token.layout.confidence))
            for ff in page.form_fields:
                key = _anchor_text(text, ff.field_name.text_anchor)
                val = _anchor_text(text, ff.field_value.text_anchor)
                if key and key.rstrip(":").strip() not in form_fields:
                    form_fields[key.rstrip(":").strip()] = val
            for table in page.tables:
                rows: list[list[str | None]] = []
                for row in list(table.header_rows) + list(table.body_rows):
                    rows.append([_anchor_text(text, cell.layout.text_anchor) for cell in row.cells])
                if len(rows) > 1:
                    tables.append(rows)

    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return DocAiResult(
        text="\n\n".join(t for t in texts if t).strip(),
        confidence=round(confidence, 3),
        page_count=page_count,
        form_fields=form_fields,
        tables=tables,
    )
