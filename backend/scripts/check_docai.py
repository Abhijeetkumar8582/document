"""Prove Google Document AI is configured: one real process() call on a small generated page.

Run:  .venv/Scripts/python scripts/check_docai.py
Reads backend/.env (GOOGLE_DOCAI_PROJECT_ID, GOOGLE_DOCAI_LOCATION, GOOGLE_DOCAI_PROCESSOR_ID and either
GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account JSON, or gcloud application-default credentials).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402
from app.services import google_docai  # noqa: E402
from samples import scan_pdf  # noqa: E402


def ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def main() -> int:
    print(f"project={settings.google_project!r} location={settings.google_location!r} processor={settings.google_processor!r}")
    if not settings.google_ready:
        fail("GOOGLE_DOCAI_PROJECT_ID or GOOGLE_DOCAI_PROCESSOR_ID is empty in backend/.env")
        return 1
    cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred:
        if Path(cred).is_file():
            ok(f"service-account key file found at {cred}")
        else:
            fail(f"GOOGLE_APPLICATION_CREDENTIALS points at {cred} but that file does not exist")
            return 1
    else:
        print("  [info] GOOGLE_APPLICATION_CREDENTIALS not set; relying on gcloud application-default credentials")

    try:
        res = google_docai.process(scan_pdf(), "application/pdf")
    except google_docai.DocAiError as exc:
        fail(str(exc))
        return 1
    ok(f"processor answered: {res.page_count} page(s), {len(res.text)} chars, mean confidence {round(res.confidence * 100)}%")
    ok(f"threshold is {round(settings.docai_min_confidence * 100)}%: result would be {'accepted' if res.confidence >= settings.docai_min_confidence else 'discarded in favour of Gemini'}")
    if res.form_fields:
        ok(f"form fields detected: {list(res.form_fields)[:5]}")
    if res.tables:
        ok(f"tables detected: {len(res.tables)}")
    print("\nAll good. Restart the backend; GET /api/engines will report google_docai ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
