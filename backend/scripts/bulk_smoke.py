"""End-to-end check of the bulk upload queue against a running backend on :8000.

Builds a ZIP in memory with two marksheets, a duplicate, an unreadable scan and junk, plus two loose files.
Nothing is written to local disk by this script or by the server: every file lands in permanent storage.
"""
import io
import sys
import time
import zipfile

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from samples import marksheet_pdf, scan_pdf, us_transcript_txt  # noqa: E402

BASE = "http://127.0.0.1:8000/api"


def main() -> int:
    priya = marksheet_pdf()
    arjun = marksheet_pdf(name="Arjun Mehta", roll="4157823", institution="Central Board of Secondary Education", program="Class X", semester="Annual Examination", session="2024")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("priya.pdf", priya)
        z.writestr("arjun.pdf", arjun)
        z.writestr("arjun_copy.pdf", arjun)  # duplicate inside the batch
        z.writestr("scan.pdf", scan_pdf())  # needs a scan engine
        z.writestr("__MACOSX/._junk", b"x")
        z.writestr("notes.xyz", b"unsupported")

    files = [
        ("files", ("bulk.zip", buf.getvalue(), "application/zip")),
        ("files", ("transcript_jordan_reyes.txt", us_transcript_txt(), "text/plain")),
        ("files", ("gradecard_meera_iyer.txt", us_transcript_txt("Meera Iyer", "SXC-1187"), "text/plain")),
    ]
    r = requests.post(f"{BASE}/batches", params={"mode": "auto", "name": "Fall intake"}, files=files, timeout=120)
    r.raise_for_status()
    b = r.json()
    print(f"batch #{b['id']} {b['status']} jobs={b['total_jobs']} counts={b['counts']}")
    bid = b["id"]

    for _ in range(60):
        time.sleep(1.5)
        b = requests.get(f"{BASE}/batches/{bid}", timeout=10).json()
        if b["status"] not in ("running", "queued"):
            break
    print(f"  final {b['status']:<10} {b['finished_jobs']}/{b['total_jobs']} {b['counts']}")

    jobs = requests.get(f"{BASE}/batches/{bid}/jobs", timeout=10).json()["items"]
    print("jobs:")
    for j in jobs:
        print(
            f"  #{j['id']:<3} {j['status']:<10} src={j['source']:<8} tries={j['attempts']}/{j['max_attempts']} rec={j['record_id']} "
            f"dup={j['duplicate_of']} {j['file_name']:<26} stage={j['stage']!r} err={(j['error'] or '')[:50]!r}"
        )
    print("summary:", requests.get(f"{BASE}/batches/summary", timeout=10).json())
    statuses = {j["status"] for j in jobs}
    ok = statuses <= {"done", "skipped", "dead", "cancelled"} and b["status"] not in ("running", "queued")
    print("TERMINAL:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
