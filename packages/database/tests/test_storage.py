"""Tests for LocalObjectStorage, S3ObjectStorage, bounded streaming, factory, and retention/erasure helpers."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from database.storage import (
    DEFAULT_MAX_STREAM_BYTES,
    DEFAULT_WORM_RETENTION_DAYS,
    LocalObjectStorage,
    ObjectSizeLimitExceededError,
    ObjectStorage,
    S3ObjectStorage,
    build_object_storage,
    compute_worm_retain_until,
    delete_if_erased,
    is_retention_expired,
)
from security.settings import NexusSettings


class FakeS3ClientError(Exception):
    """Minimal stand-in for botocore.exceptions.ClientError."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        }


class FakeS3Client:
    """Hermetic in-memory S3/R2 client supporting Object Lock semantics."""

    def __init__(self, *, now_fn: Any = None) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.put_calls: list[dict[str, Any]] = []
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        body = kwargs["Body"]
        raw = body.read() if hasattr(body, "read") else bytes(body)
        record = {
            "Body": raw,
            "ContentType": kwargs.get("ContentType"),
            "ContentLength": kwargs.get("ContentLength", len(raw)),
            "ContentMD5": kwargs.get("ContentMD5"),
            "Metadata": dict(kwargs.get("Metadata", {})),
            "ObjectLockMode": kwargs.get("ObjectLockMode"),
            "ObjectLockRetainUntilDate": kwargs.get("ObjectLockRetainUntilDate"),
        }
        self.objects[(bucket, key)] = record
        self.put_calls.append({**kwargs, "BodySize": len(raw)})
        return {"ETag": '"fake-etag"'}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        record = self.objects.get((Bucket, Key))
        if record is None:
            raise FakeS3ClientError("NoSuchKey", status_code=404)
        return {
            "Body": io.BytesIO(record["Body"]),
            "ContentType": record["ContentType"],
            "Metadata": record["Metadata"],
        }

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        record = self.objects.get((Bucket, Key))
        if record is None:
            raise FakeS3ClientError("404", status_code=404)
        return {"ContentLength": len(record["Body"])}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        record = self.objects.get((Bucket, Key))
        if record is None:
            return {"Deleted": False}
        retain_until = record.get("ObjectLockRetainUntilDate")
        if (
            record.get("ObjectLockMode") == "COMPLIANCE"
            and retain_until is not None
            and retain_until > self._now_fn()
        ):
            raise FakeS3ClientError("AccessDenied", status_code=403)
        del self.objects[(Bucket, Key)]
        return {"Deleted": True}


class BoundedReadTrackingStream:
    """Stream that tracks bytes read and fails if caller tries to drain past the cap."""

    def __init__(self, total_size: int, fill_byte: bytes = b"x") -> None:
        self.total_size = total_size
        self.fill_byte = fill_byte
        self.bytes_read = 0

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            raise AssertionError("put_stream must not call unbounded .read()!")
        remaining = self.total_size - self.bytes_read
        if remaining <= 0:
            return b""
        to_read = min(n, remaining)
        self.bytes_read += to_read
        return self.fill_byte * to_read


