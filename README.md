# Registrar

Upload academic records (transcripts, marksheets, grade reports) and turn them into structured, searchable, audited
records. Every upload has its text read by the best available engine, its student details and course rows parsed, and
is filed in a register you can search, sort, review, correct, report on, and export the original from.

```
backend/    FastAPI + SQLAlchemy + SQLite. pdfplumber, Google Document AI, Local LLM Cloud, optional Tesseract.
frontend/   React 19 + TypeScript + Vite + Tailwind
```

## Run it

Backend (port 8000):

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Background workers start with the API. On Windows avoid `--reload`: uvicorn's reloader spawns child processes that
keep the port after a restart. Restart the process by hand instead.

Frontend (port 5173, proxies `/api` to the backend):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs.

No sample files are kept in the repo and the server writes nothing to local disk. The smoke tests under
`backend/scripts/` build their sample documents in memory (`samples.py`) and push them through the real API.

## How a file is read

Each upload is routed through the engines in this order, and the record carries a tag saying which one read it, plus a
step-by-step note of what was tried.

| Step | Engine | When it is used | Tag |
| --- | --- | --- | --- |
| 1 | **Text layer** (pdfplumber, pypdf) | The PDF has embedded text. Free and exact. DOCX and TXT always land here. | Text layer |
| 2 | **Google Document AI** | The file is a scan or image and Document AI is configured. The result is kept only if its mean token confidence is at least `DOCAI_MIN_CONFIDENCE` (default 70%). Form fields and tables are used when the processor returns them. | Google Document AI · 85% |
| 3 | **Local LLM Cloud** (`gemini-2.5-flash`) | Document AI is missing, failed, or came in under the threshold. Each page is rendered to an image and sent in its own call with a strict JSON schema; pages are merged. | Local LLM Cloud · gemini-2.5-flash |
| 4 | **Local OCR** (Tesseract) | Neither cloud engine is configured but Tesseract is installed. | Local OCR |

If none of steps 2 to 4 is available, a scan is rejected with a message listing what was tried.
On the Upload page you can also force a specific engine instead of Auto.

### Configuring the engines

Copy `backend/.env.example` to `backend/.env`:

```
GOOGLE_DOCAI_PROJECT_ID=my-project
GOOGLE_DOCAI_LOCATION=us
GOOGLE_DOCAI_PROCESSOR_ID=abc123
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
DOCAI_MIN_CONFIDENCE=0.70

GEMINI_API_KEY=AIza...            # from https://aistudio.google.com/apikey
GEMINI_VISION_MODEL=gemini-2.5-flash
```

`GET /api/engines` reports which engines are ready; the Upload page reads it to grey out unavailable options.

## What gets extracted

Student name, student ID / roll number, institution, program, term, academic year, standing or result, cumulative
GPA, credits earned, grade scale, total and max marks, percentage, and one row per course (code, title, credits,
grade, grade points, marks, max marks).

US transcripts are handled natively: letter grades with plus/minus on the 4.0 scale, credit hours, quality points,
Fall/Spring/Summer terms, and "Student ID". When a transcript does not print a GPA, one is computed from credits and
grade points, with pass/fail, withdrawn and incomplete grades excluded from the denominator. Marks-based sheets
(percentage scale) are still supported and shown with their own columns.

Extraction is heuristic: each record carries a field-confidence score and is stamped **Verified** (75% and above) or
**Needs review**. Every field and course row can be edited in the UI, and the status can be flipped by hand.

## Bulk upload

The Upload page takes a single file, a folder, a ZIP, or any number of files; anything beyond one file becomes a batch and returns immediately with a batch id. Every
file is written to disk and recorded as a job **before** the request is acknowledged, then background workers file
them one by one. Close the browser, restart the server, lose a cloud engine for an hour: the batch resumes and
finishes with every file in a terminal state, either filed or listed with a reason.

- Per-file states: waiting, processing (with page-level progress), retrying with backoff, filed, duplicate, needs
  attention, cancelled. A batch is "Completed" only when nothing is left to run; "Needs attention" when some files gave up.
- Identical files are filed once: twins inside a batch are skipped at intake, twins of earlier uploads point at the
  existing record.
- Unreadable files (unsupported type, scan with no scan engine) fail permanently on the first try. Transient errors
  (rate limits, network) retry up to `JOB_MAX_ATTEMPTS` with exponential backoff, then park for a one-click retry.
- Workers hold a lease and heartbeat while working; a janitor requeues anything whose worker went silent, and the
  same sweep runs at startup.
- `WORKER_CONCURRENCY` sets how many files run in parallel. Keep it at 1 or 2 when batches are scan-heavy so the
  vision model stays inside its rate limit.

Capacity, measured with `python scripts/load_test.py 1000` (text transcripts, local storage, one laptop):
1,000 files uploaded in 4 s, the batch created in 1 s, and all 1,000 filed in 21 s with two workers while the API
stayed responsive. Scanned pages are bound by the cloud engines instead: roughly 3 to 5 s per page for Document AI
and 5 to 10 s for Gemini, so a thousand scans take one to three hours at `WORKER_CONCURRENCY=2`. Raise it for
scan-heavy batches as far as your Document AI and Gemini quotas allow. ZIPs are unpacked one member at a time, so
memory stays flat regardless of archive size; the per-archive cap is `MAX_ZIP_ENTRIES` (2,000).

