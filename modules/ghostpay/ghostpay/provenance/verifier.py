"""Evidence completeness, provenance, and hash-chain integrity verification."""

from __future__ import annotations

import hmac

from contracts import (
    EvidenceRecord,
    EvidenceSourceType,
    PaymentState,
    QuoteSnapshot,
    ReplayRequest,
    compute_payload_hash,
    compute_quote_hash,
)
from security import (
    assert_same_tenant,
    verify_financial_event_chain,
)


def verify_evidence_digest(ev: EvidenceRecord) -> tuple[bool, str | None]:
    """Verify evidence record digest against canonical content-hash computations."""
    if not ev.content_hash:
        return False, f"Missing content_hash on EvidenceRecord {ev.id}"

    # 1. Plain content hash
    direct_hash = compute_payload_hash(ev.content)
    if hmac.compare_digest(direct_hash, ev.content_hash):
        return True, None

    # 2. Normalized metadata envelope hash (from DocumentIngestionService)
    envelope_hash = compute_payload_hash(
        {
            "source_type": ev.source_type.value,
            "source_ref": ev.source_ref,
            "title": ev.title,
            "content": ev.content,
        }
    )
    if hmac.compare_digest(envelope_hash, ev.content_hash):
        return True, None

    return False, (
        f"Tampered content_hash on EvidenceRecord {ev.id}: "
        f"digest {ev.content_hash} does not match verified payload."
    )


def verify_quote_snapshot_integrity(quote: QuoteSnapshot) -> tuple[bool, str | None]:
    """Verify QuoteSnapshot binding hash matches its deterministic parameters."""
    recomputed = compute_quote_hash(
        merchant_id=quote.merchant_id,
        amount_minor=quote.amount_minor,
        currency=quote.currency,
        line_items=quote.line_items,
    )
    if not hmac.compare_digest(recomputed, quote.quote_hash):
        return False, (
            f"Tampered quote_hash on QuoteSnapshot {quote.id}: "
            f"recomputed {recomputed} != stored {quote.quote_hash}"
        )
    return True, None


def check_missing_evidence(request: ReplayRequest) -> list[str]:
    """Detect missing required transaction artifacts without fabricating missing evidence."""
    missing: list[str] = []
    present_types = {
        e.source_type
        for e in request.evidence_records
        if e.payment_intent_id == request.payment_intent.id
        and e.correlation_id == request.correlation_id
    }

    # 1. QUOTE artifact: must be in evidence_records
    if EvidenceSourceType.QUOTE not in present_types:
        missing.append("QUOTE")

    # 2. POLICY_DECISION artifact: satisfied by dedicated recorded_decision contract or evidence record
    has_decision = (
        EvidenceSourceType.POLICY_DECISION in present_types
        or request.recorded_decision is not None
    )
    if not has_decision:
        missing.append("POLICY_DECISION")

    # 3. PAYPAL_CAPTURE artifact: required when payment intent succeeded
    if (
        request.payment_intent.state == PaymentState.SUCCEEDED
        and EvidenceSourceType.PAYPAL_CAPTURE not in present_types
    ):
        missing.append("PAYPAL_CAPTURE")

    return missing


def enforce_request_tenancy(request: ReplayRequest) -> None:
    """Enforce strict tenant isolation across all entities inside ReplayRequest."""
    expected = request.tenant_id

    assert_same_tenant(expected, request.payment_intent.tenant_id, "payment_intent")
    assert_same_tenant(expected, request.proposal.tenant_id, "proposal")
    assert_same_tenant(expected, request.quote_snapshot.tenant_id, "quote_snapshot")
    assert_same_tenant(
        expected, request.recorded_passport.tenant_id, "recorded_passport"
    )
    assert_same_tenant(
        expected, request.recorded_merchant.tenant_id, "recorded_merchant"
    )

    if request.recorded_decision is not None:
        assert_same_tenant(
            expected, request.recorded_decision.tenant_id, "recorded_decision"
        )
    if request.approval_record is not None:
        assert_same_tenant(
            expected, request.approval_record.tenant_id, "approval_record"
        )

    for ev in request.events:
        assert_same_tenant(expected, ev.tenant_id, f"financial_event_{ev.id}")

    for rec in request.evidence_records:
        assert_same_tenant(expected, rec.tenant_id, f"evidence_record_{rec.id}")


def verify_provenance_and_integrity(
    request: ReplayRequest,
    *,
    hypothetical: bool = False,
) -> tuple[bool, list[str], list[str]]:
    """Perform comprehensive provenance, hash-chain, and evidence completeness verification."""
    # Step 1: Enforce tenancy (raises TenantIsolationError on mismatch)
    enforce_request_tenancy(request)

    errors = verify_record_bindings(request, hypothetical=hypothetical)
    if request.events:
        ordered = sorted(request.events, key=lambda event: event.sequence_number)
        if [event.sequence_number for event in ordered] != list(
            range(1, len(ordered) + 1)
        ):
            errors.append("Event chain must be complete and contiguous from sequence 1")

    # Step 2: Verify financial event hash chain
    chain_ok, chain_errors = verify_financial_event_chain(request.events)
    if not chain_ok:
        errors.extend(chain_errors)

    # Step 3: Verify quote snapshot binding hash
    quote_ok, quote_err = verify_quote_snapshot_integrity(request.quote_snapshot)
    if not quote_ok and quote_err:
        errors.append(quote_err)

    # Step 4: Verify each evidence record digest
    for ev in request.evidence_records:
        ev_ok, ev_err = verify_evidence_digest(ev)
        if not ev_ok and ev_err:
            errors.append(ev_err)

    # Step 5: Check missing evidence
    missing = check_missing_evidence(request)
    if not request.events:
        missing.append("FINANCIAL_EVENTS")

    integrity_valid = len(errors) == 0
    return integrity_valid, missing, errors


