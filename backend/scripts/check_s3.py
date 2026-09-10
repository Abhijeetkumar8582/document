"""Prove the S3 configuration in backend/.env works before pointing the app at it.

Checks, in order: credentials resolve, bucket is reachable, region matches, CORS allows the frontend origin,
and a full presigned POST -> presigned GET -> delete round trip succeeds on a throwaway object.
Run:  .venv/Scripts/python scripts/check_s3.py
"""
from __future__ import annotations

import sys
import time

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

FRONTEND_ORIGIN = "http://localhost:5173"


def ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def main() -> int:
    print(f"backend={settings.storage_backend} bucket={settings.s3_bucket!r} region={settings.s3_region} endpoint={settings.s3_endpoint_url or 'AWS'}")
    if settings.storage_backend != "s3":
        fail("STORAGE_BACKEND is not 's3' in backend/.env")
        return 1
    if not settings.s3_bucket:
        fail("S3_BUCKET is empty")
        return 1

    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    try:
        ident = boto3.client("sts", region_name=settings.s3_region).get_caller_identity()
        ok(f"credentials resolve to {ident['Arn']}")
    except NoCredentialsError:
        fail("no AWS credentials found (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in backend/.env)")
        return 1
    except ClientError as exc:
        if settings.s3_endpoint_url:
            ok(f"STS not available on custom endpoint, skipping identity check ({exc.response['Error']['Code']})")
        else:
            fail(f"credentials rejected: {exc}")
            return 1

    from app.services import storage

    try:
        store = storage.S3Storage()
    except storage.StorageError as exc:
        fail(str(exc))
        return 1
    client = store.client

    try:
        loc = client.get_bucket_location(Bucket=settings.s3_bucket).get("LocationConstraint") or "us-east-1"
        if loc != settings.s3_region and not settings.s3_endpoint_url:
            fail(f"bucket is in {loc} but S3_REGION is {settings.s3_region}; presigned URLs will fail. Set S3_REGION={loc}")
            return 1
        ok(f"bucket reachable in {loc}")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        fail(f"cannot access bucket ({code}). Check the name, and that the IAM policy allows s3:ListBucket and s3:GetBucketLocation")
        return 1

    try:
        rules = client.get_bucket_cors(Bucket=settings.s3_bucket)["CORSRules"]
        allowed = any(
            ("*" in r.get("AllowedOrigins", []) or FRONTEND_ORIGIN in r.get("AllowedOrigins", []))
            and "POST" in r.get("AllowedMethods", [])
            for r in rules
        )
        if allowed:
            ok(f"CORS allows POST from {FRONTEND_ORIGIN}")
        else:
            fail(f"CORS does not allow POST from {FRONTEND_ORIGIN}. Apply deploy/s3-cors.json (add your production origin too)")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "NoSuchCORSConfiguration":
            fail("bucket has no CORS rules; browser uploads will be blocked. Apply deploy/s3-cors.json")
        else:
            print(f"  [warn] could not read CORS ({code}); add s3:GetBucketCors to the policy or check it in the console")

    key = f"records/_healthcheck_{int(time.time())}.txt"
    payload = b"registrar s3 healthcheck"
    try:
        post = store.presign_post(key, "text/plain", 1024)
        r = requests.post(post.url, data=post.fields, files={"file": ("h.txt", payload, "text/plain")}, timeout=60)
        if r.status_code not in (200, 201, 204):
            fail(f"presigned POST rejected ({r.status_code}): {r.text[:200]}")
            return 1
        ok("presigned POST accepted")
        get = store.presign_get(key, "h.txt", "text/plain", inline=True)
        g = requests.get(get.url, timeout=30)
        if g.status_code == 200 and g.content == payload:
            ok("presigned GET returned the object")
        else:
            fail(f"presigned GET failed ({g.status_code})")
            return 1
        store.delete(key)
        ok("delete cleaned up the object")
    except ClientError as exc:
        fail(f"round trip failed: {exc}")
        return 1
    finally:
        try:
            store.delete(key)
        except Exception:
            pass

    print("\nAll good. Restart the backend and check GET /api/storage reports backend=s3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