def test_local_object_storage_roundtrip_delete_and_guards(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path / "evidence")
    assert isinstance(storage, ObjectStorage)

    tenant_a = uuid4()
    tenant_b = uuid4()
    artifact_id = uuid4()
    payload = b"%PDF-1.4\nSigned delivery receipt\n"

    meta = storage.put_bytes(
        tenant_id=tenant_a,
        artifact_id=artifact_id,
        filename="../../receipt (final).pdf",
        data=payload,
        content_type="application/pdf",
    )
    assert meta.storage_backend == "LOCAL_OBJECT_STORE"
    assert meta.object_key == f"{tenant_a}/{artifact_id}/receipt_final_.pdf"
    assert meta.byte_size == len(payload)

    assert (
        storage.get_bytes(
            tenant_id=tenant_a,
            object_key=meta.object_key,
            expected_sha256=meta.sha256,
        )
        == payload
    )

    with pytest.raises(ValueError, match="integrity mismatch"):
        storage.get_bytes(
            tenant_id=tenant_a,
            object_key=meta.object_key,
            expected_sha256="0" * 64,
        )

    with pytest.raises(PermissionError):
        storage.get_bytes(tenant_id=tenant_b, object_key=meta.object_key)

    with pytest.raises(PermissionError):
        storage.delete(tenant_id=tenant_b, object_key=meta.object_key)

    with pytest.raises(ValueError, match="Invalid object key"):
        storage.get_bytes(
            tenant_id=tenant_a,
            object_key=f"{tenant_a}/../{tenant_b}/secret.pdf",
        )

    assert storage.delete(tenant_id=tenant_a, object_key=meta.object_key) is True
    assert storage.delete(tenant_id=tenant_a, object_key=meta.object_key) is False
    with pytest.raises(FileNotFoundError):
        storage.get_bytes(tenant_id=tenant_a, object_key=meta.object_key)


def test_local_put_stream_exact_limit_and_abort_over_10mb(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path / "stream-store")
    tenant_id = uuid4()

    # Exact 10 MiB boundary succeeds without raising.
    exact_stream = BoundedReadTrackingStream(DEFAULT_MAX_STREAM_BYTES, b"a")
    meta = storage.put_stream(
        tenant_id,
        "exports/exact",
        exact_stream,
        filename="exact.bin",
        content_type="application/octet-stream",
    )
    assert meta.byte_size == DEFAULT_MAX_STREAM_BYTES
    assert exact_stream.bytes_read == DEFAULT_MAX_STREAM_BYTES

    # >10 MiB stream (e.g. 25 MiB) aborts immediately at 10 MiB + 1 byte without draining RAM.
    oversized_stream = BoundedReadTrackingStream(25 * 1024 * 1024, b"b")
    with pytest.raises(ObjectSizeLimitExceededError, match="10485760"):
        storage.put_stream(
            tenant_id,
            "exports/oversize",
            oversized_stream,
            filename="too-big.bin",
        )
    assert oversized_stream.bytes_read == DEFAULT_MAX_STREAM_BYTES + 1
    assert not (tmp_path / "stream-store" / str(tenant_id) / "exports" / "oversize").exists()


def test_local_put_stream_iterable_and_traversal_rejection(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path / "iter-store")
    tenant_id = uuid4()

    def chunk_gen() -> Any:
        yield b"hello "
        yield b""
        yield b"world"

    meta = storage.put_stream(
        tenant_id,
        "case-1/proof.txt",
        chunk_gen(),
        max_bytes=64,
    )
    assert meta.object_key == f"{tenant_id}/case-1/proof.txt"
    assert meta.filename == "proof.txt"
    assert storage.get_bytes(tenant_id=tenant_id, object_key=meta.object_key) == b"hello world"

    with pytest.raises(ValueError, match="Invalid object key"):
        storage.put_stream(tenant_id, "../../escape", io.BytesIO(b"nope"))


