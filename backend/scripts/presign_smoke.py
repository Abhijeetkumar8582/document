"""Exercise presign -> direct POST -> from-upload -> preview against a running backend on :8000.

All sample bytes are built in memory; nothing is written to local disk.
"""
import sys

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from samples import marksheet_pdf  # noqa: E402

BASE = "http://127.0.0.1:8000"


def main() -> int:
    print("storage:", requests.get(f"{BASE}/api/storage", timeout=10).json())
    pdf = marksheet_pdf()
    name = "marksheet_priya_sharma.pdf"

    r = requests.post(f"{BASE}/api/uploads/presign", json={"file_name": name, "content_type": "application/pdf", "size": len(pdf)}, timeout=10)
    r.raise_for_status()
    p = r.json()
    print("presigned POST:", p["backend"], p["key"], p["url"][:60] + "...")

    url = p["url"] if p["url"].startswith("http") else BASE + p["url"]
    r = requests.post(url, data=p["fields"], files={"file": (name, pdf, "application/pdf")}, timeout=60)
    print("direct POST ->", r.status_code)
    r.raise_for_status()

    if p["backend"] == "local":
        bad = requests.post(url.replace("sig=", "sig=0"), files={"file": ("x.pdf", b"x", "application/pdf")}, timeout=10)
        print("tampered signature ->", bad.status_code)

    r = requests.post(f"{BASE}/api/records/from-upload", json={"key": p["key"], "file_name": name, "content_type": "application/pdf", "mode": "auto"}, timeout=120)
    r.raise_for_status()
    rec = r.json()
    print("record:", rec["id"], rec["student_name"], rec["extraction_method"], "stored as", p["key"])

    r = requests.get(f"{BASE}/api/records/{rec['id']}/preview", timeout=10)
    r.raise_for_status()
    pv = r.json()
    print("presigned GET:", pv["kind"], pv["content_type"], pv["url"].split("?")[0][:80] + "?...")
    purl = pv["url"] if pv["url"].startswith("http") else BASE + pv["url"]
    g = requests.get(purl, timeout=30)
    print("fetch preview ->", g.status_code, g.headers.get("content-type"), g.headers.get("content-disposition"), len(g.content), "bytes")
    ok = g.status_code == 200 and g.content[:4] == b"%PDF"

    if pv["backend"] == "local":
        bad = requests.get(purl.replace("sig=", "sig=0"), timeout=10)
        print("tampered preview link ->", bad.status_code)
        ok = ok and bad.status_code == 403

    requests.delete(f"{BASE}/api/records/{rec['id']}", timeout=10)
    gone = requests.get(f"{BASE}/api/records/{rec['id']}/preview", timeout=10).status_code
    print("after delete, preview ->", gone)
    print("OK" if ok and gone == 404 else "FAILED")
    return 0 if ok and gone == 404 else 1


if __name__ == "__main__":
    sys.exit(main())
