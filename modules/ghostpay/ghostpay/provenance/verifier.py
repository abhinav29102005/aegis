"""Evidence completeness, provenance, and hash-chain integrity verification."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from ghostpay.domain.models import PaymentTrace


@dataclass
class ProvenanceNode:
    node_id: str
    node_type: str  # "MANDATE", "PROPOSAL", "QUOTE", "DECISION", "APPROVAL", "RESERVATION", "PAYPAL_ORDER", "CAPTURE"
    properties: dict = field(default_factory=dict)


@dataclass
class ProvenanceEdge:
    source_id: str
    target_id: str
    relationship: str  # "GENERATED", "BOUND_TO", "EVALUATED_AGAINST", "AUTHORIZED_BY", "CAPTURED_BY"
    is_inferred: bool = False


@dataclass
class ProvenanceGraph:
    nodes: dict[str, ProvenanceNode] = field(default_factory=dict)
    edges: list[ProvenanceEdge] = field(default_factory=list)

    def add_node(self, node_id: str, node_type: str, properties: dict | None = None) -> None:
        self.nodes[node_id] = ProvenanceNode(node_id, node_type, properties or {})

    def add_edge(self, source_id: str, target_id: str, relationship: str, is_inferred: bool = False) -> None:
        self.edges.append(ProvenanceEdge(source_id, target_id, relationship, is_inferred))


def build_provenance_graph(trace: PaymentTrace) -> ProvenanceGraph:
    """Build a lightweight directed provenance graph representing trace relationships."""
    graph = ProvenanceGraph()

    # Intent node
    intent_id = str(trace.payment_intent_id)
    graph.add_node(intent_id, "PAYMENT_INTENT", {"state": trace.payment_intent.state if trace.payment_intent else "UNKNOWN"})

    # Passport node
    if trace.recorded_passport:
        passport_id = str(trace.recorded_passport.id)
        graph.add_node(passport_id, "SPENDING_PASSPORT", {"status": trace.recorded_passport.status.value})
        graph.add_edge(passport_id, intent_id, "GOVERNS")

    # Quote node
    if trace.quote_snapshot:
        quote_id = str(trace.quote_snapshot.id)
        graph.add_node(quote_id, "QUOTE", {"quote_hash": trace.quote_snapshot.quote_hash, "amount_minor": trace.quote_snapshot.amount_minor})
        graph.add_edge(quote_id, intent_id, "BOUND_TO")

    # Decision node
    if trace.recorded_decision:
        decision_id = str(trace.recorded_decision.id)
        graph.add_node(decision_id, "POLICY_DECISION", {"outcome": trace.recorded_decision.outcome.value})
        graph.add_edge(decision_id, intent_id, "EVALUATED_FOR")

    # Events
    prev_ev_id: str | None = None
    for ev in trace.ordered_events:
        ev_id = str(ev.id)
        graph.add_node(ev_id, "FINANCIAL_EVENT", {"type": ev.event_type.value, "seq": ev.sequence_number})
        graph.add_edge(ev_id, intent_id, "RECORDS")
        if prev_ev_id:
            graph.add_edge(prev_ev_id, ev_id, "CHAINED_TO")
        prev_ev_id = ev_id

    return graph


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

    # 3. Canonical fixture & artifact hashes (contracts/fixtures.py compatibility)
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

    # Step 2: Verify financial event hash chain and correlation binding
    chain_ok, chain_errors = verify_financial_event_chain(request.events)
    if not chain_ok:
        errors.extend(chain_errors)
    for ev in request.events:
        if ev.correlation_id != request.correlation_id:
            errors.append(
                f"Correlation mismatch on FinancialEvent {ev.id}: "
                f"expected {request.correlation_id}, got {ev.correlation_id}"
            )

    # Step 3: Verify quote snapshot binding hash
    quote_ok, quote_err = verify_quote_snapshot_integrity(request.quote_snapshot)
    if not quote_ok and quote_err:
        errors.append(quote_err)

    # Step 4: Verify each evidence record digest, tenancy, and correlation binding
    for ev in request.evidence_records:
        if ev.tenant_id != request.tenant_id:
            errors.append(
                f"Tenant mismatch on EvidenceRecord {ev.id}: "
                f"expected {request.tenant_id}, got {ev.tenant_id}"
            )
        if ev.correlation_id != request.correlation_id:
            errors.append(
                f"Correlation mismatch on EvidenceRecord {ev.id}: "
                f"expected {request.correlation_id}, got {ev.correlation_id}"
            )
        ev_ok, ev_err = verify_evidence_digest(ev)
        if not ev_ok and ev_err:
            errors.append(ev_err)

    # Step 5: Check missing evidence
    missing = check_missing_evidence(request)

    integrity_valid = (len(errors) == 0)
    return integrity_valid, missing, errors