def test_s3_object_storage_r2_and_worm_object_lock() -> None:
    now = datetime(2026, 11, 12, 0, 0, 0, tzinfo=UTC)
    fake_client = FakeS3Client(now_fn=lambda: now)
    retain_until = compute_worm_retain_until(DEFAULT_WORM_RETENTION_DAYS, now=now)

    s3 = S3ObjectStorage(
        bucket="aegis-worm-ledger",
        region="auto",
        endpoint_url="https://account-id.r2.cloudflarestorage.com",
        key_prefix="prod-ledger",
        object_lock_mode="COMPLIANCE",
        default_retention_days=DEFAULT_WORM_RETENTION_DAYS,
        client=fake_client,
    )
    assert isinstance(s3, ObjectStorage)
    assert s3.endpoint_url == "https://account-id.r2.cloudflarestorage.com"

    tenant_id = uuid4()
    other_tenant = uuid4()
    artifact_id = uuid4()
    ledger_json = b'{"event":"PAYMENT_CAPTURED","amount_minor":4900}'

    meta = s3.put_bytes(
        tenant_id=tenant_id,
        artifact_id=artifact_id,
        filename="ledger_export.json",
        data=ledger_json,
        content_type="application/json",
        retain_until=retain_until,
    )
    assert meta.storage_backend == "S3_OBJECT_STORE"
    assert meta.object_key == f"{tenant_id}/{artifact_id}/ledger_export.json"
    assert meta.object_lock_mode == "COMPLIANCE"
    assert meta.retain_until == retain_until

    physical_key = f"prod-ledger/{meta.object_key}"
    stored = fake_client.objects[("aegis-worm-ledger", physical_key)]
    assert stored["ObjectLockMode"] == "COMPLIANCE"
    assert stored["ObjectLockRetainUntilDate"] == retain_until
    assert stored["ContentMD5"] is not None
    assert stored["Metadata"]["sha256"] == meta.sha256

    assert (
        s3.get_bytes(
            tenant_id=tenant_id,
            object_key=meta.object_key,
            expected_sha256=meta.sha256,
        )
        == ledger_json
    )

    with pytest.raises(PermissionError):
        s3.get_bytes(tenant_id=other_tenant, object_key=meta.object_key)

    with pytest.raises(FileNotFoundError):
        s3.get_bytes(tenant_id=tenant_id, object_key=f"{tenant_id}/missing/file.json")

    # Active WORM compliance lock prevents deletion.
    with pytest.raises(PermissionError, match="ObjectLock retention"):
        s3.delete(tenant_id=tenant_id, object_key=meta.object_key)


def test_s3_put_stream_size_enforcement_and_governance_delete() -> None:
    fake_client = FakeS3Client()
    s3 = S3ObjectStorage(
        bucket="aegis-evidence",
        object_lock_mode="GOVERNANCE",
        default_retention_days=30,
        client=fake_client,
    )
    tenant_id = uuid4()

    # Oversized >10 MiB stream aborts before put_object is ever called.
    oversized = BoundedReadTrackingStream(12 * 1024 * 1024, b"z")
    with pytest.raises(ObjectSizeLimitExceededError):
        s3.put_stream(tenant_id, "disputes/case-9", oversized, filename="huge.pdf")
    assert oversized.bytes_read == DEFAULT_MAX_STREAM_BYTES + 1
    assert fake_client.put_calls == []

    # Valid stream upload succeeds and sends ObjectLock headers.
    small_stream = io.BytesIO(b"valid evidence stream payload")
    meta = s3.put_stream(
        tenant_id,
        "disputes/case-9",
        small_stream,
        max_bytes=1024,
        filename="proof.bin",
        content_type="application/octet-stream",
    )
    assert len(fake_client.put_calls) == 1
    assert fake_client.put_calls[0]["ObjectLockMode"] == "GOVERNANCE"
    assert s3.get_bytes(tenant_id=tenant_id, object_key=meta.object_key, expected_sha256=meta.sha256) == (
        b"valid evidence stream payload"
    )
    assert s3.delete(tenant_id=tenant_id, object_key=meta.object_key) is True
    assert s3.delete(tenant_id=tenant_id, object_key=meta.object_key) is False