def verify_record_bindings(
    request: ReplayRequest, *, hypothetical: bool = False
) -> list[str]:
    """Check record identity independently from hypothetical policy/amount changes."""
    errors: list[str] = []
    intent = request.payment_intent
    decision = request.recorded_decision
    checks = [
        (intent.correlation_id, request.correlation_id, "intent correlation"),
        (intent.proposal_id, request.proposal.id, "intent proposal"),
        (intent.passport_id, request.recorded_passport.id, "intent passport"),
        (intent.quote_snapshot_id, request.quote_snapshot.id, "intent quote"),
        (intent.agent_id, request.proposal.agent_id, "intent agent"),
        (
            request.proposal.passport_id,
            request.recorded_passport.id,
            "proposal passport",
        ),
        (
            request.recorded_passport.agent_id,
            request.proposal.agent_id,
            "passport agent",
        ),
        (
            request.proposal.correlation_id,
            request.correlation_id,
            "proposal correlation",
        ),
        (
            request.quote_snapshot.correlation_id,
            request.correlation_id,
            "quote correlation",
        ),
        (request.quote_snapshot.proposal_id, request.proposal.id, "quote proposal"),
        (decision.payment_intent_id, intent.id, "decision payment"),
        (decision.correlation_id, request.correlation_id, "decision correlation"),
        (decision.proposal_id, request.proposal.id, "decision proposal"),
        (decision.passport_id, request.recorded_passport.id, "decision passport"),
        (decision.quote_snapshot_id, request.quote_snapshot.id, "decision quote"),
    ]
    if not hypothetical:
        checks.extend(
            [
                (intent.merchant_id, request.recorded_merchant.id, "intent merchant"),
                (request.proposal.merchant_id, intent.merchant_id, "proposal merchant"),
                (
                    request.quote_snapshot.merchant_id,
                    intent.merchant_id,
                    "quote merchant",
                ),
                (request.proposal.amount_minor, intent.amount_minor, "proposal amount"),
                (
                    request.quote_snapshot.amount_minor,
                    intent.amount_minor,
                    "quote amount",
                ),
                (request.proposal.currency, intent.currency, "proposal currency"),
                (request.quote_snapshot.currency, intent.currency, "quote currency"),
                (
                    request.quote_snapshot.quote_hash,
                    intent.quote_hash,
                    "intent quote hash",
                ),
                (decision.quote_hash, intent.quote_hash, "decision quote hash"),
            ]
        )
        for evidence in request.evidence_records:
            if evidence.source_type == EvidenceSourceType.QUOTE:
                for field, expected in (
                    ("quote_hash", intent.quote_hash),
                    ("amount_minor", intent.amount_minor),
                    ("merchant_id", str(intent.merchant_id)),
                ):
                    checks.append(
                        (
                            evidence.content.get(field),
                            expected,
                            f"quote evidence {field}",
                        )
                    )
    if intent.authorization_decision_id is not None:
        checks.append(
            (intent.authorization_decision_id, decision.id, "intent decision")
        )
    approval = request.approval_record
    if approval is not None:
        checks.extend(
            [
                (approval.payment_intent_id, intent.id, "approval payment"),
                (approval.decision_id, decision.id, "approval decision"),
                (
                    approval.correlation_id,
                    request.correlation_id,
                    "approval correlation",
                ),
                (approval.bound_currency, intent.currency, "approval currency"),
                (approval.bound_merchant_id, intent.merchant_id, "approval merchant"),
                (approval.bound_amount_minor, intent.amount_minor, "approval amount"),
                (approval.bound_quote_hash, intent.quote_hash, "approval quote"),
            ]
        )
    for record in [*request.events, *request.evidence_records]:
        checks.extend(
            [
                (record.payment_intent_id, intent.id, f"record {record.id} payment"),
                (
                    record.correlation_id,
                    request.correlation_id,
                    f"record {record.id} correlation",
                ),
            ]
        )
    for actual, expected, label in checks:
        if actual != expected:
            errors.append(f"Record binding mismatch: {label}")
    for evidence in request.evidence_records:
        if evidence.source_type == EvidenceSourceType.PAYPAL_CAPTURE and (
            evidence.content.get("status") != "COMPLETED"
            or not evidence.content.get("capture_id")
        ):
            errors.append("Capture evidence is missing a completed capture reference")
    if len({e.id for e in request.events}) != len(request.events):
        errors.append("Duplicate financial event IDs")
    if len({e.id for e in request.evidence_records}) != len(request.evidence_records):
        errors.append("Duplicate evidence IDs")
    return errors
