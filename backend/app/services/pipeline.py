"""Decide how to read an upload and do it.

    text layer present  -> "text"          (free, exact)
    scan + Google ready -> "google_docai"  (kept only at >= DOCAI_MIN_CONFIDENCE)
    otherwise           -> "llm_vision"    (Gemini, one call per page)
    nothing configured  -> "ocr"           (local Tesseract, if installed)

Every step taken is written to `notes` so the UI can show why an engine was chosen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

from ..config import settings
from . import extractor, google_docai, llm_vision

ENGINES = {
    "text": "Text layer",
    "google_docai": "Google Document AI",
    "llm_vision": "Local LLM Cloud",
    "ocr": "Local OCR",
}
MODES = ("auto", "text", "google_docai", "llm_vision", "ocr")


@dataclass
class Processed:
    extraction: extractor.Extraction
    engine: str
    engine_confidence: float | None
    notes: list[str] = field(default_factory=list)
    model: str | None = None


class ProcessingError(Exception):
    """`permanent=True` means retrying the same bytes on the same server cannot succeed."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


def engine_status() -> dict:
    return {
        "google_docai": {
            "label": ENGINES["google_docai"],
            "ready": settings.google_ready,
            "threshold": settings.docai_min_confidence,
        },
        "llm_vision": {"label": ENGINES["llm_vision"], "ready": settings.gemini_ready, "model": settings.gemini_model},
        "ocr": {"label": ENGINES["ocr"], "ready": extractor.tesseract_available()},
        "text": {"label": ENGINES["text"], "ready": True},
    }


Progress = Callable[[str, int, int], None]  # (stage, done, total)


def process(
    data: bytes, filename: str, content_type: str | None, mode: str = "auto", progress: Progress | None = None
) -> Processed:
    def tick(stage: str, done: int, total: int) -> None:
        if progress:
            progress(stage, done, total)

    kind = extractor.detect_kind(filename, content_type)
    if mode not in MODES:
        mode = "auto"
    notes: list[str] = []

    if kind == "docx":
        return Processed(extractor.docx_text(data), "text", None, ["Word document: read paragraphs and tables directly."])
    if kind == "text":
        return Processed(extractor.plain_text(data), "text", None, ["Plain text file: read as-is."])

    # 1. Text layer
    layer: extractor.Extraction | None = None
    if kind == "pdf":
        tick("text layer", 0, 1)
        layer = extractor.pdf_text_layer(data)
        chars = len(layer.text)
        if mode == "text" or (mode == "auto" and extractor.has_text_layer(layer)):
            notes.append(f"Text layer: {chars:,} characters across {layer.page_count} page(s). Used directly.")
            return Processed(layer, "text", None, notes)
        if mode == "auto":
            notes.append(f"Text layer: only {chars:,} characters on {layer.page_count} page(s). Treated as a scan.")
    else:
        notes.append("Image upload. No text layer to read.")

    # 2. Google Document AI
    if mode in ("auto", "google_docai"):
        if settings.google_ready:
            try:
                tick("google document ai", 0, 1)
                res = google_docai.process(data, extractor.mime_for(filename, kind))
                pct = round(res.confidence * 100)
                if res.confidence >= settings.docai_min_confidence or mode == "google_docai":
                    notes.append(
                        f"Google Document AI: {pct}% mean confidence on {res.page_count} page(s), "
                        f"threshold {round(settings.docai_min_confidence * 100)}%. Accepted."
                    )
                    ex = extractor.Extraction(
                        text=res.text,
                        page_count=res.page_count,
                        method="google_docai",
                        tables=res.tables,
                        form_fields=res.form_fields,
                    )
                    return Processed(ex, "google_docai", res.confidence, notes)
                notes.append(
                    f"Google Document AI: {pct}% mean confidence, below the "
                    f"{round(settings.docai_min_confidence * 100)}% threshold. Discarded."
                )
            except google_docai.DocAiError as exc:
                notes.append(f"Google Document AI: {exc}")
                if mode == "google_docai":
                    raise ProcessingError(str(exc)) from exc
        else:
            notes.append("Google Document AI: not configured, skipped.")
            if mode == "google_docai":
                raise ProcessingError("Google Document AI is not configured on this server.", permanent=True)

    # 3. Vision LLM, page by page
    if mode in ("auto", "llm_vision"):
        if settings.gemini_ready:
            try:
                tick("rendering pages", 0, 1)
                images = extractor.render_pages(data, kind)
                tick("llm vision", 0, len(images))
                res = llm_vision.read_pages(images, on_page=lambda i, n: tick("gemini vision", i, n))
                notes.append(
                    f"Local LLM Cloud ({res.model}): read {len(res.pages)} page(s), "
                    f"{len(res.subjects)} subject row(s) returned."
                )
                ex = extractor.Extraction(
                    text=res.text,
                    page_count=len(res.pages),
                    method="llm_vision",
                    structured=res.fields,
                    structured_subjects=res.subjects,
                )
                return Processed(ex, "llm_vision", None, notes, model=res.model)
            except llm_vision.VisionError as exc:
                notes.append(f"Local LLM Cloud: {exc}")
                if mode == "llm_vision":
                    raise ProcessingError(str(exc)) from exc
        else:
            notes.append("Local LLM Cloud: GEMINI_API_KEY not set, skipped.")
            if mode == "llm_vision":
                raise ProcessingError("Gemini is not configured: set GEMINI_API_KEY on the server.", permanent=True)

    # 4. Local OCR
    if extractor.tesseract_available():
        tick("local ocr", 0, 1)
        images = extractor.render_pages(data, kind)
        text = extractor.ocr_images(images)
        notes.append(f"Local OCR (Tesseract): {len(text):,} characters from {len(images)} page(s).")
        return Processed(extractor.Extraction(text=text, page_count=len(images), method="ocr"), "ocr", None, notes)
    notes.append("Local OCR: Tesseract not installed.")

    if layer and layer.text.strip():
        notes.append("Fell back to the thin text layer.")
        return Processed(layer, "text", None, notes)
    raise ProcessingError(
        "This looks like a scanned document and no scan engine is available. "
        "Set GEMINI_API_KEY, configure Google Document AI, or install Tesseract. Steps tried: " + " ".join(notes),
        permanent=True,
    )
