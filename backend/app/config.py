"""Runtime settings, read from environment variables (and backend/.env if present)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


class Settings:
    # Google Document AI (used for scanned pages when configured)
    google_project: str | None = os.getenv("GOOGLE_DOCAI_PROJECT_ID")
    google_location: str = os.getenv("GOOGLE_DOCAI_LOCATION", "us")
    google_processor: str | None = os.getenv("GOOGLE_DOCAI_PROCESSOR_ID")
    # Optional: pin a specific processor version (e.g. "pretrained-ocr-v2.0-2023-06-02"); blank uses the default.
    google_processor_version: str | None = os.getenv("GOOGLE_DOCAI_PROCESSOR_VERSION") or None
    google_credentials: str | None = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    # Accept a Document AI result only when its mean token confidence reaches this.
    docai_min_confidence: float = _float("DOCAI_MIN_CONFIDENCE", 0.70)

    # Vision fallback: Gemini, one call per page
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")

    # A page whose text layer is shorter than this is treated as a scan.
    min_text_chars_per_page: int = int(os.getenv("MIN_TEXT_CHARS_PER_PAGE", "80"))
    render_dpi: int = int(os.getenv("RENDER_DPI", "170"))

    # Document storage: "local" (this server's disk) or "s3" (AWS S3 / MinIO / any S3-compatible store).
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local").lower()
    s3_bucket: str | None = os.getenv("S3_BUCKET")
    s3_region: str = os.getenv("S3_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    s3_endpoint_url: str | None = os.getenv("S3_ENDPOINT_URL")  # MinIO etc.; leave blank for AWS
    presign_expires: int = int(os.getenv("PRESIGN_EXPIRES", "900"))  # seconds a presigned URL stays valid
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    # Where the browser can reach this API, for local signed URLs. The Vite proxy makes "" correct in dev.
    public_api_base: str = os.getenv("PUBLIC_API_BASE", "").rstrip("/")
    signing_secret: str = os.getenv("SIGNING_SECRET", "")

    @property
    def google_ready(self) -> bool:
        return bool(self.google_project and self.google_processor)

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)


settings = Settings()

def _ensure_signing_secret() -> str:
    """A stable secret for local signed URLs. Generated once and kept next to the database."""
    import secrets

    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True, mode=0o700)
    p = data_dir / ".signing_secret"
    if p.exists():
        return p.read_text().strip()
    secret = secrets.token_hex(32)
    # Owner-only: anyone who can read this can mint valid document links.
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(secret)
    return secret


if not settings.signing_secret:
    settings.signing_secret = _ensure_signing_secret()


# --- Background workers (bulk upload) ------------------------------------------
class WorkerSettings:
    concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "2"))
    max_attempts: int = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
    lease_seconds: int = int(os.getenv("JOB_LEASE_SECONDS", "300"))
    poll_seconds: float = _float("WORKER_POLL_SECONDS", 1.0)
    backoff_base_seconds: int = int(os.getenv("JOB_BACKOFF_SECONDS", "15"))
    max_zip_entries: int = int(os.getenv("MAX_ZIP_ENTRIES", "2000"))
    max_batch_bytes: int = int(os.getenv("MAX_BATCH_BYTES", str(2 * 1024 * 1024 * 1024)))


worker_settings = WorkerSettings()
