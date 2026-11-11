"""Dispute evidence normalization and transaction bundle ingestion."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from contracts import (
    AuthorizationDecision,
    EvidenceRecord,
    EvidenceSourceType,
    PaymentAttempt,
    PaymentIntent,
    PurchaseProposal,
    QuoteSnapshot,
    compute_payload_hash,
)
from contracts.models import utc_now
from security import assert_same_tenant


def _compute_evidence_hash(
    *,
    source_type: EvidenceSourceType,
    source_ref: str,
    title: str,
    content: dict[str, Any],
) -> str:
    return compute_payload_hash({
        "source_type": source_type.value,
        "source_ref": source_ref,
        "title": title,
        "content": content,
    })


def _clean_text(value: str, field_name: str, max_length: int = 255) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned[:max_length]


def normalize_evidence_record(
    record: EvidenceRecord | dict[str, Any] | None = None,
    *,
    tenant_id: UUID | None = None,
    correlation_id: UUID | None = None,
    payment_intent_id: UUID | None = None,
    dispute_case_id: UUID | None = None,
    source_type: EvidenceSourceType | str | None = None,
    source_ref: str | None = None,
    title: str | None = None,
    content: dict[str, Any] | None = None,
    is_synthetic: bool | None = None,
    content_hash: str | None = None,
    collected_at: datetime | None = None,
    evidence_id: UUID | None = None,
) -> EvidenceRecord:
    """Normalize raw evidence inputs or an existing EvidenceRecord into a canonical record."""
    if isinstance(record, EvidenceRecord):
        if tenant_id is not None:
            assert_same_tenant(tenant_id, record.tenant_id, "evidence_record")
        effective_synthetic = (
            record.is_synthetic
            or bool(is_synthetic)
            or record.source_type == EvidenceSourceType.SYNTHETIC_FIXTURE
        )
        updates: dict[str, Any] = {}
        if payment_intent_id is not None and record.payment_intent_id is None:
            updates["payment_intent_id"] = payment_intent_id
        if dispute_case_id is not None and record.dispute_case_id is None:
            updates["dispute_case_id"] = dispute_case_id
        if effective_synthetic != record.is_synthetic:
            updates["is_synthetic"] = effective_synthetic
        return record.model_copy(update=updates) if updates else record

    raw: dict[str, Any] = dict(record) if isinstance(record, dict) else {}

    resolved_tenant_id = tenant_id if tenant_id is not None else raw.get("tenant_id")
    if resolved_tenant_id is None:
        raise ValueError("tenant_id is required to normalize an evidence record")
    if isinstance(resolved_tenant_id, str):
        resolved_tenant_id = UUID(resolved_tenant_id)
    if "tenant_id" in raw and tenant_id is not None:
        raw_tenant = raw["tenant_id"]
        if isinstance(raw_tenant, str):
            raw_tenant = UUID(raw_tenant)
        assert_same_tenant(tenant_id, raw_tenant, "evidence_record")

    resolved_correlation_id = correlation_id if correlation_id is not None else raw.get("correlation_id")
    if resolved_correlation_id is None:
        raise ValueError("correlation_id is required to normalize an evidence record")
    if isinstance(resolved_correlation_id, str):
        resolved_correlation_id = UUID(resolved_correlation_id)

    raw_source_type = source_type if source_type is not None else raw.get("source_type")
    if raw_source_type is None:
        raise ValueError("source_type is required to normalize an evidence record")
    resolved_source_type = (
        raw_source_type
        if isinstance(raw_source_type, EvidenceSourceType)
        else EvidenceSourceType(str(raw_source_type))
    )

    raw_source_ref = source_ref if source_ref is not None else raw.get("source_ref")
    if raw_source_ref is None:
        raise ValueError("source_ref is required to normalize an evidence record")
    resolved_source_ref = _clean_text(str(raw_source_ref), "source_ref")

    raw_title = title if title is not None else raw.get("title")
    if raw_title is None:
        raise ValueError("title is required to normalize an evidence record")
    resolved_title = _clean_text(str(raw_title), "title")

    resolved_content = dict(content if content is not None else raw.get("content", {}))

    resolved_payment_intent_id = (
        payment_intent_id if payment_intent_id is not None else raw.get("payment_intent_id")
    )
    if isinstance(resolved_payment_intent_id, str):
        resolved_payment_intent_id = UUID(resolved_payment_intent_id)

    resolved_dispute_case_id = (
        dispute_case_id if dispute_case_id is not None else raw.get("dispute_case_id")
    )
    if isinstance(resolved_dispute_case_id, str):
        resolved_dispute_case_id = UUID(resolved_dispute_case_id)

    resolved_id = evidence_id if evidence_id is not None else raw.get("id")
    if isinstance(resolved_id, str):
        resolved_id = UUID(resolved_id)

    resolved_synthetic = (
        bool(is_synthetic if is_synthetic is not None else raw.get("is_synthetic", False))
        or resolved_source_type == EvidenceSourceType.SYNTHETIC_FIXTURE
    )

    resolved_hash = content_hash or raw.get("content_hash")
    if not resolved_hash:
        resolved_hash = _compute_evidence_hash(
            source_type=resolved_source_type,
            source_ref=resolved_source_ref,
            title=resolved_title,
            content=resolved_content,
        )

    resolved_collected_at = collected_at or raw.get("collected_at") or utc_now()

    return EvidenceRecord(
        id=resolved_id or uuid4(),
        tenant_id=resolved_tenant_id,
        correlation_id=resolved_correlation_id,
        payment_intent_id=resolved_payment_intent_id,
        dispute_case_id=resolved_dispute_case_id,
        source_type=resolved_source_type,
        source_ref=resolved_source_ref,
        title=resolved_title,
        content=resolved_content,
        content_hash=resolved_hash,
        is_synthetic=resolved_synthetic,
        collected_at=resolved_collected_at,
    )


class DocumentIngestionService:
    """Ingests structured documents and transaction bundles into normalized EvidenceRecords."""

    def ingest_document(
        self,
        *,
        tenant_id: UUID,
        correlation_id: UUID,
        payment_intent_id: UUID | None = None,
        dispute_case_id: UUID | None = None,
        source_type: EvidenceSourceType,
        source_ref: str,
        title: str,
        content: dict[str, Any],
        is_synthetic: bool = False,
    ) -> EvidenceRecord:
        """Normalize a single document payload into an EvidenceRecord with a canonical hash."""
        cleaned_ref = _clean_text(source_ref, "source_ref")
        cleaned_title = _clean_text(title, "title")
        normalized_content = dict(content)
        content_hash = _compute_evidence_hash(
            source_type=source_type,
            source_ref=cleaned_ref,
            title=cleaned_title,
            content=normalized_content,
        )
        return normalize_evidence_record(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payment_intent_id=payment_intent_id,
            dispute_case_id=dispute_case_id,
            source_type=source_type,
            source_ref=cleaned_ref,
            title=cleaned_title,
            content=normalized_content,
            content_hash=content_hash,
            is_synthetic=is_synthetic,
        )

    def ingest_transaction_bundle(
        self,
        *,
        tenant_id: UUID,
        payment_intent: PaymentIntent,
        proposal: PurchaseProposal | None = None,
        quote: QuoteSnapshot | None = None,
        decision: AuthorizationDecision | None = None,
        attempt: PaymentAttempt | None = None,
        existing_evidence: list[EvidenceRecord] | None = None,
        dispute_case_id: UUID | None = None,
        is_synthetic: bool = False,
    ) -> list[EvidenceRecord]:
        """Validate tenant boundaries across all transaction artifacts and normalize into EvidenceRecords."""
        assert_same_tenant(tenant_id, payment_intent.tenant_id, "payment_intent")
        if proposal is not None:
            assert_same_tenant(tenant_id, proposal.tenant_id, "proposal")
        if quote is not None:
            assert_same_tenant(tenant_id, quote.tenant_id, "quote_snapshot")
        if decision is not None:
            assert_same_tenant(tenant_id, decision.tenant_id, "authorization_decision")
        if attempt is not None:
            assert_same_tenant(tenant_id, attempt.tenant_id, "payment_attempt")
        if existing_evidence:
            for record in existing_evidence:
                assert_same_tenant(tenant_id, record.tenant_id, "evidence_record")

        records: list[EvidenceRecord] = []
        seen_keys: set[tuple[EvidenceSourceType, str]] = set()
        seen_ids: set[UUID] = set()

        def _append_if_new(record: EvidenceRecord) -> None:
            key = (record.source_type, record.source_ref)
            if record.id in seen_ids or key in seen_keys:
                return
            seen_ids.add(record.id)
            seen_keys.add(key)
            records.append(record)

        if existing_evidence:
            for record in existing_evidence:
                normalized = normalize_evidence_record(
                    record,
                    tenant_id=tenant_id,
                    payment_intent_id=payment_intent.id,
                    dispute_case_id=dispute_case_id,
                    is_synthetic=is_synthetic,
                )
                _append_if_new(normalized)

        correlation_id = payment_intent.correlation_id

        if proposal is not None:
            _append_if_new(
                self.ingest_document(
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                    payment_intent_id=payment_intent.id,
                    dispute_case_id=dispute_case_id,
                    source_type=EvidenceSourceType.PROPOSAL,
                    source_ref=f"proposal:{proposal.id}",
                    title=f"Purchase Proposal: {proposal.item_summary}",
                    content={
                        "proposal_id": str(proposal.id),
                        "agent_id": str(proposal.agent_id),
                        "passport_id": str(proposal.passport_id),
                        "merchant_id": str(proposal.merchant_id),
                        "merchant_name": proposal.merchant_name,
                        "merchant_category": proposal.merchant_category,
                        "amount_minor": proposal.amount_minor,
                        "currency": proposal.currency,
                        "item_summary": proposal.item_summary,
                        "line_items": proposal.line_items,
                        "rationale": proposal.rationale,
                        "proposed_by_model": proposal.proposed_by_model,
                    },
                    is_synthetic=is_synthetic,
                )
            )

        if quote is not None:
            _append_if_new(
                self.ingest_document(
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                    payment_intent_id=payment_intent.id,
                    dispute_case_id=dispute_case_id,
                    source_type=EvidenceSourceType.QUOTE,
                    source_ref=f"quote:{quote.id}",
                    title=f"Bound Quote Snapshot ({quote.amount_minor} {quote.currency})",
                    content={
                        "quote_snapshot_id": str(quote.id),
                        "proposal_id": str(quote.proposal_id),
                        "merchant_id": str(quote.merchant_id),
                        "amount_minor": quote.amount_minor,
                        "currency": quote.currency,
                        "line_items": quote.line_items,
                        "quote_hash": quote.quote_hash,
                        "expires_at": quote.expires_at.isoformat(),
                    },
                    is_synthetic=is_synthetic,
                )
            )

        if decision is not None:
            _append_if_new(
                self.ingest_document(
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                    payment_intent_id=payment_intent.id,
                    dispute_case_id=dispute_case_id,
                    source_type=EvidenceSourceType.POLICY_DECISION,
                    source_ref=f"decision:{decision.id}",
                    title=f"Authorization Decision ({decision.outcome.value})",
                    content={
                        "decision_id": str(decision.id),
                        "payment_intent_id": str(decision.payment_intent_id),
                        "proposal_id": str(decision.proposal_id),
                        "passport_id": str(decision.passport_id),
                        "quote_snapshot_id": str(decision.quote_snapshot_id),
                        "quote_hash": decision.quote_hash,
                        "policy_version": decision.policy_version,
                        "outcome": decision.outcome.value,
                        "reason_codes": [code.value for code in decision.reason_codes],
                        "violated_constraints": list(decision.violated_constraints),
                        "requires_human_approval": decision.requires_human_approval,
                        "explanation": decision.explanation,
                        "policy_inputs": dict(decision.policy_inputs),
                        "decided_at": decision.decided_at.isoformat(),
                    },
                    is_synthetic=is_synthetic,
                )
            )

        if attempt is not None:
            order_ref = f"paypal:{attempt.paypal_order_id}" if attempt.paypal_order_id else f"attempt:{attempt.id}"
            _append_if_new(
                self.ingest_document(
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                    payment_intent_id=payment_intent.id,
                    dispute_case_id=dispute_case_id,
                    source_type=EvidenceSourceType.PAYPAL_ORDER,
                    source_ref=order_ref,
                    title=f"PayPal Order Attempt ({attempt.state.value})",
                    content={
                        "attempt_id": str(attempt.id),
                        "payment_intent_id": str(attempt.payment_intent_id),
                        "provider": attempt.provider,
                        "paypal_order_id": attempt.paypal_order_id,
                        "state": attempt.state.value,
                        "buyer_approval": (
                            attempt.buyer_approval.model_dump(mode="json")
                            if attempt.buyer_approval is not None
                            else None
                        ),
                        "failure_code": attempt.failure_code,
                        "failure_reason": attempt.failure_reason,
                    },
                    is_synthetic=is_synthetic,
                )
            )

            if attempt.verified_capture is not None:
                capture = attempt.verified_capture
                _append_if_new(
                    self.ingest_document(
                        tenant_id=tenant_id,
                        correlation_id=correlation_id,
                        payment_intent_id=payment_intent.id,
                        dispute_case_id=dispute_case_id,
                        source_type=EvidenceSourceType.PAYPAL_CAPTURE,
                        source_ref=f"paypal:{capture.paypal_capture_id}",
                        title=f"Verified PayPal Capture ({capture.paypal_status})",
                        content={
                            "paypal_order_id": capture.paypal_order_id,
                            "capture_id": capture.paypal_capture_id,
                            "paypal_capture_id": capture.paypal_capture_id,
                            "status": capture.paypal_status,
                            "verified_amount_minor": capture.verified_amount_minor,
                            "verified_currency": capture.verified_currency,
                            "verification_hash": capture.verification_hash,
                            "verified_at": capture.verified_at.isoformat(),
                        },
                        is_synthetic=is_synthetic,
                    )
                )

        return records
