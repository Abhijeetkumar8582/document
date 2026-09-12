"""Push N documents through the real intake path and time it.

    .venv/Scripts/python scripts/load_test.py 1000

Each file is uploaded exactly the way the browser does it (presign -> direct POST to storage), then one batch is
created from the keys and polled until every job is terminal. Records are deleted at the end so the register is
left as it was. Uses generated text transcripts, so no OCR or LLM calls are made.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "http://127.0.0.1:8000"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
THREADS = 8


def transcript(i: int) -> bytes:
    return (
        f"Riverbend State University\nOFFICIAL TRANSCRIPT\nStudent Name: Student {i:04d}\nStudent ID: RSU-{100000 + i}\n"
        f"Degree Program: B.S. Data Science\nTerm: Fall 2025\n\nCourse                     Credits  Grade  Points\n"
        f"DS 101  Intro to Data Science  3.0  A   12.0\nMTH 201  Linear Algebra      3.0  B+  9.9\n"
        f"CS 150  Programming I         4.0  A-  14.8\nCumulative GPA: {3.2 + (i % 8) / 10:.2f}\nCredits Earned: 10.0\n"
    ).encode()


def upload_one(i: int) -> dict | None:
    name = f"student_{i:04d}.txt"
    data = transcript(i)
    for attempt in range(3):
        try:
            p = requests.post(f"{BASE}/api/uploads/presign", json={"file_name": name, "content_type": "text/plain", "size": len(data)}, timeout=30).json()
            url = p["url"] if p["url"].startswith("http") else BASE + p["url"]
            r = requests.post(url, data=p["fields"], files={"file": (name, data, "text/plain")}, timeout=60)
            if r.status_code in (200, 201, 204):
                return {"key": p["key"], "file_name": name, "content_type": "text/plain", "size": len(data)}
        except Exception:
            pass
        time.sleep(0.5 * (attempt + 1))
    return None


def main() -> int:
    print(f"storage: {requests.get(f'{BASE}/api/storage', timeout=10).json()['backend']}, files: {N}, upload threads: {THREADS}")
    t0 = time.time()
    with ThreadPoolExecutor(THREADS) as pool:
        items = [it for it in pool.map(upload_one, range(N)) if it]
    t_up = time.time() - t0
    print(f"uploaded {len(items)}/{N} in {t_up:.1f}s ({len(items) / t_up:.1f} files/s)")

    t1 = time.time()
    b = requests.post(f"{BASE}/api/batches/from-keys", json={"items": items, "mode": "text", "name": f"load test {N}"}, timeout=300).json()
    print(f"batch #{b['id']} created in {time.time() - t1:.1f}s with {b['total_jobs']} jobs")

    t2 = time.time()
    last = None
    while True:
        b = requests.get(f"{BASE}/api/batches/{b['id']}", timeout=30).json()
        c = b["counts"]
        line = f"  {b['status']:<10} done={c['done']} skipped={c['skipped']} dead={c['dead']} processing={c['processing']} waiting={c['queued'] + c['failed']}"
        if line != last:
            print(line)
            last = line
        if b["status"] not in ("running", "queued"):
            break
        time.sleep(3)
    t_proc = time.time() - t2
    filed = b["counts"]["done"]
    print(f"processed {b['total_jobs']} jobs in {t_proc:.1f}s ({b['total_jobs'] / max(t_proc, 0.1):.1f} files/s with {requests.get(f'{BASE}/api/batches/summary', timeout=10).json()['workers']} workers)")

    # API responsiveness under load was the point of the async fix; sample it now that the queue is idle.
    t3 = time.time()
    requests.get(f"{BASE}/api/records?page_size=10", timeout=30)
    print(f"records page: {(time.time() - t3) * 1000:.0f} ms")

    # Clean up everything this run created.
    ids = []
    page = 1
    while True:
        r = requests.get(f"{BASE}/api/records", params={"q": "Riverbend State University", "page": page, "page_size": 200}, timeout=60).json()
        ids += [x["id"] for x in r["items"]]
        if len(ids) >= r["total"] or not r["items"]:
            break
        page += 1
    for i in range(0, len(ids), 500):
        requests.post(f"{BASE}/api/records/bulk-delete", json={"ids": ids[i : i + 500]}, timeout=300)
    print(f"cleaned up {len(ids)} records")
    print("RESULT:", "OK" if filed == len(items) and b["status"] == "completed" else f"CHECK ({b['status']}, filed {filed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
