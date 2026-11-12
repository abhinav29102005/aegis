"""Tenant-scoped dispute case management with fail-closed human approval gates and optional durable persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from contracts import (
    DisputeAnalysis,
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    FinancialEventType,
    compute_payload_hash,
)
from contracts.models import utc_now
from security import assert_same_tenant

if TYPE_CHECKING:
    from database import LedgerRepository


class CaseNotFoundError(KeyError):
    """Raised when a requested dispute case does not exist."""


class ApprovalGateError(PermissionError):
    """Raised when external submission is attempted without explicit human approval."""


class SyntheticSubmissionError(PermissionError):
    """Raised when external submission is attempted for a synthetic demo case."""


class DisputeTransitionError(ValueError):
    """Raised when an invalid dispute status transition is attempted."""


VALID_DISPUTE_TRANSITIONS: dict[DisputeStatus, set[DisputeStatus]] = {
    DisputeStatus.OPEN: {
        DisputeStatus.UNDER_INVESTIGATION,
        DisputeStatus.DRAFT_READY,
        DisputeStatus.RESOLVED,
    },
    DisputeStatus.UNDER_INVESTIGATION: {
        DisputeStatus.DRAFT_READY,
        DisputeStatus.RESOLVED,
    },
    DisputeStatus.DRAFT_READY: {
        DisputeStatus.APPROVED_FOR_SUBMISSION,
        DisputeStatus.DRAFT_READY,
        DisputeStatus.RESOLVED,
    },
    DisputeStatus.APPROVED_FOR_SUBMISSION: {
        DisputeStatus.SUBMITTED,
        DisputeStatus.DRAFT_READY,
        DisputeStatus.RESOLVED,
    },
    DisputeStatus.SUBMITTED: {
        DisputeStatus.UNDER_INVESTIGATION,
        DisputeStatus.RESOLVED,
    },
    DisputeStatus.RESOLVED: set(),
}


def assert_dispute_transition(current: DisputeStatus, target: DisputeStatus) -> None:
    if current == DisputeStatus.RESOLVED:
        raise DisputeTransitionError("Case is already in terminal RESOLVED state")
    if target == current:
        return
    valid = VALID_DISPUTE_TRANSITIONS.get(current, set())
    if target not in valid:
        raise DisputeTransitionError(
            f"Invalid dispute status transition: {current.value} -> {target.value}"
        )
    allowed = VALID_DISPUTE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise DisputeTransitionError(
            f"Illegal DisputeStatus transition from {current.value} to {target.value}. "
            f"Allowed targets: {[s.value for s in allowed]}"
        )


class DisputeCaseService:
    """Tenant-isolated dispute case lifecycle and approval gate service.

    When initialized with a ``LedgerRepository``, all state, evidence links, analyses,
    and financial events are persisted durably in SQLAlchemy/PostgreSQL. When initialized
    with ``repo=None``, it operates as an isolated in-memory harness for unit tests.
    """

    def __init__(self, repo: LedgerRepository | None = None) -> None:
        self._repo = repo
        self._cases: dict[UUID, DisputeCase] = {}
        self._evidence: dict[UUID, list[EvidenceRecord]] = {}
        self._analyses: dict[UUID, list[DisputeAnalysis]] = {}

    def create_case(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        payment_intent_id: UUID,
        reason: str,
        buyer_claim: str,
        amount_minor: int,
        currency: str = "USD",
        source_type: DisputeSourceType = DisputeSourceType.SYNTHETIC_DEMO,
        is_synthetic: bool = True,
        evidence_records: list[EvidenceRecord] | None = None,
        paypal_dispute_id: str | None = None,
        case_id: UUID | None = None,
        actor_id: str = "disputeos",
        response_due_by: datetime | None = None,
    ) -> DisputeCase:
        """Create a tenant-scoped dispute case and link any validated evidence records."""
        resolved_case_id = case_id or uuid4()
        if self._repo is not None:
            existing = self._repo.get_dispute_case(tenant_id, resolved_case_id)
            if existing is not None:
                raise ValueError(f"Dispute case {resolved_case_id} already exists")
            intent = self._repo.get_intent(tenant_id, payment_intent_id)
            if intent is None:
                raise ValueError(
                    f"Referenced payment_intent_id {payment_intent_id} does not exist for tenant {tenant_id}"
                )
        elif resolved_case_id in self._cases:
            raise ValueError(f"Dispute case {resolved_case_id} already exists")

        validated_records: list[EvidenceRecord] = []
        seen_evidence_ids: set[UUID] = set()
        evidence_ids: list[UUID] = []

        if evidence_records:
            for record in evidence_records:
                assert_same_tenant(tenant_id, record.tenant_id, "evidence_record")
                if record.id not in seen_evidence_ids:
                    seen_evidence_ids.add(record.id)
                    if record.dispute_case_id != resolved_case_id:
                        record = record.model_copy(update={"dispute_case_id": resolved_case_id})
                    validated_records.append(record)
                    evidence_ids.append(record.id)

        effective_synthetic = is_synthetic or source_type == DisputeSourceType.SYNTHETIC_DEMO
        now = utc_now()
        case = DisputeCase(
            id=resolved_case_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            paypal_dispute_id=paypal_dispute_id,
            source_type=source_type,
            is_synthetic=effective_synthetic,
            reason=reason,
            buyer_claim=buyer_claim,
            amount_minor=amount_minor,
            currency=currency,
            status=DisputeStatus.OPEN,
            evidence_ids=evidence_ids,
            response_due_by=response_due_by,
            opened_at=now,
            updated_at=now,
        )
        if self._repo is not None:
            saved_case = self._repo.save_dispute_case(case)
            for rec in validated_records:
                self._repo.save_evidence(rec)
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                payment_intent_id=payment_intent_id,
                event_type=FinancialEventType.DISPUTE_OPENED,
                actor_type="DISPUTEOS",
                actor_id=actor_id,
                payload={
                    "dispute_case_id": str(saved_case.id),
                    "reason": reason,
                    "is_synthetic": effective_synthetic,
                },
            )
            return saved_case

        self._cases[case.id] = case
        self._evidence[case.id] = validated_records
        self._analyses[case.id] = []
        return case

    def get_case(self, tenant_id: UUID, case_id: UUID) -> DisputeCase:
        """Retrieve a dispute case after enforcing strict tenant isolation."""
        if self._repo is not None:
            case = self._repo.get_dispute_case(tenant_id, case_id)
            if case is None:
                raise CaseNotFoundError(f"Dispute case {case_id} not found")
            return case
        case = self._cases.get(case_id)
        if case is None:
            raise CaseNotFoundError(f"Dispute case {case_id} not found")
        assert_same_tenant(tenant_id, case.tenant_id, "dispute_case")
        return case

    def list_cases(
        self,
        tenant_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DisputeCase]:
        """List all dispute cases belonging to the specified tenant with limit/offset."""
        if self._repo is not None:
            cases = self._repo.list_dispute_cases(tenant_id)
        else:
            cases = [case for case in self._cases.values() if case.tenant_id == tenant_id]
        return cases[offset : offset + limit]

    def attach_evidence(
        self,
        tenant_id: UUID,
        case_id: UUID,
        records: list[EvidenceRecord],
        *,
        actor_id: str = "disputeos",
    ) -> DisputeCase:
        """Attach tenant-validated evidence records to an existing dispute case."""
        case = self.get_case(tenant_id, case_id)
        for record in records:
            assert_same_tenant(tenant_id, record.tenant_id, "evidence_record")

        if self._repo is not None:
            existing_records = self._repo.list_evidence(tenant_id, dispute_case_id=case_id)
            seen_ids = {r.id for r in existing_records}
            updated_evidence_ids = list(case.evidence_ids)
            seen_case_ids = set(updated_evidence_ids)
            for rec in records:
                normalized = rec if rec.dispute_case_id == case_id else rec.model_copy(update={"dispute_case_id": case_id})
                if normalized.id not in seen_ids:
                    self._repo.save_evidence(normalized)
                    seen_ids.add(normalized.id)
                if normalized.id not in seen_case_ids:
                    updated_evidence_ids.append(normalized.id)
                    seen_case_ids.add(normalized.id)
            updated = case.model_copy(update={"evidence_ids": updated_evidence_ids, "updated_at": utc_now()})
            saved = self._repo.save_dispute_case(updated)
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                event_type=FinancialEventType.EVIDENCE_ATTACHED,
                actor_type="DISPUTEOS",
                actor_id=actor_id,
                payload={
                    "dispute_case_id": str(case_id),
                    "evidence_ids": [str(r.id) for r in records],
                    "count": len(records),
                },
            )
            return saved

        existing_records = list(self._evidence.get(case_id, []))
        seen_ids = {record.id for record in existing_records}
        updated_evidence_ids = list(case.evidence_ids)
        seen_case_ids = set(updated_evidence_ids)

        for record in records:
            if record.id not in seen_ids:
                seen_ids.add(record.id)
                existing_records.append(record)
            if record.id not in seen_case_ids:
                seen_case_ids.add(record.id)
                updated_evidence_ids.append(record.id)

        updated_case = case.model_copy(
            update={
                "evidence_ids": updated_evidence_ids,
                "updated_at": utc_now(),
            }
        )
        self._evidence[case_id] = existing_records
        self._cases[case_id] = updated_case
        return updated_case

    def get_case_evidence(self, tenant_id: UUID, case_id: UUID) -> list[EvidenceRecord]:
        """Return all evidence records linked to a tenant-owned dispute case."""
        case = self.get_case(tenant_id, case_id)
        if self._repo is not None:
            linked = self._repo.list_evidence(tenant_id, dispute_case_id=case_id)
            if not linked and case.evidence_ids:
                by_id = {ev.id: ev for ev in self._repo.list_evidence(tenant_id, correlation_id=case.correlation_id)}
                return [by_id[eid] for eid in case.evidence_ids if eid in by_id]
            return linked
        return list(self._evidence.get(case_id, []))

    def record_analysis(
        self,
        tenant_id: UUID,
        case_id: UUID,
        analysis: DisputeAnalysis,
        *,
        actor_id: str = "dispute-analyzer",
    ) -> DisputeCase:
        """Store a DisputeAnalysis for a case and transition status to DRAFT_READY."""
        case = self.get_case(tenant_id, case_id)
        assert_same_tenant(tenant_id, analysis.tenant_id, "dispute_analysis")
        if analysis.dispute_case_id != case_id:
            raise ValueError(
                f"DisputeAnalysis dispute_case_id {analysis.dispute_case_id} does not match case {case_id}"
            )
        assert_dispute_transition(case.status, DisputeStatus.DRAFT_READY)

        updated_case = case.model_copy(
            update={
                "status": DisputeStatus.DRAFT_READY,
                "updated_at": utc_now(),
            }
        )
        if self._repo is not None:
            self._repo.save_dispute_analysis(analysis)
            saved_case = self._repo.save_dispute_case(updated_case)
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                event_type=FinancialEventType.DISPUTE_ANALYZED,
                actor_type="DISPUTEOS",
                actor_id=actor_id,
                payload={
                    "dispute_case_id": str(case_id),
                    "analysis_id": str(analysis.id),
                    "recommendation": analysis.recommendation.value,
                    "confidence_score": analysis.confidence_score,
                },
            )
            return saved_case

        self._analyses.setdefault(case_id, []).append(analysis)
        self._cases[case_id] = updated_case
        return updated_case

    def get_latest_analysis(
        self,
        tenant_id: UUID,
        case_id: UUID,
    ) -> DisputeAnalysis | None:
        """Return the most recent DisputeAnalysis for a tenant-owned dispute case."""
        self.get_case(tenant_id, case_id)
        if self._repo is not None:
            return self._repo.get_latest_dispute_analysis(tenant_id, case_id)
        analyses = self._analyses.get(case_id, [])
        return analyses[-1] if analyses else None

    def approve_for_submission(
        self,
        *,
        tenant_id: UUID,
        case_id: UUID,
        approver_id: str,
        draft_response_text: str,
    ) -> DisputeCase:
        """Record explicit human approval and bind the response hash before external submission."""
        case = self.get_case(tenant_id, case_id)
        cleaned_approver = approver_id.strip()
        if not cleaned_approver:
            raise ValueError("approver_id must not be empty")
        if not draft_response_text.strip():
            raise ValueError("draft_response_text must not be empty")
        assert_dispute_transition(case.status, DisputeStatus.APPROVED_FOR_SUBMISSION)

        now = utc_now()
        response_payload_hash = compute_payload_hash({
            "case_id": str(case_id),
            "draft_response_text": draft_response_text,
        })
        updated_case = case.model_copy(
            update={
                "human_approved_for_submission": True,
                "approved_by": cleaned_approver,
                "approved_at": now,
                "response_payload_hash": response_payload_hash,
                "status": DisputeStatus.APPROVED_FOR_SUBMISSION,
                "updated_at": now,
            }
        )
        if self._repo is not None:
            saved_case = self._repo.save_dispute_case(updated_case)
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                event_type=FinancialEventType.DISPUTE_RESPONSE_APPROVED,
                actor_type="HUMAN_REVIEWER",
                actor_id=cleaned_approver,
                payload={
                    "dispute_case_id": str(case_id),
                    "response_payload_hash": response_payload_hash,
                },
            )
            return saved_case

        self._cases[case_id] = updated_case
        return updated_case

    def mark_submitted(
        self,
        *,
        tenant_id: UUID,
        case_id: UUID,
    ) -> DisputeCase:
        """Mark a dispute case as submitted only if human-approved and non-synthetic."""
        case = self.get_case(tenant_id, case_id)
        if (
            not case.human_approved_for_submission
            or case.status != DisputeStatus.APPROVED_FOR_SUBMISSION
            or not case.approved_by
            or not case.response_payload_hash
        ):
            raise ApprovalGateError(
                f"Dispute case {case_id} requires explicit human approval before submission"
            )
        if case.is_synthetic or case.source_type == DisputeSourceType.SYNTHETIC_DEMO:
            raise SyntheticSubmissionError(
                f"Synthetic dispute case {case_id} cannot be submitted externally"
            )
        assert_dispute_transition(case.status, DisputeStatus.SUBMITTED)

        updated_case = case.model_copy(
            update={
                "status": DisputeStatus.SUBMITTED,
                "updated_at": utc_now(),
            }
        )
        if self._repo is not None:
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                event_type=FinancialEventType.DISPUTE_SUBMITTED,
                actor_type="DISPUTEOS",
                actor_id=case.approved_by or "disputeos",
                payload={
                    "dispute_case_id": str(case_id),
                    "paypal_dispute_id": case.paypal_dispute_id,
                    "response_payload_hash": case.response_payload_hash,
                },
            )
            return self._repo.save_dispute_case(updated_case)
        self._cases[case_id] = updated_case
        return updated_case

    def mark_resolved(
        self,
        *,
        tenant_id: UUID,
        case_id: UUID,
        resolution_outcome: str | None = None,
        actor_id: str = "dispute-resolver",
    ) -> DisputeCase:
        """Transition a dispute case to RESOLVED and record financial event."""
        case = self.get_case(tenant_id, case_id)
        assert_dispute_transition(case.status, DisputeStatus.RESOLVED)
        now = utc_now()
        outcome_str = resolution_outcome or "RESOLVED"
        updated_case = case.model_copy(
            update={
                "status": DisputeStatus.RESOLVED,
                "resolved_at": now,
                "resolution_outcome": outcome_str,
                "updated_at": now,
            }
        )
        if self._repo is not None:
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                event_type=FinancialEventType.DISPUTE_RESOLVED,
                actor_type="DISPUTEOS",
                actor_id=actor_id,
                payload={
                    "dispute_case_id": str(case_id),
                    "resolution_outcome": outcome_str,
                },
            )
            return self._repo.save_dispute_case(updated_case)
        self._cases[case_id] = updated_case
        return updated_case
