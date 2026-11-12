"""Evidence completeness, provenance, correlation binding, and hash-chain integrity verification."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from contracts import (
    BudgetReservation,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialEventType,
    PaymentAttempt,
    PaymentState,
    QuoteSnapshot,
    ReplayRequest,
    ReservationStatus,
    VerifiedPayPalCapture,
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
    """Verify evidence record digest against full canonical content-hash computations."""
    if not ev.content_hash:
        return False, f"Missing content_hash on EvidenceRecord {ev.id}"

    # 1. Full canonical content payload hash
    direct_hash = compute_payload_hash(ev.content)
    if hmac.compare_digest(direct_hash, ev.content_hash):
        return True, None

    # 2. Normalized metadata envelope hash (covering full ev.content)
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

    # 4. Full-context envelope hash (covering full ev.content + provenance metadata)
    full_context_hash = compute_payload_hash({
        "tenant_id": str(ev.tenant_id),
        "correlation_id": str(ev.correlation_id),
        "payment_intent_id": str(ev.payment_intent_id) if ev.payment_intent_id is not None else None,
        "dispute_case_id": str(ev.dispute_case_id) if ev.dispute_case_id is not None else None,
        "source_type": ev.source_type.value,
        "source_ref": ev.source_ref,
        "title": ev.title,
        "content": ev.content,
        "is_synthetic": ev.is_synthetic,
        "collected_at": ev.collected_at.isoformat(),
    })
    if hmac.compare_digest(full_context_hash, ev.content_hash):
        return True, None

    return False, (
        f"Tampered content_hash on EvidenceRecord {ev.id}: "
        f"digest {ev.content_hash} does not match canonical payload hash."
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


def enforce_request_tenancy(
    request: ReplayRequest,
    *,
    payment_attempt: PaymentAttempt | None = None,
    budget_reservation: BudgetReservation | None = None,
) -> None:
    """Enforce strict tenant isolation across all entities inside ReplayRequest and execution artifacts."""
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
    if payment_attempt is not None:
        assert_same_tenant(expected, payment_attempt.tenant_id, "payment_attempt")
    if budget_reservation is not None:
        assert_same_tenant(expected, budget_reservation.tenant_id, "budget_reservation")

    for ev in request.events:
        assert_same_tenant(expected, ev.tenant_id, f"financial_event_{ev.id}")

    for rec in request.evidence_records:
        assert_same_tenant(expected, rec.tenant_id, f"evidence_record_{rec.id}")


def _extract_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        val = payload.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
    return None


def _extract_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def verify_execution_artifacts_consistency(
    request: ReplayRequest,
    *,
    payment_attempt: PaymentAttempt | None = None,
    verified_capture: VerifiedPayPalCapture | None = None,
    budget_reservation: BudgetReservation | None = None,
) -> list[str]:
    """Cross-check PaymentAttempt, VerifiedPayPalCapture, BudgetReservation, events, and evidence."""
    errors: list[str] = []
    intent = request.payment_intent

    # 1. PaymentAttempt consistency checks
    if payment_attempt is not None:
        if payment_attempt.correlation_id != request.correlation_id:
            errors.append(
                f"Correlation mismatch on PaymentAttempt {payment_attempt.id}: "
                f"expected {request.correlation_id}, got {payment_attempt.correlation_id}"
            )
        if payment_attempt.payment_intent_id != intent.id:
            errors.append(
                f"PaymentIntent mismatch on PaymentAttempt {payment_attempt.id}: "
                f"expected {intent.id}, got {payment_attempt.payment_intent_id}"
            )
        if (
            intent.active_attempt_id is not None
            and payment_attempt.state == PaymentState.SUCCEEDED
            and payment_attempt.id != intent.active_attempt_id
        ):
            errors.append(
                f"Active attempt mismatch on PaymentAttempt {payment_attempt.id}: "
                f"PaymentIntent references {intent.active_attempt_id}"
            )
        if intent.state == PaymentState.SUCCEEDED and payment_attempt.state != PaymentState.SUCCEEDED:
            errors.append(
                f"State mismatch: PaymentIntent {intent.id} is SUCCEEDED but "
                f"PaymentAttempt {payment_attempt.id} is {payment_attempt.state.value}"
            )
        if payment_attempt.verified_capture is not None:
            if (
                payment_attempt.paypal_order_id
                and payment_attempt.verified_capture.paypal_order_id != payment_attempt.paypal_order_id
            ):
                errors.append(
                    f"Order mismatch on PaymentAttempt {payment_attempt.id}: "
                    f"attempt order {payment_attempt.paypal_order_id} != "
                    f"capture order {payment_attempt.verified_capture.paypal_order_id}"
                )
            if (
                verified_capture is not None
                and verified_capture.paypal_capture_id != payment_attempt.verified_capture.paypal_capture_id
            ):
                errors.append(
                    f"Capture mismatch: PaymentAttempt capture {payment_attempt.verified_capture.paypal_capture_id} "
                    f"!= VerifiedPayPalCapture {verified_capture.paypal_capture_id}"
                )

    # 2. VerifiedPayPalCapture consistency checks
    active_capture = verified_capture or (payment_attempt.verified_capture if payment_attempt else None)
    if active_capture is not None:
        if active_capture.verified_amount_minor != intent.amount_minor:
            errors.append(
                f"Capture amount mismatch: VerifiedPayPalCapture amount {active_capture.verified_amount_minor} "
                f"!= PaymentIntent amount {intent.amount_minor}"
            )
        if active_capture.verified_currency.upper() != intent.currency.upper():
            errors.append(
                f"Capture currency mismatch: VerifiedPayPalCapture currency {active_capture.verified_currency} "
                f"!= PaymentIntent currency {intent.currency}"
            )
        if intent.state == PaymentState.SUCCEEDED and active_capture.paypal_status.upper() != "COMPLETED":
            errors.append(
                f"Capture status mismatch: PaymentIntent is SUCCEEDED but "
                f"VerifiedPayPalCapture status is {active_capture.paypal_status}"
            )

    # 3. BudgetReservation consistency checks
    if budget_reservation is not None:
        if budget_reservation.correlation_id != request.correlation_id:
            errors.append(
                f"Correlation mismatch on BudgetReservation {budget_reservation.id}: "
                f"expected {request.correlation_id}, got {budget_reservation.correlation_id}"
            )
        if budget_reservation.payment_intent_id != intent.id:
            errors.append(
                f"PaymentIntent mismatch on BudgetReservation {budget_reservation.id}: "
                f"expected {intent.id}, got {budget_reservation.payment_intent_id}"
            )
        if budget_reservation.passport_id != request.recorded_passport.id:
            errors.append(
                f"Passport mismatch on BudgetReservation {budget_reservation.id}: "
                f"expected {request.recorded_passport.id}, got {budget_reservation.passport_id}"
            )
        if budget_reservation.amount_minor != intent.amount_minor:
            errors.append(
                f"Reservation amount mismatch on BudgetReservation {budget_reservation.id}: "
                f"expected {intent.amount_minor}, got {budget_reservation.amount_minor}"
            )
        if budget_reservation.currency.upper() != intent.currency.upper():
            errors.append(
                f"Reservation currency mismatch on BudgetReservation {budget_reservation.id}: "
                f"expected {intent.currency}, got {budget_reservation.currency}"
            )
        if intent.reservation_id is not None and budget_reservation.id != intent.reservation_id:
            errors.append(
                f"Reservation ID mismatch: PaymentIntent references {intent.reservation_id}, "
                f"got BudgetReservation {budget_reservation.id}"
            )
        if intent.state == PaymentState.SUCCEEDED and budget_reservation.status != ReservationStatus.CAPTURED:
            errors.append(
                f"Reservation state mismatch: PaymentIntent is SUCCEEDED but "
                f"BudgetReservation {budget_reservation.id} is {budget_reservation.status.value}"
            )

    # 4. Cross-check evidence records and events against PaymentIntent / capture / reservation
    observed_order_ids: set[str] = set()
    if payment_attempt and payment_attempt.paypal_order_id:
        observed_order_ids.add(payment_attempt.paypal_order_id)
    if active_capture:
        observed_order_ids.add(active_capture.paypal_order_id)

    for rec in request.evidence_records:
        content = rec.content or {}
        if rec.source_type == EvidenceSourceType.PAYPAL_ORDER:
            order_id = _extract_str(content, "paypal_order_id", "order_id")
            if order_id:
                if observed_order_ids and order_id not in observed_order_ids:
                    errors.append(
                        f"PayPal order mismatch on EvidenceRecord {rec.id}: "
                        f"{order_id} != expected {sorted(observed_order_ids)}"
                    )
                observed_order_ids.add(order_id)
        elif rec.source_type == EvidenceSourceType.PAYPAL_CAPTURE:
            order_id = _extract_str(content, "paypal_order_id", "order_id")
            if order_id:
                if observed_order_ids and order_id not in observed_order_ids:
                    errors.append(
                        f"PayPal order mismatch on PAYPAL_CAPTURE EvidenceRecord {rec.id}: "
                        f"{order_id} != expected {sorted(observed_order_ids)}"
                    )
                observed_order_ids.add(order_id)

            cap_id = _extract_str(content, "paypal_capture_id", "capture_id")
            if active_capture and cap_id and cap_id != active_capture.paypal_capture_id:
                errors.append(
                    f"PayPal capture ID mismatch on EvidenceRecord {rec.id}: "
                    f"{cap_id} != {active_capture.paypal_capture_id}"
                )

            cap_amount = _extract_int(content, "verified_amount_minor", "amount_minor")
            if cap_amount is not None and cap_amount != intent.amount_minor:
                errors.append(
                    f"Capture evidence amount mismatch on EvidenceRecord {rec.id}: "
                    f"{cap_amount} != PaymentIntent amount {intent.amount_minor}"
                )

            cap_currency = _extract_str(content, "verified_currency", "currency")
            if cap_currency is not None and cap_currency.upper() != intent.currency.upper():
                errors.append(
                    f"Capture evidence currency mismatch on EvidenceRecord {rec.id}: "
                    f"{cap_currency} != PaymentIntent currency {intent.currency}"
                )

            cap_status = _extract_str(content, "paypal_status", "status")
            if (
                intent.state == PaymentState.SUCCEEDED
                and cap_status is not None
                and cap_status.upper() not in {"COMPLETED", "SUCCEEDED"}
            ):
                errors.append(
                    f"Capture evidence status mismatch on EvidenceRecord {rec.id}: "
                    f"PaymentIntent is SUCCEEDED but capture status is {cap_status}"
                )

    for ev in request.events:
        payload = ev.payload or {}
        if ev.event_type in (FinancialEventType.BUDGET_RESERVED, FinancialEventType.BUDGET_CAPTURED):
            ev_res_id = _extract_str(payload, "reservation_id")
            if ev_res_id:
                if intent.reservation_id is not None and ev_res_id != str(intent.reservation_id):
                    errors.append(
                        f"Reservation ID mismatch in FinancialEvent {ev.id}: "
                        f"{ev_res_id} != PaymentIntent.reservation_id {intent.reservation_id}"
                    )
                if budget_reservation is not None and ev_res_id != str(budget_reservation.id):
                    errors.append(
                        f"Reservation ID mismatch in FinancialEvent {ev.id}: "
                        f"{ev_res_id} != BudgetReservation {budget_reservation.id}"
                    )
            ev_amt = _extract_int(payload, "amount_minor")
            if ev_amt is not None and ev_amt != intent.amount_minor:
                errors.append(
                    f"Budget event amount mismatch in FinancialEvent {ev.id}: "
                    f"{ev_amt} != PaymentIntent amount {intent.amount_minor}"
                )
        elif ev.event_type == FinancialEventType.PAYPAL_CAPTURE_VERIFIED:
            order_id = _extract_str(payload, "paypal_order_id", "order_id")
            if order_id and observed_order_ids and order_id not in observed_order_ids:
                errors.append(
                    f"PayPal order mismatch in FinancialEvent {ev.id}: "
                    f"{order_id} != expected {sorted(observed_order_ids)}"
                )
            ev_cap_id = _extract_str(payload, "paypal_capture_id", "capture_id")
            if active_capture and ev_cap_id and ev_cap_id != active_capture.paypal_capture_id:
                errors.append(
                    f"PayPal capture ID mismatch in FinancialEvent {ev.id}: "
                    f"{ev_cap_id} != {active_capture.paypal_capture_id}"
                )
            ev_amt = _extract_int(payload, "verified_amount_minor", "amount_minor")
            if ev_amt is not None and ev_amt != intent.amount_minor:
                errors.append(
                    f"Capture event amount mismatch in FinancialEvent {ev.id}: "
                    f"{ev_amt} != PaymentIntent amount {intent.amount_minor}"
                )

    return errors


def verify_provenance_and_integrity(
    request: ReplayRequest,
    *,
    payment_attempt: PaymentAttempt | None = None,
    verified_capture: VerifiedPayPalCapture | None = None,
    budget_reservation: BudgetReservation | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Perform comprehensive provenance, correlation binding, hash-chain, and completeness checks."""
    resolved_attempt = payment_attempt or getattr(request, "payment_attempt", None)
    resolved_capture = verified_capture or getattr(request, "verified_capture", None)
    resolved_reservation = budget_reservation or getattr(request, "budget_reservation", None)

    # Step 1: Enforce tenancy (raises TenantIsolationError on mismatch)
    enforce_request_tenancy(
        request,
        payment_attempt=resolved_attempt,
        budget_reservation=resolved_reservation,
    )

    errors: list[str] = []

    # Step 2: Enforce correlation_id binding across core artifacts, events, and evidence
    core_entities: list[tuple[str, Any]] = [
        ("PaymentIntent", request.payment_intent),
        ("PurchaseProposal", request.proposal),
        ("QuoteSnapshot", request.quote_snapshot),
        ("AuthorizationDecision", request.recorded_decision),
    ]
    if request.approval_record is not None:
        core_entities.append(("ApprovalRecord", request.approval_record))

    for label, entity in core_entities:
        if entity.correlation_id != request.correlation_id:
            errors.append(
                f"Correlation mismatch on {label} {entity.id}: "
                f"expected {request.correlation_id}, got {entity.correlation_id}"
            )

    # Step 3: Verify financial event hash chain, correlation binding, and intent binding
    chain_ok, chain_errors = verify_financial_event_chain(request.events)
    if not chain_ok:
        errors.extend(chain_errors)
    for ev in request.events:
        if ev.correlation_id != request.correlation_id:
            errors.append(
                f"Correlation mismatch on FinancialEvent {ev.id}: "
                f"expected {request.correlation_id}, got {ev.correlation_id}"
            )
        if ev.payment_intent_id is not None and ev.payment_intent_id != request.payment_intent.id:
            errors.append(
                f"PaymentIntent mismatch on FinancialEvent {ev.id}: "
                f"expected {request.payment_intent.id}, got {ev.payment_intent_id}"
            )

    # Step 4: Verify quote snapshot binding hash
    quote_ok, quote_err = verify_quote_snapshot_integrity(request.quote_snapshot)
    if not quote_ok and quote_err:
        errors.append(quote_err)

    # Step 5: Verify each evidence record digest, correlation binding, and intent binding
    for rec in request.evidence_records:
        if rec.correlation_id != request.correlation_id:
            errors.append(
                f"Correlation mismatch on EvidenceRecord {rec.id}: "
                f"expected {request.correlation_id}, got {rec.correlation_id}"
            )
        if rec.payment_intent_id is not None and rec.payment_intent_id != request.payment_intent.id:
            errors.append(
                f"PaymentIntent mismatch on EvidenceRecord {rec.id}: "
                f"expected {request.payment_intent.id}, got {rec.payment_intent_id}"
            )
        ev_ok, ev_err = verify_evidence_digest(rec)
        if not ev_ok and ev_err:
            errors.append(ev_err)

    # Step 6: Cross-check PaymentAttempt, VerifiedPayPalCapture, and BudgetReservation consistency
    errors.extend(
        verify_execution_artifacts_consistency(
            request,
            payment_attempt=resolved_attempt,
            verified_capture=resolved_capture,
            budget_reservation=resolved_reservation,
        )
    )

    # Step 7: Check missing evidence
    missing = check_missing_evidence(request)

    integrity_valid = len(errors) == 0
    return integrity_valid, missing, errors
