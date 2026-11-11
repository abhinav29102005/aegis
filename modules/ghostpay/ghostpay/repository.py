"""Read-only repository protocol for future database-backed GhostPay replay."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from contracts import ReplayRequest


@runtime_checkable
class GhostPayReplayRepository(Protocol):
    """Interface required to reconstruct a canonical ReplayRequest from persistent ledger storage.

    Note: The current GhostPay runtime is stateless and accepts complete ``ReplayRequest``
    payloads. When ``services/api`` wires database persistence via ``packages/database``, an
    adapter over ``LedgerRepository`` should implement this read-only protocol.
    """

    def load_replay_request(
        self,
        tenant_id: UUID,
        correlation_id: UUID,
    ) -> ReplayRequest | None:
        """Load tenant-scoped persisted records for ``correlation_id`` or return None if absent."""
        ...
