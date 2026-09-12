"""Where original documents live, and how the browser reaches them without going through the API.

Two backends behind one interface:

  * S3Storage    AWS S3 or any S3-compatible store (MinIO, R2, Wasabi). The browser uploads straight to the
                 bucket with a presigned POST and previews with a presigned GET. The API never proxies bytes.
  * LocalStorage Files on this server's disk. "Presigned" URLs are HMAC-signed links to this API with an expiry,
                 so the frontend uses exactly the same flow in development and in production.

Records store the object *key* in `stored_path`. Keys look like `records/<uuid>.<ext>`.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

# Only used by the local backend (and to read files stored before a switch to S3). Created on first write.
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,240}$")


@dataclass
class PresignedPost:
    url: str
    fields: dict[str, str]
    key: str
    expires_at: int  # unix seconds
    max_bytes: int


@dataclass
class PresignedGet:
    url: str
    expires_at: int


class StorageError(Exception):
    """Storage could not do what was asked (network, credentials, permissions). Usually worth retrying."""


class StorageNotFound(StorageError):
    """The object is definitely not there. Retrying will not help."""


def new_key(filename: str, prefix: str = "records") -> str:
    ext = Path(filename).suffix.lower()[:10]
    ext = ext if re.fullmatch(r"\.[a-z0-9]+", ext or "") else ""
    return f"{prefix}/{uuid.uuid4().hex}{ext}"


def valid_key(key: str) -> bool:
    return bool(KEY_RE.match(key)) and ".." not in key and not key.startswith("/")


# --- Local -------------------------------------------------------------------------


class LocalStorage:
    backend = "local"

    def __init__(self) -> None:
        self.root = UPLOAD_DIR
        self.secret = settings.signing_secret.encode()

    def _path(self, key: str) -> Path:
        if not valid_key(key):
            raise StorageError("Invalid storage key.")
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise StorageError("Invalid storage key.")
        return p

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def move_in(self, src: Path, key: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        src.replace(p)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise StorageNotFound("Object not found.")
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).exists()
        except StorageError:
            return False

    def delete(self, key: str) -> None:
        try:
            p = self._path(key)
        except StorageError:
            return
        if p.exists():
            p.unlink()

    def local_path(self, key: str) -> Path:
        return self._path(key)

    # -- signing --------------------------------------------------------------------

    def sign(self, verb: str, key: str, exp: int, disposition: str = "") -> str:
        msg = f"{verb}|{key}|{exp}|{disposition}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()[:40]

    def verify(self, verb: str, key: str, exp: int, sig: str, disposition: str = "") -> bool:
        if exp < int(time.time()):
            return False
        return hmac.compare_digest(self.sign(verb, key, exp, disposition), sig)

    def presign_post(self, key: str, content_type: str | None, max_bytes: int) -> PresignedPost:
        exp = int(time.time()) + settings.presign_expires
        sig = self.sign("put", key, exp)
        return PresignedPost(
            url=f"{settings.public_api_base}/api/uploads/local/{key}?exp={exp}&sig={sig}",
            fields={},
            key=key,
            expires_at=exp,
            max_bytes=max_bytes,
        )

    def presign_get(self, key: str, filename: str, content_type: str | None, inline: bool) -> PresignedGet:
        from urllib.parse import quote

        exp = int(time.time()) + settings.presign_expires
        disposition = "inline" if inline else "attachment"
        sig = self.sign("get", key, exp, disposition)
        # The real filename rides along (unsigned, cosmetic) so downloads are named like the upload.
        return PresignedGet(
            url=f"{settings.public_api_base}/api/files/{key}?exp={exp}&sig={sig}&as={disposition}&name={quote(filename)}",
            expires_at=exp,
        )


# --- S3 -------------------------------------------------------------------------------


class S3Storage:
    backend = "s3"

    def __init__(self) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise StorageError("boto3 is not installed.") from exc
        if not settings.s3_bucket:
            raise StorageError("S3_BUCKET is not set.")
        self.bucket = settings.s3_bucket
        # Records filed before the switch to S3 still sit on local disk; keep them readable.
        self._legacy = LocalStorage()
        self.client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url or None,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path" if settings.s3_endpoint_url else "auto"}),
        )

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def move_in(self, src: Path, key: str) -> None:
        from .extractor import MIME

        ctype = MIME.get(src.suffix.lower())
        self.client.upload_file(str(src), self.bucket, key, ExtraArgs={"ContentType": ctype} if ctype else None)
        src.unlink(missing_ok=True)

    @staticmethod
    def _is_missing(exc: Exception) -> bool:
        """Only a definite 404/NoSuchKey means missing. Anything else (network, auth, throttling) is an outage."""
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        return code in ("404", "NoSuchKey", "NotFound")

    def _in_bucket(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            if self._is_missing(exc):
                return False
            raise StorageError(f"{type(exc).__name__}: {exc}") from exc

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            if not self._is_missing(exc):
                raise StorageError(f"{type(exc).__name__}: {exc}") from exc
            if self._legacy.exists(key):
                return self._legacy.get(key)
            raise StorageNotFound("Object not found.") from exc

    def exists(self, key: str) -> bool:
        return self._in_bucket(key) or self._legacy.exists(key)

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            pass
        self._legacy.delete(key)

    def presign_post(self, key: str, content_type: str | None, max_bytes: int) -> PresignedPost:
        fields: dict[str, str] = {}
        conditions: list = [["content-length-range", 1, max_bytes]]
        if content_type:
            fields["Content-Type"] = content_type
            conditions.append({"Content-Type": content_type})
        post = self.client.generate_presigned_post(
            Bucket=self.bucket, Key=key, Fields=fields, Conditions=conditions, ExpiresIn=settings.presign_expires
        )
        return PresignedPost(
            url=post["url"], fields=post["fields"], key=key, expires_at=int(time.time()) + settings.presign_expires, max_bytes=max_bytes
        )

    def presign_get(self, key: str, filename: str, content_type: str | None, inline: bool) -> PresignedGet:
        if not self._in_bucket(key) and self._legacy.exists(key):
            return self._legacy.presign_get(key, filename, content_type, inline)
        safe = filename.replace('"', "").replace("\r", "").replace("\n", "")[:150]
        disposition = "inline" if inline else f'attachment; filename="{safe}"'
        params = {"Bucket": self.bucket, "Key": key, "ResponseContentDisposition": disposition}
        if content_type:
            params["ResponseContentType"] = content_type
        url = self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=settings.presign_expires)
        return PresignedGet(url=url, expires_at=int(time.time()) + settings.presign_expires)


_storage: LocalStorage | S3Storage | None = None


def get_storage() -> LocalStorage | S3Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.storage_backend == "s3" else LocalStorage()
    return _storage


def sync_bucket_cors(origins: list[str]) -> None:
    """Make sure browsers can POST presigned uploads to the bucket from wherever the app is served.

    Runs at startup when STORAGE_BACKEND=s3 and S3_MANAGE_CORS is not "false". Presigned signatures are the
    access control, so the rule allows any origin ("*") and the bucket itself stays private. Other CORS rules
    on the bucket are left alone. Failures are logged, never fatal: the app still starts without it.
    """
    del origins  # the rule is origin-agnostic by design; kept in the signature for callers
    import logging
    import os

    log = logging.getLogger("registrar.storage")
    if settings.storage_backend != "s3" or os.getenv("S3_MANAGE_CORS", "true").lower() in ("0", "false", "no"):
        return
    try:
        store = get_storage()
        if not isinstance(store, S3Storage):
            return
        client = store.client
        try:
            rules = client.get_bucket_cors(Bucket=store.bucket)["CORSRules"]
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") != "NoSuchCORSConfiguration":
                raise
            rules = []
        rule = next((r for r in rules if "POST" in r.get("AllowedMethods", [])), None)
        if rule is None:
            rule = {"AllowedOrigins": [], "AllowedMethods": ["GET", "POST", "HEAD"], "AllowedHeaders": ["*"], "ExposeHeaders": ["ETag"], "MaxAgeSeconds": 3000}
            rules.append(rule)
        have = set(rule.get("AllowedOrigins", []))
        if "*" in have:
            log.info("bucket %s CORS already allows any origin", store.bucket)
            return
        missing = ["*"]
        rule["AllowedOrigins"] = ["*"]
        client.put_bucket_cors(Bucket=store.bucket, CORSConfiguration={"CORSRules": rules})
        log.info("bucket %s CORS: added %s", store.bucket, ", ".join(missing))
    except Exception as exc:
        log.warning("could not sync bucket CORS (%s). Browser uploads may be blocked until the rule is applied by hand.", exc)


def status() -> dict:
    s = get_storage()
    return {
        "backend": s.backend,
        "bucket": settings.s3_bucket if s.backend == "s3" else None,
        "presign_expires": settings.presign_expires,
        "max_bytes": settings.max_upload_bytes,
    }


