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
    pass


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
            raise StorageError("Object not found.")
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
        exp = int(time.time()) + settings.presign_expires
        disposition = "inline" if inline else "attachment"
        sig = self.sign("get", key, exp, disposition)
        return PresignedGet(
            url=f"{settings.public_api_base}/api/files/{key}?exp={exp}&sig={sig}&as={disposition}",
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
        self.client.upload_file(str(src), self.bucket, key)
        src.unlink(missing_ok=True)

    def _in_bucket(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            if self._legacy.exists(key):
                return self._legacy.get(key)
            raise StorageError("Object not found.") from exc

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
        disposition = "inline" if inline else f'attachment; filename="{filename}"'
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


def status() -> dict:
    s = get_storage()
    return {
        "backend": s.backend,
        "bucket": settings.s3_bucket if s.backend == "s3" else None,
        "presign_expires": settings.presign_expires,
        "max_bytes": settings.max_upload_bytes,
    }


