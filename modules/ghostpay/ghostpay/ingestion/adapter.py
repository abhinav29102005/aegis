"""Financial trace ingestion adapter."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    AuthorizationDecision,
    EvidenceRecord,
    FinancialEvent,
    Merchant,
    PaymentIntent,
    QuoteSnapshot,
    SpendingPassport,
)
from ghostpay.domain.exceptions import (
    IntegrityError,
)
from ghostpay.domain.models import PaymentTrace
from ghostpay.ingestion.validation import TraceValidator


class TraceIngestionAdapter:
    """Consumes and normalizes financial events and evidence into a versioned PaymentTrace."""

    def __init__(self) -> None:
        self.traces: dict[UUID, PaymentTrace] = {}
        self.seen_events: dict[tuple[UUID, UUID], FinancialEvent] = {}  # (tenant_id, event_id) -> event

    def ingest_event(
        self,
        tenant_id: UUID,
        event: FinancialEvent,
    ) -> FinancialEvent:
        """Ingest a single financial event with duplicate and conflict detection."""
        TraceValidator.validate_tenant_isolation(tenant_id, events=[event])

        key = (tenant_id, event.id)
        if key in self.seen_events:
            existing = self.seen_events[key]
            # Identical duplicate: idempotent return
            if (
                existing.event_hash == event.event_hash
                and existing.sequence_number == event.sequence_number
                and existing.payload == event.payload
            ):
                return existing
            # Conflicting duplicate: integrity error
            raise IntegrityError(
                f"Conflicting duplicate event detected for event ID {event.id}: "
                f"existing hash {existing.event_hash} != incoming hash {event.event_hash}"
            )

        self.seen_events[key] = event
        return event

    def build_trace(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        payment_intent_id: UUID,
        events: list[FinancialEvent],
        quote_snapshot: QuoteSnapshot | None = None,
        evidence_records: list[EvidenceRecord] | None = None,
        recorded_decision: AuthorizationDecision | None = None,
        recorded_passport: SpendingPassport | None = None,
        recorded_merchant: Merchant | None = None,
        approval_record: ApprovalRecord | None = None,
        payment_intent: PaymentIntent | None = None,
        policy_version: str = "policy-v1",
        strict_integrity: bool = False,
    ) -> PaymentTrace:
        """Assemble, validate, and index a PaymentTrace."""
        ev_list = evidence_records or []

        # 1. Tenant boundary enforcement
        TraceValidator.validate_tenant_isolation(
            tenant_id,
            events=events,
            evidence_records=ev_list,
            intent=payment_intent,
        )

        # 2. Ingest and deduplicate events
        deduped_events: list[FinancialEvent] = []
        for ev in events:
            deduped_events.append(self.ingest_event(tenant_id, ev))

        # 3. Sort chronologically and by sequence number
        sorted_events = sorted(deduped_events, key=lambda e: (e.occurred_at, e.sequence_number))

        # 4. Integrity and provenance validation
        chain_valid, chain_errors = TraceValidator.validate_event_chain(sorted_events)
        evidence_valid, evidence_errors = TraceValidator.validate_evidence_records(ev_list)

        missing_evidence: list[str] = []
        if quote_snapshot is None:
            missing_evidence.append("MISSING_QUOTE_SNAPSHOT")
        if recorded_decision is None:
            missing_evidence.append("MISSING_RECORDED_DECISION")
        if recorded_passport is None:
            missing_evidence.append("MISSING_RECORDED_PASSPORT")

        all_errors = chain_errors + evidence_errors

        if strict_integrity and all_errors:
            raise IntegrityError(f"Trace failed integrity validation: {'; '.join(all_errors)}")

        if any("CONFLICTING" in err for err in all_errors):
            integrity_status = "CONFLICTING"
        elif any("TAMPERED" in err for err in all_errors) or any("BROKEN" in err for err in all_errors):
            integrity_status = "TAMPERED"
        elif any("MISSING" in err for err in all_errors) or missing_evidence:
            integrity_status = "INCOMPLETE"
        else:
            integrity_status = "VALID"

        provenance_refs = [f"event:{e.id}" for e in sorted_events] + [f"evidence:{ev.id}" for ev in ev_list]

        trace = PaymentTrace(
            trace_id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            payment_intent_id=payment_intent_id,
            ordered_events=sorted_events,
            quote_snapshot=quote_snapshot,
            authorization_evidence=ev_list,
            recorded_decision=recorded_decision,
            recorded_passport=recorded_passport,
            recorded_merchant=recorded_merchant,
            approval_record=approval_record,
            payment_intent=payment_intent,
            policy_version=policy_version,
            integrity_status=integrity_status,
            missing_evidence=missing_evidence + all_errors,
            provenance_references=provenance_refs,
        )
        self.traces[trace.trace_id] = trace
        return trace

    def get_trace(self, trace_id: UUID) -> PaymentTrace | None:
        return self.traces.get(trace_id)

