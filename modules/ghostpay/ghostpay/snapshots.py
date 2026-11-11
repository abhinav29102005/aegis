"""Read-only historical snapshot integration; never assemble history from live policy."""

from pathlib import Path
from uuid import UUID

from contracts import ReplayRequest
from pydantic import ValidationError
from security import assert_same_tenant


class SnapshotDirectory:
    """Trusted operator-supplied snapshots, partitioned by authenticated tenant."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def load(self, tenant_id: UUID, payment_id: UUID) -> ReplayRequest | None:
        path = (self.root / str(tenant_id) / f"{payment_id}.json").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Snapshot path leaves configured directory")
        try:
            with path.open("rb") as file:
                content = file.read(2_097_153)
        except FileNotFoundError:
            return None
        if len(content) > 2_097_152:
            raise ValueError("Snapshot exceeds supported size")
        try:
            record = ReplayRequest.model_validate_json(content)
        except ValidationError as exc:
            raise ValueError("Stored snapshot is invalid") from exc
        assert_same_tenant(tenant_id, record.tenant_id, "stored snapshot")
        if record.payment_intent.id != payment_id:
            raise ValueError("Stored snapshot payment identity mismatch")
        return record
