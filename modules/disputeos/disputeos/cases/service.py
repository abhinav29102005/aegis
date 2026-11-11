"""Tenant-scoped dispute case management with fail-closed human approval gates."""

from __future__ import annotations

from uuid import UUID, uuid4

from contracts import (
    DisputeAnalysis,
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    EvidenceRecord,
    compute_payload_hash,
)
from contracts.models import utc_now
from security import assert_same_tenant


class CaseNotFoundError(KeyError):
    """Raised when a requested dispute case does not exist."""


class ApprovalGateError(PermissionError):
    """Raised when external submission is attempted without explicit human approval."""


class SyntheticSubmissionError(PermissionError):
    """Raised when external submission is attempted for a synthetic demo case."""


class DisputeCaseService:
    """In-memory tenant-isolated dispute case lifecycle and approval gate service."""

    def __init__(self) -> None:
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
    ) -> DisputeCase:
        """Create a tenant-scoped dispute case and link any validated evidence records."""
        resolved_case_id = case_id or uuid4()
        if resolved_case_id in self._cases:
            raise ValueError(f"Dispute case {resolved_case_id} already exists")

        validated_records: list[EvidenceRecord] = []
        seen_evidence_ids: set[UUID] = set()
        evidence_ids: list[UUID] = []

        if evidence_records:
            for record in evidence_records:
                assert_same_tenant(tenant_id, record.tenant_id, "evidence_record")
                if record.id not in seen_evidence_ids:
                    seen_evidence_ids.add(record.id)
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
            opened_at=now,
            updated_at=now,
        )
        self._cases[case.id] = case
        self._evidence[case.id] = validated_records
        self._analyses[case.id] = []
        return case

    def get_case(self, tenant_id: UUID, case_id: UUID) -> DisputeCase:
        """Retrieve a dispute case after enforcing strict tenant isolation."""
        case = self._cases.get(case_id)
        if case is None:
            raise CaseNotFoundError(f"Dispute case {case_id} not found")
        assert_same_tenant(tenant_id, case.tenant_id, "dispute_case")
        return case

    def list_cases(self, tenant_id: UUID) -> list[DisputeCase]:
        """List all dispute cases belonging to the specified tenant."""
        return [case for case in self._cases.values() if case.tenant_id == tenant_id]

    def attach_evidence(
        self,
        tenant_id: UUID,
        case_id: UUID,
        records: list[EvidenceRecord],
    ) -> DisputeCase:
        """Attach tenant-validated evidence records to an existing dispute case."""
        case = self.get_case(tenant_id, case_id)
        for record in records:
            assert_same_tenant(tenant_id, record.tenant_id, "evidence_record")

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
        self.get_case(tenant_id, case_id)
        return list(self._evidence.get(case_id, []))

    def record_analysis(
        self,
        tenant_id: UUID,
        case_id: UUID,
        analysis: DisputeAnalysis,
    ) -> DisputeCase:
        """Store a DisputeAnalysis for a case and transition status to DRAFT_READY."""
        case = self.get_case(tenant_id, case_id)
        assert_same_tenant(tenant_id, analysis.tenant_id, "dispute_analysis")
        if analysis.dispute_case_id != case_id:
            raise ValueError(
                f"DisputeAnalysis dispute_case_id {analysis.dispute_case_id} does not match case {case_id}"
            )

        self._analyses.setdefault(case_id, []).append(analysis)
        updated_case = case.model_copy(
            update={
                "status": DisputeStatus.DRAFT_READY,
                "updated_at": utc_now(),
            }
        )
        self._cases[case_id] = updated_case
        return updated_case

    def get_latest_analysis(
        self,
        tenant_id: UUID,
        case_id: UUID,
    ) -> DisputeAnalysis | None:
        """Return the most recent DisputeAnalysis for a tenant-owned dispute case."""
        self.get_case(tenant_id, case_id)
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

        updated_case = case.model_copy(
            update={
                "status": DisputeStatus.SUBMITTED,
                "updated_at": utc_now(),
            }
        )
        self._cases[case_id] = updated_case
        return updated_case
