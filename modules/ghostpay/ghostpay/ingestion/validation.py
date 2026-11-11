"""Validation engine for financial trace ingestion."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from contracts import (
    EvidenceRecord,
    FinancialEvent,
    PaymentIntent,
    compute_payload_hash,
)
from ghostpay.domain.exceptions import (
    CrossTenantAccessError,
    IntegrityError,
)
from security import compute_financial_event_hash


class TraceValidator:
    """Validates structural and cryptographic integrity of ingested financial traces."""

    @classmethod
    def validate_tenant_isolation(
        cls,
        expected_tenant_id: UUID,
        *,
        events: list[FinancialEvent] | None = None,
        evidence_records: list[EvidenceRecord] | None = None,
        intent: PaymentIntent | None = None,
    ) -> None:
        """Enforce strict tenant boundary across all trace components."""
        if intent is not None and intent.tenant_id != expected_tenant_id:
            raise CrossTenantAccessError(
                f"Tenant isolation breach: intent tenant {intent.tenant_id} != expected {expected_tenant_id}"
            )

        if events:
            for ev in events:
                if ev.tenant_id != expected_tenant_id:
                    raise CrossTenantAccessError(
                        f"Tenant isolation breach: event {ev.id} tenant {ev.tenant_id} != expected {expected_tenant_id}"
                    )

        if evidence_records:
            for rec in evidence_records:
                if rec.tenant_id != expected_tenant_id:
                    raise CrossTenantAccessError(
                        f"Tenant isolation breach: evidence {rec.id} tenant {rec.tenant_id} != expected {expected_tenant_id}"
                    )

    @classmethod
    def validate_event_chain(
        cls,
        events: list[FinancialEvent],
    ) -> tuple[bool, list[str]]:
        """Validate hash-chained event integrity, detecting tampering and missing sequences."""
        if not events:
            return True, []

        errors: list[str] = []
        seen_ids: dict[UUID, FinancialEvent] = {}
        seen_sequences: set[int] = set()

        sorted_events = sorted(events, key=lambda e: (e.occurred_at, e.sequence_number))

        for idx, ev in enumerate(sorted_events):
            expected_seq = idx + 1

            # 1. Duplicate event ID check
            if ev.id in seen_ids:
                existing = seen_ids[ev.id]
                if existing.event_hash != ev.event_hash or existing.payload != ev.payload:
                    errors.append(f"CONFLICTING_DUPLICATE_EVENT: ID {ev.id} has conflicting payload")
                continue
            seen_ids[ev.id] = ev

            # 2. Sequence continuity check
            if ev.sequence_number in seen_sequences:
                errors.append(f"DUPLICATE_SEQUENCE_NUMBER: Sequence {ev.sequence_number} appears multiple times")
            seen_sequences.add(ev.sequence_number)

            if ev.sequence_number != expected_seq:
                errors.append(
                    f"MISSING_EVENT_SEQUENCE: Expected sequence {expected_seq}, observed {ev.sequence_number}"
                )

            # 3. Previous hash pointer check
            expected_prev_hash = sorted_events[idx - 1].event_hash if idx > 0 else None
            if ev.previous_event_hash != expected_prev_hash:
                errors.append(
                    f"EVENT_CHAIN_BROKEN: Event {ev.id} (seq {ev.sequence_number}) "
                    f"previous_event_hash {ev.previous_event_hash} != expected {expected_prev_hash}"
                )

            # 4. Recompute event hash
            recomputed_hash = compute_financial_event_hash(
                event_id=ev.id,
                tenant_id=ev.tenant_id,
                correlation_id=ev.correlation_id,
                payment_intent_id=ev.payment_intent_id,
                sequence_number=ev.sequence_number,
                event_type=ev.event_type.value,
                actor_type=ev.actor_type,
                actor_id=ev.actor_id,
                payload=ev.payload,
                previous_event_hash=ev.previous_event_hash,
                occurred_at_iso=ev.occurred_at.isoformat(),
            )
            if ev.event_hash != recomputed_hash:
                errors.append(
                    f"EVENT_HASH_TAMPERED: Event {ev.id} hash {ev.event_hash} != recomputed {recomputed_hash}"
                )

        is_valid = len(errors) == 0
        return is_valid, errors

    @classmethod
    def validate_evidence_records(
        cls,
        evidence_records: list[EvidenceRecord],
    ) -> tuple[bool, list[str]]:
        """Validate evidence content hashes."""
        from ghostpay.forensics.provenance import verify_evidence_digest

        errors: list[str] = []
        for rec in evidence_records:
            valid, err = verify_evidence_digest(rec)
            if not valid and err:
                errors.append(f"EVIDENCE_TAMPERED: {err}")
        return len(errors) == 0, errors