def test_s3_object_storage_validation_and_missing_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="bucket"):
        S3ObjectStorage(bucket="   ", client=FakeS3Client())

    with pytest.raises(ValueError, match="Unsupported S3 ObjectLockMode"):
        S3ObjectStorage(bucket="bkt", object_lock_mode="INVALID", client=FakeS3Client())

    # Simulate boto3 missing when no client is injected.
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "boto3":
            raise ImportError("No module named 'boto3'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="boto3 is required"):
        S3ObjectStorage(bucket="aegis-prod")


def test_build_object_storage_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Default NexusSettings -> LocalObjectStorage
    monkeypatch.delenv("AEGIS_STORAGE_BACKEND", raising=False)
    local_settings = NexusSettings(evidence_storage_dir=str(tmp_path / "ev"))
    local_store = build_object_storage(local_settings)
    assert isinstance(local_store, LocalObjectStorage)
    assert local_store.root_dir == (tmp_path / "ev").resolve()

    # S3 settings object -> S3ObjectStorage
    @dataclass
    class FakeS3Settings:
        storage_backend: str = "s3"
        s3_bucket: str = "aegis-r2-bucket"
        s3_region: str = "auto"
        s3_endpoint_url: str = "https://r2.example.invalid"
        s3_key_prefix: str = "tenant-evidence"
        s3_object_lock_mode: str = "GOVERNANCE"
        s3_retention_days: int = 2555

    fake_client = FakeS3Client()
    s3_store = build_object_storage(FakeS3Settings(), client=fake_client)
    assert isinstance(s3_store, S3ObjectStorage)
    assert s3_store.bucket == "aegis-r2-bucket"
    assert s3_store.endpoint_url == "https://r2.example.invalid"
    assert s3_store.object_lock_mode == "GOVERNANCE"
    assert s3_store.default_retention_days == 2555

    # Env var fallback via default get_settings() and NexusSettings()
    from security.settings import get_settings

    monkeypatch.setenv("AEGIS_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AEGIS_S3_BUCKET", "env-bucket")
    get_settings.cache_clear()
    try:
        env_store = build_object_storage(None, client=fake_client)
        assert isinstance(env_store, S3ObjectStorage)
        assert env_store.bucket == "env-bucket"

        # Missing bucket fails closed
        monkeypatch.delenv("AEGIS_S3_BUCKET", raising=False)
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="AEGIS_S3_BUCKET"):
            build_object_storage(None, client=fake_client)

        # Unknown backend fails closed
        monkeypatch.setenv("AEGIS_STORAGE_BACKEND", "ftp")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="Unsupported storage backend"):
            build_object_storage(None)
    finally:
        get_settings.cache_clear()


def test_retention_and_gdpr_erasure_sweep_helpers(tmp_path: Path) -> None:
    now = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)
    assert is_retention_expired(None, now=now) is True
    assert is_retention_expired(now - timedelta(seconds=1), now=now) is True
    assert is_retention_expired(now, now=now) is True
    assert is_retention_expired(now + timedelta(days=1), now=now) is False
    # Naive datetime normalized safely as UTC
    assert is_retention_expired(datetime(2026, 11, 12, 11, 59, 0), now=now) is True

    storage = LocalObjectStorage(tmp_path / "erasure")
    tenant_id = uuid4()
    meta = storage.put_bytes(
        tenant_id=tenant_id,
        artifact_id=uuid4(),
        filename="kyc.pdf",
        data=b"pii-document",
    )

    # 1. Not erased -> retained
    assert (
        delete_if_erased(
            storage,
            tenant_id=tenant_id,
            object_key=meta.object_key,
            erased=False,
            retention_until=now - timedelta(days=1),
            now=now,
        )
        is False
    )

    # 2. Erased, but legal hold active -> retained
    assert (
        delete_if_erased(
            storage,
            tenant_id=tenant_id,
            object_key=meta.object_key,
            erased=True,
            legal_hold=True,
            retention_until=now - timedelta(days=1),
            now=now,
        )
        is False
    )

    # 3. Erased, no legal hold, but retention still active -> retained
    assert (
        delete_if_erased(
            storage,
            tenant_id=tenant_id,
            object_key=meta.object_key,
            erased=True,
            legal_hold=False,
            retention_until=now + timedelta(days=30),
            now=now,
        )
        is False
    )
    assert storage.get_bytes(tenant_id=tenant_id, object_key=meta.object_key) == b"pii-document"

    # 4. Erased, no legal hold, retention expired -> deleted
    assert (
        delete_if_erased(
            storage,
            tenant_id=tenant_id,
            object_key=meta.object_key,
            erased_at=now - timedelta(hours=1),
            legal_hold=False,
            retention_until=now - timedelta(seconds=1),
            now=now,
        )
        is True
    )
    with pytest.raises(FileNotFoundError):
        storage.get_bytes(tenant_id=tenant_id, object_key=meta.object_key)
