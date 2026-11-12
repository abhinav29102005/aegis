"""Tenant-scoped binary artifact storage with SHA-256 verification.

Supports filesystem-backed local storage (dev/single-node) and S3-compatible
object storage (AWS S3 / Cloudflare R2) with optional Object Lock WORM
retention, bounded-memory streaming uploads, and retention/erasure helpers.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Protocol, runtime_checkable
from uuid import UUID

DEFAULT_MAX_STREAM_BYTES = 10 * 1024 * 1024  # 10 MiB
DEFAULT_STREAM_CHUNK_SIZE = 64 * 1024  # 64 KiB
DEFAULT_WORM_RETENTION_DAYS = 2555  # 7 years

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_VALID_OBJECT_LOCK_MODES = frozenset({"COMPLIANCE", "GOVERNANCE"})
_NOT_FOUND_S3_CODES = frozenset({"NoSuchKey", "404", "NotFound"})
_LOCK_DENIED_S3_CODES = frozenset({"AccessDenied", "ObjectLocked"})


class ObjectSizeLimitExceededError(ValueError):
    """Raised when a streamed object exceeds the configured maximum byte limit."""


@dataclass(frozen=True)
class StoredObjectMetadata:
    storage_backend: str
    object_key: str
    filename: str
    content_type: str
    byte_size: int
    sha256: str
    object_lock_mode: str | None = None
    retain_until: datetime | None = None


@runtime_checkable
class ObjectStorage(Protocol):
    """Protocol implemented by all tenant-scoped object storage backends."""

    def put_bytes(
        self,
        *,
        tenant_id: UUID,
        artifact_id: UUID,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObjectMetadata: ...

    def put_stream(
        self,
        tenant_id: UUID,
        key_prefix: str,
        stream: BinaryIO | Iterable[bytes],
        *,
        max_bytes: int = DEFAULT_MAX_STREAM_BYTES,
        filename: str | None = None,
        content_type: str = "application/octet-stream",
        chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE,
    ) -> StoredObjectMetadata: ...

    def get_bytes(
        self,
        *,
        tenant_id: UUID,
        object_key: str,
        expected_sha256: str | None = None,
    ) -> bytes: ...

    def delete(self, *, tenant_id: UUID, object_key: str) -> bool: ...


def sanitize_filename(filename: str) -> str:
    """Sanitize a user-supplied filename to a safe basename without traversal."""
    base = Path(filename).name.strip() or "artifact.bin"
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    return cleaned[:180] or "artifact.bin"


def _normalize_key_prefix(key_prefix: str) -> list[str]:
    if "\x00" in key_prefix or "\\" in key_prefix:
        raise ValueError("Invalid object key path")
    stripped = key_prefix.strip("/")
    if not stripped:
        return []
    segments = stripped.split("/")
    for seg in segments:
        if seg in {"", ".", ".."}:
            raise ValueError("Invalid object key path")
    return segments


def _build_stream_object_key(
    tenant_id: UUID,
    key_prefix: str,
    filename: str | None,
) -> tuple[str, str]:
    segments = _normalize_key_prefix(key_prefix)
    if filename is not None:
        safe_name = sanitize_filename(filename)
        rel_parts = [*segments, safe_name]
    elif len(segments) >= 2:
        safe_name = sanitize_filename(segments[-1])
        rel_parts = [*segments[:-1], safe_name]
    elif len(segments) == 1:
        safe_name = "artifact.bin"
        rel_parts = [segments[0], safe_name]
    else:
        safe_name = "artifact.bin"
        rel_parts = [safe_name]
    return f"{tenant_id}/{'/'.join(rel_parts)}", safe_name


def _validate_tenant_object_key(tenant_id: UUID, object_key: str) -> str:
    expected_prefix = f"{tenant_id}/"
    if not object_key.startswith(expected_prefix):
        raise PermissionError("Cross-tenant object storage access denied")
    if "\x00" in object_key or "\\" in object_key:
        raise ValueError("Invalid object key path")
    rel = object_key[len(expected_prefix) :]
    if not rel or any(part in {"", ".", ".."} for part in rel.split("/")):
        raise ValueError("Invalid object key path")
    return object_key


def _verify_sha256(raw: bytes, object_key: str, expected_sha256: str | None) -> None:
    if expected_sha256 is not None:
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected_sha256:
            raise ValueError(
                f"Evidence artifact integrity mismatch for {object_key}: {actual} != {expected_sha256}"
            )


def iter_bounded_stream(
    stream: BinaryIO | Iterable[bytes],
    *,
    max_bytes: int = DEFAULT_MAX_STREAM_BYTES,
    chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE,
) -> Iterator[bytes]:
    """Yield chunks from a binary stream or byte-chunk iterable up to ``max_bytes``.

    Aborts immediately with ``ObjectSizeLimitExceededError`` the moment cumulative
    bytes exceed ``max_bytes``, without reading or buffering the remainder of the stream.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    total = 0
    if hasattr(stream, "read"):
        reader: BinaryIO = stream  # type: ignore[assignment]
        while True:
            remaining = max_bytes - total
            read_limit = min(chunk_size, remaining + 1)
            raw_chunk = reader.read(read_limit)
            if not raw_chunk:
                break
            if not isinstance(raw_chunk, (bytes, bytearray, memoryview)):
                raise TypeError("Stream chunks must be bytes-like objects")
            chunk = bytes(raw_chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ObjectSizeLimitExceededError(
                    f"Stream exceeded maximum allowed size of {max_bytes} bytes"
                )
            yield chunk
        return

    for raw_chunk in stream:
        if not isinstance(raw_chunk, (bytes, bytearray, memoryview)):
            raise TypeError("Stream chunks must be bytes-like objects")
        chunk = bytes(raw_chunk)
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ObjectSizeLimitExceededError(
                f"Stream exceeded maximum allowed size of {max_bytes} bytes"
            )
        yield chunk


def _stream_into_sink(
    stream: BinaryIO | Iterable[bytes],
    sink: BinaryIO,
    *,
    max_bytes: int,
    chunk_size: int,
    compute_md5: bool = False,
) -> tuple[int, str, str | None]:
    sha256_hasher = hashlib.sha256()
    md5_hasher = hashlib.md5(usedforsecurity=False) if compute_md5 else None
    total = 0
    for chunk in iter_bounded_stream(stream, max_bytes=max_bytes, chunk_size=chunk_size):
        sink.write(chunk)
        sha256_hasher.update(chunk)
        if md5_hasher is not None:
            md5_hasher.update(chunk)
        total += len(chunk)
    md5_b64 = (
        base64.b64encode(md5_hasher.digest()).decode("ascii")
        if md5_hasher is not None
        else None
    )
    return total, sha256_hasher.hexdigest(), md5_b64


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def compute_worm_retain_until(
    days: int = DEFAULT_WORM_RETENTION_DAYS,
    now: datetime | None = None,
) -> datetime:
    """Compute a UTC retention deadline for WORM ledger/evidence exports."""
    if days <= 0:
        raise ValueError("Retention days must be positive")
    base = _ensure_utc(now) if now is not None else datetime.now(UTC)
    return base + timedelta(days=days)


def is_retention_expired(
    retention_until: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Return True when no active retention lock remains as of ``now``."""
    if retention_until is None:
        return True
    current = _ensure_utc(now) if now is not None else datetime.now(UTC)
    return _ensure_utc(retention_until) <= current


def delete_if_erased(
    storage: ObjectStorage,
    *,
    tenant_id: UUID,
    object_key: str,
    erased: bool = False,
    erased_at: datetime | None = None,
    legal_hold: bool = False,
    retention_until: datetime | None = None,
    now: datetime | None = None,
) -> bool:
    """Delete an object for GDPR erasure only when legal hold and retention allow.

    Precedence:
    1. Active ``legal_hold=True`` always blocks deletion.
    2. If neither ``erased=True`` nor ``erased_at <= now``, do not delete.
    3. If ``retention_until`` has not expired yet, retain until expiry.
    4. Otherwise delete via ``storage.delete(...)`` and return whether removed.
    """
    if legal_hold:
        return False
    current = _ensure_utc(now) if now is not None else datetime.now(UTC)
    is_erased = erased or (erased_at is not None and _ensure_utc(erased_at) <= current)
    if not is_erased:
        return False
    if not is_retention_expired(retention_until, current):
        return False
    return storage.delete(tenant_id=tenant_id, object_key=object_key)


class LocalObjectStorage:
    """Filesystem-backed object store intended for single-node dev or mounted shared volumes."""

    STORAGE_BACKEND = "LOCAL_OBJECT_STORE"

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        return sanitize_filename(filename)

    def _resolve_tenant_target(self, tenant_id: UUID, object_key: str) -> Path:
        _validate_tenant_object_key(tenant_id, object_key)
        tenant_root = (self.root_dir / str(tenant_id)).resolve()
        target = (self.root_dir / object_key).resolve()
        if (
            self.root_dir not in target.parents
            or tenant_root not in target.parents
            or target == tenant_root
        ):
            raise ValueError("Invalid object key path")
        return target

    def put_bytes(
        self,
        *,
        tenant_id: UUID,
        artifact_id: UUID,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObjectMetadata:
        safe_name = self.sanitize_filename(filename)
        object_key = f"{tenant_id}/{artifact_id}/{safe_name}"
        target = self._resolve_tenant_target(tenant_id, object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return StoredObjectMetadata(
            storage_backend=self.STORAGE_BACKEND,
            object_key=object_key,
            filename=safe_name,
            content_type=content_type,
            byte_size=len(data),
            sha256=digest,
        )

    def _cleanup_empty_parents(self, tenant_id: UUID, start_dir: Path) -> None:
        tenant_root = (self.root_dir / str(tenant_id)).resolve()
        parent = start_dir
        while parent != tenant_root and self.root_dir in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def put_stream(
        self,
        tenant_id: UUID,
        key_prefix: str,
        stream: BinaryIO | Iterable[bytes],
        *,
        max_bytes: int = DEFAULT_MAX_STREAM_BYTES,
        filename: str | None = None,
        content_type: str = "application/octet-stream",
        chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE,
    ) -> StoredObjectMetadata:
        object_key, safe_name = _build_stream_object_key(tenant_id, key_prefix, filename)
        target = self._resolve_tenant_target(tenant_id, object_key)
        target.parent.mkdir(parents=True, exist_ok=True)

        tmp_path: Path | None = None
        completed = False
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=".upload_",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                total, digest, _ = _stream_into_sink(
                    stream,
                    tmp_file,
                    max_bytes=max_bytes,
                    chunk_size=chunk_size,
                    compute_md5=False,
                )
            os.replace(tmp_path, target)
            tmp_path = None
            completed = True
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            if not completed:
                self._cleanup_empty_parents(tenant_id, target.parent)

        return StoredObjectMetadata(
            storage_backend=self.STORAGE_BACKEND,
            object_key=object_key,
            filename=safe_name,
            content_type=content_type,
            byte_size=total,
            sha256=digest,
        )

    def get_bytes(
        self,
        *,
        tenant_id: UUID,
        object_key: str,
        expected_sha256: str | None = None,
    ) -> bytes:
        target = self._resolve_tenant_target(tenant_id, object_key)
        if not target.is_file():
            raise FileNotFoundError(f"Evidence artifact {object_key} not found")
        raw = target.read_bytes()
        _verify_sha256(raw, object_key, expected_sha256)
        return raw

    def delete(self, *, tenant_id: UUID, object_key: str) -> bool:
        target = self._resolve_tenant_target(tenant_id, object_key)
        if not target.is_file():
            return False
        target.unlink()
        self._cleanup_empty_parents(tenant_id, target.parent)
        return True


def _create_s3_client(
    *,
    region: str,
    endpoint_url: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
) -> Any:
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required for S3ObjectStorage when no client is injected. "
            "Install boto3 or configure AEGIS_STORAGE_BACKEND=local."
        ) from exc

    client_kwargs: dict[str, Any] = {"region_name": region}
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url
    if access_key_id and secret_access_key:
        client_kwargs["aws_access_key_id"] = access_key_id
        client_kwargs["aws_secret_access_key"] = secret_access_key
    try:
        from botocore.config import Config  # type: ignore[import-not-found]

        client_kwargs["config"] = Config(signature_version="s3v4")
    except ImportError:
        pass
    return boto3.client("s3", **client_kwargs)


def _extract_s3_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        err = response.get("Error")
        if isinstance(err, dict):
            code = err.get("Code")
            if code is not None:
                return str(code)
        meta = response.get("ResponseMetadata")
        if isinstance(meta, dict) and meta.get("HTTPStatusCode") == 404:
            return "404"
    return None


class S3ObjectStorage:
    """S3-compatible object storage supporting AWS S3, Cloudflare R2, and Object Lock WORM."""

    STORAGE_BACKEND = "S3_OBJECT_STORE"

    def __init__(
        self,
        bucket: str,
        *,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        key_prefix: str = "",
        object_lock_mode: str | None = None,
        default_retention_days: int | None = None,
        client: Any | None = None,
    ) -> None:
        clean_bucket = bucket.strip()
        if not clean_bucket:
            raise ValueError("S3 bucket must be non-empty")
        self.bucket = clean_bucket
        self.region = region.strip() or "us-east-1"
        self.endpoint_url = endpoint_url.strip() if endpoint_url else None
        self.key_prefix = "/".join(_normalize_key_prefix(key_prefix)) if key_prefix else ""
        self.object_lock_mode = self._validate_lock_mode(object_lock_mode)
        if default_retention_days is not None and default_retention_days <= 0:
            raise ValueError("default_retention_days must be positive")
        self.default_retention_days = default_retention_days
        self._client = (
            client
            if client is not None
            else _create_s3_client(
                region=self.region,
                endpoint_url=self.endpoint_url,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        )

    @staticmethod
    def _validate_lock_mode(mode: str | None) -> str | None:
        if mode is None or not mode.strip():
            return None
        normalized = mode.strip().upper()
        if normalized not in _VALID_OBJECT_LOCK_MODES:
            raise ValueError(
                f"Unsupported S3 ObjectLockMode {mode!r}; expected COMPLIANCE or GOVERNANCE"
            )
        return normalized

    def _physical_key(self, object_key: str) -> str:
        if self.key_prefix:
            return f"{self.key_prefix}/{object_key}"
        return object_key

    def _resolve_object_lock(
        self,
        object_lock_mode: str | None,
        retain_until: datetime | None,
    ) -> tuple[str | None, datetime | None]:
        mode = self._validate_lock_mode(object_lock_mode) or self.object_lock_mode
        effective_until = _ensure_utc(retain_until) if retain_until is not None else None
        if mode is not None and effective_until is None:
            if self.default_retention_days is None:
                raise ValueError(
                    "retain_until (or default_retention_days) is required when object_lock_mode is set"
                )
            effective_until = compute_worm_retain_until(self.default_retention_days)
        if effective_until is not None and mode is None:
            raise ValueError("object_lock_mode is required when retain_until is provided")
        return mode, effective_until

    def _build_put_kwargs(
        self,
        *,
        tenant_id: UUID,
        object_key: str,
        safe_name: str,
        content_type: str,
        body: bytes | BinaryIO,
        digest: str,
        byte_size: int,
        md5_b64: str | None,
        lock_mode: str | None,
        lock_until: datetime | None,
    ) -> dict[str, Any]:
        put_kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": self._physical_key(object_key),
            "Body": body,
            "ContentType": content_type,
            "ContentLength": byte_size,
            "Metadata": {
                "tenant_id": str(tenant_id),
                "sha256": digest,
                "filename": safe_name,
            },
        }
        if lock_mode is not None and lock_until is not None:
            put_kwargs["ObjectLockMode"] = lock_mode
            put_kwargs["ObjectLockRetainUntilDate"] = lock_until
            if md5_b64 is not None:
                put_kwargs["ContentMD5"] = md5_b64
        return put_kwargs

    def put_bytes(
        self,
        *,
        tenant_id: UUID,
        artifact_id: UUID,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        object_lock_mode: str | None = None,
        retain_until: datetime | None = None,
    ) -> StoredObjectMetadata:
        safe_name = sanitize_filename(filename)
        object_key = f"{tenant_id}/{artifact_id}/{safe_name}"
        _validate_tenant_object_key(tenant_id, object_key)
        lock_mode, lock_until = self._resolve_object_lock(object_lock_mode, retain_until)

        digest = hashlib.sha256(data).hexdigest()
        md5_b64 = (
            base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode("ascii")
            if lock_mode is not None
            else None
        )
        put_kwargs = self._build_put_kwargs(
            tenant_id=tenant_id,
            object_key=object_key,
            safe_name=safe_name,
            content_type=content_type,
            body=data,
            digest=digest,
            byte_size=len(data),
            md5_b64=md5_b64,
            lock_mode=lock_mode,
            lock_until=lock_until,
        )
        self._client.put_object(**put_kwargs)
        return StoredObjectMetadata(
            storage_backend=self.STORAGE_BACKEND,
            object_key=object_key,
            filename=safe_name,
            content_type=content_type,
            byte_size=len(data),
            sha256=digest,
            object_lock_mode=lock_mode,
            retain_until=lock_until,
        )

    def put_stream(
        self,
        tenant_id: UUID,
        key_prefix: str,
        stream: BinaryIO | Iterable[bytes],
        *,
        max_bytes: int = DEFAULT_MAX_STREAM_BYTES,
        filename: str | None = None,
        content_type: str = "application/octet-stream",
        chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE,
        object_lock_mode: str | None = None,
        retain_until: datetime | None = None,
    ) -> StoredObjectMetadata:
        object_key, safe_name = _build_stream_object_key(tenant_id, key_prefix, filename)
        _validate_tenant_object_key(tenant_id, object_key)
        lock_mode, lock_until = self._resolve_object_lock(object_lock_mode, retain_until)

        spool_limit = min(256 * 1024, max(1, max_bytes))
        with tempfile.SpooledTemporaryFile(max_size=spool_limit, mode="w+b") as tmp:
            total, digest, md5_b64 = _stream_into_sink(
                stream,
                tmp,  # type: ignore[arg-type]
                max_bytes=max_bytes,
                chunk_size=chunk_size,
                compute_md5=lock_mode is not None,
            )
            tmp.seek(0)
            put_kwargs = self._build_put_kwargs(
                tenant_id=tenant_id,
                object_key=object_key,
                safe_name=safe_name,
                content_type=content_type,
                body=tmp,  # type: ignore[arg-type]
                digest=digest,
                byte_size=total,
                md5_b64=md5_b64,
                lock_mode=lock_mode,
                lock_until=lock_until,
            )
            self._client.put_object(**put_kwargs)

        return StoredObjectMetadata(
            storage_backend=self.STORAGE_BACKEND,
            object_key=object_key,
            filename=safe_name,
            content_type=content_type,
            byte_size=total,
            sha256=digest,
            object_lock_mode=lock_mode,
            retain_until=lock_until,
        )

    def get_bytes(
        self,
        *,
        tenant_id: UUID,
        object_key: str,
        expected_sha256: str | None = None,
    ) -> bytes:
        _validate_tenant_object_key(tenant_id, object_key)
        try:
            response = self._client.get_object(
                Bucket=self.bucket,
                Key=self._physical_key(object_key),
            )
        except (FileNotFoundError, KeyError) as exc:
            raise FileNotFoundError(f"Evidence artifact {object_key} not found") from exc
        except Exception as exc:
            if _extract_s3_error_code(exc) in _NOT_FOUND_S3_CODES:
                raise FileNotFoundError(f"Evidence artifact {object_key} not found") from exc
            raise

        body = response["Body"]
        raw = body.read() if hasattr(body, "read") else bytes(body)
        _verify_sha256(raw, object_key, expected_sha256)
        return raw

    def delete(self, *, tenant_id: UUID, object_key: str) -> bool:
        _validate_tenant_object_key(tenant_id, object_key)
        s3_key = self._physical_key(object_key)
        if hasattr(self._client, "head_object"):
            try:
                self._client.head_object(Bucket=self.bucket, Key=s3_key)
            except (FileNotFoundError, KeyError):
                return False
            except Exception as exc:
                if _extract_s3_error_code(exc) in _NOT_FOUND_S3_CODES:
                    return False
                raise

        try:
            response = self._client.delete_object(Bucket=self.bucket, Key=s3_key)
        except (FileNotFoundError, KeyError):
            return False
        except Exception as exc:
            code = _extract_s3_error_code(exc)
            if code in _NOT_FOUND_S3_CODES:
                return False
            if code in _LOCK_DENIED_S3_CODES:
                raise PermissionError(
                    f"Evidence artifact {object_key} is protected by ObjectLock retention"
                ) from exc
            raise

        if isinstance(response, dict) and "Deleted" in response:
            return bool(response["Deleted"])
        return True


def build_object_storage(
    settings: Any | None = None,
    *,
    client: Any | None = None,
) -> ObjectStorage:
    """Instantiate the configured ObjectStorage backend from settings or environment."""
    if settings is None:
        from security.settings import get_settings

        settings = get_settings()

    backend_raw = getattr(settings, "storage_backend", None) or os.getenv(
        "AEGIS_STORAGE_BACKEND", "local"
    )
    backend = str(backend_raw).strip().lower()

    if backend in {"local", "local_object_store"}:
        root_dir = getattr(settings, "evidence_storage_dir", None) or os.getenv(
            "AEGIS_EVIDENCE_STORAGE_DIR", "./var/aegis-evidence"
        )
        return LocalObjectStorage(root_dir)

    if backend in {"s3", "r2", "s3_object_store"}:
        bucket = getattr(settings, "s3_bucket", None) or os.getenv("AEGIS_S3_BUCKET", "")
        if not str(bucket).strip():
            raise ValueError(
                "AEGIS_S3_BUCKET must be configured when storage_backend is 's3'"
            )
        region = (
            getattr(settings, "s3_region", None)
            or os.getenv("AEGIS_S3_REGION")
            or "us-east-1"
        )
        endpoint_url = (
            getattr(settings, "s3_endpoint_url", None)
            or os.getenv("AEGIS_S3_ENDPOINT_URL")
            or None
        )
        access_key_id = (
            getattr(settings, "s3_access_key_id", None)
            or os.getenv("AEGIS_S3_ACCESS_KEY_ID")
            or os.getenv("AWS_ACCESS_KEY_ID")
            or None
        )
        secret_access_key = (
            getattr(settings, "s3_secret_access_key", None)
            or os.getenv("AEGIS_S3_SECRET_ACCESS_KEY")
            or os.getenv("AWS_SECRET_ACCESS_KEY")
            or None
        )
        key_prefix = (
            getattr(settings, "s3_key_prefix", None)
            or os.getenv("AEGIS_S3_KEY_PREFIX", "")
        )
        object_lock_mode = (
            getattr(settings, "s3_object_lock_mode", None)
            or os.getenv("AEGIS_S3_OBJECT_LOCK_MODE")
            or None
        )
        retention_raw = getattr(settings, "s3_retention_days", None)
        if retention_raw is None:
            env_ret = os.getenv("AEGIS_S3_RETENTION_DAYS", "").strip()
            retention_days = int(env_ret) if env_ret else None
        else:
            retention_days = int(retention_raw)

        return S3ObjectStorage(
            bucket=str(bucket),
            region=str(region),
            endpoint_url=str(endpoint_url) if endpoint_url else None,
            access_key_id=str(access_key_id) if access_key_id else None,
            secret_access_key=str(secret_access_key) if secret_access_key else None,
            key_prefix=str(key_prefix),
            object_lock_mode=str(object_lock_mode) if object_lock_mode else None,
            default_retention_days=retention_days,
            client=client,
        )

    raise ValueError(f"Unsupported storage backend: {backend!r}. Expected 'local' or 's3'.")
