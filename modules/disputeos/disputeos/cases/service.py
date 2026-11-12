"""Tenant-scoped dispute case management with fail-closed human approval gates and optional durable persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from contracts import (
    DisputeAnalysis,
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    FinancialEventType,
    assert_dispute_transition,
    compute_payload_hash,
)
from contracts.models import utc_now
from security import assert_same_tenant

from disputeos.ingestion.normalizer import (
    assert_evidence_digest,
    normalize_evidence_record,
)

if TYPE_CHECKING:
    from database import LedgerRepository


class CaseNotFoundError(KeyError):
    """Raised when a requested dispute case does not exist."""


class ApprovalGateError(PermissionError):
    """Raised when external submission is attempted without explicit human approval."""


class SyntheticSubmissionError(PermissionError):
    """Raised when external submission is attempted for a synthetic demo case."""


class InvalidDisputeTransitionError(ValueError):
    """Raised when a dispute status transition violates the monotonic state machine."""


def _assert_transition(current: DisputeStatus, target: DisputeStatus) -> None:
    try:
        assert_dispute_transition(current, target)
    except ValueError as exc:
        raise InvalidDisputeTransitionError(str(exc)) from exc


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
        external_status: str | None = None,
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
            external_status=external_status[:64] if external_status else None,
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
                    "paypal_dispute_id": paypal_dispute_id,
                    "response_due_by": saved_case.response_due_by.isoformat()
                    if saved_case.response_due_by
                    else None,
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
        """List dispute cases belonging to the specified tenant with pagination."""
        if self._repo is not None:
            return self._repo.list_dispute_cases(tenant_id, limit=limit, offset=offset)
        cases = [case for case in self._cases.values() if case.tenant_id == tenant_id]
        cases.sort(key=lambda c: c.opened_at, reverse=True)
        return cases[offset : offset + limit]

    def attach_evidence(
        self,
        tenant_id: UUID,
        case_id: UUID,
        records: list[EvidenceRecord],
        *,
        actor_id: str = "disputeos",
        actor_type: str = "DISPUTEOS",
    ) -> DisputeCase:
        """Attach tenant- and digest-validated evidence records to an existing dispute case."""
        case = self.get_case(tenant_id, case_id)
        if case.status == DisputeStatus.RESOLVED:
            raise InvalidDisputeTransitionError(
                f"Cannot attach evidence to resolved dispute case {case_id}"
            )

        normalized_records: list[EvidenceRecord] = []
        for record in records:
            assert_same_tenant(tenant_id, record.tenant_id, "evidence_record")
            if record.dispute_case_id is not None and record.dispute_case_id != case_id:
                raise ValueError(
                    f"EvidenceRecord {record.id} belongs to dispute case {record.dispute_case_id}, not {case_id}"
                )
            assert_evidence_digest(record)
            if record.dispute_case_id != case_id:
                record = normalize_evidence_record(
                    record,
                    tenant_id=tenant_id,
                    dispute_case_id=case_id,
                    verify_digest=False,
                )
            normalized_records.append(record)

        if self._repo is not None:
            existing_records = self._repo.list_evidence(tenant_id, dispute_case_id=case_id)
            seen_ids = {r.id for r in existing_records}
            updated_evidence_ids = list(case.evidence_ids)
            seen_case_ids = set(updated_evidence_ids)
            attached_ids: list[str] = []
            for rec in normalized_records:
                if rec.id not in seen_ids:
                    self._repo.save_evidence(rec)
                    seen_ids.add(rec.id)
                if rec.id not in seen_case_ids:
                    updated_evidence_ids.append(rec.id)
                    seen_case_ids.add(rec.id)
                    attached_ids.append(str(rec.id))
            updated = case.model_copy(update={"evidence_ids": updated_evidence_ids, "updated_at": utc_now()})
            saved_case = self._repo.save_dispute_case(updated)
            if normalized_records:
                self._repo.append_financial_event(
                    tenant_id=tenant_id,
                    correlation_id=case.correlation_id,
                    payment_intent_id=case.payment_intent_id,
                    event_type=FinancialEventType.DISPUTE_EVIDENCE_ATTACHED,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    payload={
                        "dispute_case_id": str(case_id),
                        "attached_evidence_ids": attached_ids or [str(r.id) for r in normalized_records],
                        "total_evidence_count": len(updated_evidence_ids),
                    },
                )
            return saved_case

        existing_records = list(self._evidence.get(case_id, []))
        seen_ids = {record.id for record in existing_records}
        updated_evidence_ids = list(case.evidence_ids)
        seen_case_ids = set(updated_evidence_ids)

        for record in normalized_records:
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
        if case.status != DisputeStatus.DRAFT_READY:
            _assert_transition(case.status, DisputeStatus.DRAFT_READY)

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
        _assert_transition(case.status, DisputeStatus.APPROVED_FOR_SUBMISSION)
        cleaned_approver = approver_id.strip()
        if not cleaned_approver:
            raise ValueError("approver_id must not be empty")
        if not draft_response_text.strip():
            raise ValueError("draft_response_text must not be empty")

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
        actor_id: str = "disputeos",
        actor_type: str = "DISPUTEOS",
        external_status: str | None = None,
        submission_details: dict[str, Any] | None = None,
    ) -> DisputeCase:
        """Mark a dispute case as submitted only if human-approved, non-synthetic, and externally bound."""
        case = self.get_case(tenant_id, case_id)
        if case.status in (DisputeStatus.SUBMITTED, DisputeStatus.RESOLVED):
            _assert_transition(case.status, DisputeStatus.SUBMITTED)
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
        if not case.paypal_dispute_id or not case.paypal_dispute_id.strip():
            raise ValueError(
                f"Dispute case {case_id} requires paypal_dispute_id before transitioning to SUBMITTED"
            )

        _assert_transition(case.status, DisputeStatus.SUBMITTED)
        now = utc_now()
        updates: dict[str, Any] = {
            "status": DisputeStatus.SUBMITTED,
            "updated_at": now,
        }
        if external_status is not None:
            updates["external_status"] = external_status.strip()[:64] or None
        updated_case = case.model_copy(update=updates)

        if self._repo is not None:
            saved_case = self._repo.save_dispute_case(updated_case)
            payload: dict[str, Any] = {
                "dispute_case_id": str(case_id),
                "paypal_dispute_id": case.paypal_dispute_id,
                "approved_by": case.approved_by,
                "response_payload_hash": case.response_payload_hash,
                "external_status": saved_case.external_status,
            }
            if submission_details:
                payload["submission_details"] = submission_details
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                event_type=FinancialEventType.DISPUTE_SUBMITTED,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload,
            )
            return saved_case
        self._cases[case_id] = updated_case
        return updated_case

    def mark_resolved(
        self,
        *,
        tenant_id: UUID,
        case_id: UUID,
        resolution_outcome: str = "RESOLVED",
        actor_id: str = "disputeos",
        actor_type: str = "DISPUTEOS",
        external_status: str | None = None,
        notes: str | None = None,
    ) -> DisputeCase:
        """Transition a dispute case to RESOLVED with timestamp and hash-chained financial event."""
        case = self.get_case(tenant_id, case_id)
        _assert_transition(case.status, DisputeStatus.RESOLVED)

        cleaned_outcome = (resolution_outcome or "RESOLVED").strip() or "RESOLVED"
        now = utc_now()
        updates: dict[str, Any] = {
            "status": DisputeStatus.RESOLVED,
            "resolved_at": now,
            "resolution_outcome": cleaned_outcome[:64],
            "updated_at": now,
        }
        if external_status is not None:
            updates["external_status"] = external_status.strip()[:64] or None
        updated_case = case.model_copy(update=updates)

        if self._repo is not None:
            saved_case = self._repo.save_dispute_case(updated_case)
            payload: dict[str, Any] = {
                "dispute_case_id": str(case_id),
                "paypal_dispute_id": case.paypal_dispute_id,
                "resolution_outcome": cleaned_outcome,
                "resolved_at": now.isoformat(),
                "external_status": saved_case.external_status,
            }
            if notes:
                payload["notes"] = notes.strip()[:1000]
            self._repo.append_financial_event(
                tenant_id=tenant_id,
                correlation_id=case.correlation_id,
                payment_intent_id=case.payment_intent_id,
                event_type=FinancialEventType.DISPUTE_RESOLVED,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload,
            )
            return saved_case
        self._cases[case_id] = updated_case
        return updated_case
