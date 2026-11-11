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
    envelope_hash = compute_payload_hash({
        "source_type": ev.source_type.value,
        "source_ref": ev.source_ref,
        "title": ev.title,
        "content": ev.content,
    })
    if hmac.compare_digest(envelope_hash, ev.content_hash):
        return True, None

    # 3. Canonical fixture & artifact hashes
    content = ev.content or {}
    if ev.source_type == EvidenceSourceType.QUOTE:
        if "quote_hash" in content and "amount_minor" in content:
            h = compute_payload_hash({"quote_hash": content["quote_hash"], "amount_minor": content["amount_minor"]})
            if hmac.compare_digest(h, ev.content_hash):
                return True, None
    elif ev.source_type == EvidenceSourceType.PAYPAL_CAPTURE:
        if "capture_id" in content and "status" in content:
            h = compute_payload_hash({"capture_id": content["capture_id"], "status": content["status"]})
            if hmac.compare_digest(h, ev.content_hash):
                return True, None
    elif ev.source_type == EvidenceSourceType.CARRIER_TRACKING:
        if "tracking_number" in content and "status" in content:
            h = compute_payload_hash({"tracking_number": content["tracking_number"], "status": content["status"]})
            if hmac.compare_digest(h, ev.content_hash):
                return True, None
    elif (
        ev.source_type == EvidenceSourceType.CUSTOMER_MESSAGE
        and "msg_id" in content
        and "status" in content
    ):
        h = compute_payload_hash({"msg_id": content["msg_id"], "status": content["status"]})
        if hmac.compare_digest(h, ev.content_hash):
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
    present_types = {e.source_type for e in request.evidence_records}

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
    assert_same_tenant(expected, request.recorded_passport.tenant_id, "recorded_passport")
    assert_same_tenant(expected, request.recorded_merchant.tenant_id, "recorded_merchant")

    if request.recorded_decision is not None:
        assert_same_tenant(expected, request.recorded_decision.tenant_id, "recorded_decision")
    if request.approval_record is not None:
        assert_same_tenant(expected, request.approval_record.tenant_id, "approval_record")

    for ev in request.events:
        assert_same_tenant(expected, ev.tenant_id, f"financial_event_{ev.id}")

    for rec in request.evidence_records:
        assert_same_tenant(expected, rec.tenant_id, f"evidence_record_{rec.id}")


def verify_provenance_and_integrity(
    request: ReplayRequest,
) -> tuple[bool, list[str], list[str]]:
    """Perform comprehensive provenance, hash-chain, and evidence completeness verification."""
    # Step 1: Enforce tenancy (raises TenantIsolationError on mismatch)
    enforce_request_tenancy(request)

    errors: list[str] = []

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

    integrity_valid = (len(errors) == 0)
    return integrity_valid, missing, errors