The full design, including the state machine, failure table and how to scale workers onto separate machines, is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). `python scripts/bulk_smoke.py` exercises the queue end to end against
a running backend.

## Document storage and presigned URLs

Originals live in either local disk (default) or an S3-compatible bucket, chosen by `STORAGE_BACKEND`. The browser
never streams file bytes through the API in either mode:

1. `POST /api/uploads/presign` with `{file_name, content_type, size}` returns a **presigned POST**: a `url`, form
   `fields`, and the object `key`.
2. The browser POSTs the file to that URL (fields first, `file` last). With S3 this goes straight to the bucket; with
   local storage it goes to a signed endpoint on this API.
3. `POST /api/records/from-upload` with the `key` reads the object from storage, extracts it, and files the record.
4. `GET /api/records/{id}/preview` returns a **presigned GET** the record page embeds inline: PDFs in the browser's
   viewer, images as `<img>`. Links expire after `PRESIGN_EXPIRES` seconds (default 15 minutes) and the page renews
   them before they lapse. Each preview request is written to the audit log.

For S3:

```bash
STORAGE_BACKEND=s3
S3_BUCKET=registrar-documents
S3_REGION=us-east-1
# S3_ENDPOINT_URL=http://localhost:9000    # MinIO
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

The bucket needs a CORS rule allowing `POST` and `GET` from the frontend origin, and the IAM identity needs
`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, and `s3:ListBucket` on it. Keep the bucket private; presigned
URLs are the only way the browser reaches objects. `python scripts/presign_smoke.py` runs the full chain against a
running backend, including tampered-signature checks.

## FERPA handling

- **PII redaction.** Social Security numbers and dates of birth are removed from the extracted text before anything is
  stored. Records where this happened carry a "PII redacted" badge. The vision prompt also instructs the model never
  to output them.
- **Audit log.** Every upload, view, edit, status change, download, export and deletion is written to `audit_events`
  with actor, IP and timestamp, and shown on the Audit log page. Set the `X-User` header from your SSO or reverse
  proxy to record real identities; until then the actor is `anonymous`.
- **Right to inspect and correct.** Each record has an "Access history" link, an editor, and a download of the original.
- **Deletion** removes the stored file and the record in one step, and is itself logged.
- **US formatting.** Dates are MM/DD/YYYY, numbers use en-US formatting, and the CSV export uses US column names.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/engines` | which engines are configured, threshold, model |
| POST | `/api/uploads/presign` | `{file_name, content_type, size}` → presigned POST url, fields, key |
| POST | `/api/records/from-upload` | `{key, file_name, content_type, mode}` → files the uploaded object as a record |
| GET | `/api/records/{id}/preview` | presigned GET for an inline document preview |
| GET | `/api/storage` | which backend is active and the presign lifetime |
| POST | `/api/records/upload?mode=auto` | single-request upload through the API (scripts); `mode` is auto, text, google_docai, llm_vision or ocr |
| GET | `/api/records` | `q`, `status`, `engine`, `sort`, `order`, `page`, `page_size` |
| GET | `/api/records/stats` | counts, average GPA (4.0-scale only), average score, records per engine |
| GET | `/api/dashboard?days=30` | everything the dashboard draws: intake per day, review split, engine mix, GPA buckets, top institutions, queue, recent activity |
| GET | `/api/records/export.csv` | one row per course, US column names |
| GET | `/api/records/{id}` | full record with courses, raw text and processing notes |
| PATCH | `/api/records/{id}` | edit fields, courses, GPA, scale, or review status |
| DELETE | `/api/records/{id}` | remove record and stored file |
| GET | `/api/records/{id}/file` | download the original upload |
| GET | `/api/audit` | `record_id`, `action`, `page`, `page_size` |
| POST | `/api/batches?mode=&name=` | multipart `files[]`, ZIPs and folders ok; returns 202 with the batch |
| GET | `/api/batches`, `/api/batches/{id}`, `/api/batches/{id}/jobs` | batch list, batch with counts, per-file rows |
| GET | `/api/batches/summary` | queue depth, processing, dead count, workers |
| POST | `/api/batches/{id}/retry`, `/api/batches/{id}/cancel`, `/api/jobs/{id}/retry` | requeue dead jobs, cancel waiting jobs, requeue one job |

## Deploying

One host runs everything: uvicorn serves the API and the built frontend on port 8000, so the browser uses a single
origin and needs no API address or CORS setup. Step-by-step instructions for the EC2 host, the systemd unit, and the
setup and update scripts are in [deploy/DEPLOY.md](deploy/DEPLOY.md). `backend/.env` is never committed; create it
on the server.

## Production notes

- Set `allow_origins` in `backend/app/main.py` to the real frontend origin and put the API behind authentication.
- `npm run build` in `frontend/` emits static files in `frontend/dist/`; serve them on the same host as the API.
- Swap `DATABASE_URL` in `backend/app/database.py` for Postgres when you outgrow SQLite. Startup migration adds any
  new columns automatically.
- Document AI online processing handles up to 15 pages per request; split larger scans or switch to batch processing.
- The vision fallback sends page images to Google's Gemini API. Check your data-processing agreement covers
  education records before enabling it. Keys used through AI Studio's free tier may be used to improve Google's
  models; a paid Google Cloud project key is not.
