"""Tenant-scoped binary artifact storage with SHA-256 verification.

Prevents large binary files from bloating transactional database rows while
preserving cryptographic content hashes and strict tenant directory isolation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StoredObjectMetadata:
    storage_backend: str
    object_key: str
    filename: str
    content_type: str
    byte_size: int
    sha256: str


class LocalObjectStorage:
    """Filesystem-backed object store intended for single-node dev or mounted shared volumes."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        base = Path(filename).name.strip() or "artifact.bin"
        cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._")
        return cleaned[:180] or "artifact.bin"

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
        target = (self.root_dir / object_key).resolve()
        if self.root_dir not in target.parents:
            raise ValueError("Invalid object key path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return StoredObjectMetadata(
            storage_backend="LOCAL_OBJECT_STORE",
            object_key=object_key,
            filename=safe_name,
            content_type=content_type,
            byte_size=len(data),
            sha256=digest,
        )

    def get_bytes(self, *, tenant_id: UUID, object_key: str, expected_sha256: str | None = None) -> bytes:
        expected_prefix = f"{tenant_id}/"
        if not object_key.startswith(expected_prefix):
            raise PermissionError("Cross-tenant object storage access denied")
        target = (self.root_dir / object_key).resolve()
        if self.root_dir not in target.parents or not target.is_file():
            raise FileNotFoundError(f"Evidence artifact {object_key} not found")
        raw = target.read_bytes()
        if expected_sha256 is not None:
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected_sha256:
                raise ValueError(
                    f"Evidence artifact integrity mismatch for {object_key}: {actual} != {expected_sha256}"
                )
        return raw
