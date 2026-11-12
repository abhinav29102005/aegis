"""Deterministic missing-evidence and contradiction detection for DisputeOS."""

from __future__ import annotations

import re
from typing import Any

from contracts import DisputeCase, EvidenceRecord, EvidenceSourceType
from paypal import paypal_value_to_minor
from security import assert_same_tenant

_BASELINE_REQUIRED: tuple[tuple[EvidenceSourceType, str], ...] = (
    (
        EvidenceSourceType.QUOTE,
        "Missing QUOTE evidence record (bound merchant, amount, and quote hash snapshot).",
    ),
    (
        EvidenceSourceType.POLICY_DECISION,
        "Missing POLICY_DECISION evidence record (deterministic policy authorization output).",
    ),
    (
        EvidenceSourceType.PAYPAL_CAPTURE,
        "Missing PAYPAL_CAPTURE evidence record (verified PayPal capture receipt).",
    ),
)

_DELIVERY_REQUIRED: tuple[tuple[EvidenceSourceType, str], ...] = (
    (
        EvidenceSourceType.CARRIER_TRACKING,
        "Missing CARRIER_TRACKING evidence record (required for delivery/merchandise dispute).",
    ),
    (
        EvidenceSourceType.DELIVERY_RECEIPT,
        "Missing DELIVERY_RECEIPT evidence record (required for delivery/merchandise dispute).",
    ),
)

_DELIVERY_REASON_TOKENS: tuple[str, ...] = (
    "NOT_RECEIVED",
    "NOT RECEIVED",
    "DELIVERY",
    "MERCHANDISE",
)

_NON_DELIVERY_PATTERN = re.compile(
    r"\b(not delivered|undelivered|delayed|never arrived|lost)\b"
)


def _enforce_tenant(case: DisputeCase, evidence: list[EvidenceRecord]) -> None:
    for rec in evidence:
        assert_same_tenant(case.tenant_id, rec.tenant_id, "evidence_record")


def _flatten_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for val in value.values():
            parts.extend(_flatten_text(val))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            parts.extend(_flatten_text(item))
        return parts
    return [str(value)]


def _tracking_indicates_delivered(rec: EvidenceRecord) -> bool:
    for key in ("status", "delivery_status", "tracking_status", "state"):
        raw = rec.content.get(key)
        if raw is None:
            continue
        upper = str(raw).strip().upper().replace("_", " ")
        if "DELIVERED" in upper and "UNDELIVERED" not in upper and "NOT DELIVERED" not in upper:
            return True
    return False


def _find_non_delivery_term(rec: EvidenceRecord) -> str | None:
    text_blob = " ".join([rec.title, *_flatten_text(rec.content)]).lower().replace("_", " ")
    match = _NON_DELIVERY_PATTERN.search(text_blob)
    return match.group(1) if match else None


def _extract_amount_minor(content: dict[str, Any]) -> int | None:
    for key in ("amount_minor", "verified_amount_minor"):
        raw = content.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
            return int(raw.strip())

    amount_val = content.get("amount")
    if isinstance(amount_val, int) and not isinstance(amount_val, bool):
        return amount_val
    if isinstance(amount_val, dict) and amount_val.get("value") is not None:
        return paypal_value_to_minor(str(amount_val["value"]))
    return None


def detect_missing_evidence(case: DisputeCase, evidence: list[EvidenceRecord]) -> list[str]:
    """Identify missing required evidence records without fabricating any evidence."""
    _enforce_tenant(case, evidence)
    present_types = {rec.source_type for rec in evidence}
    missing: list[str] = []

    for source_type, description in _BASELINE_REQUIRED:
        if source_type not in present_types:
            missing.append(description)

    reason_upper = case.reason.upper()
    if any(token in reason_upper for token in _DELIVERY_REASON_TOKENS):
        for source_type, description in _DELIVERY_REQUIRED:
            if source_type not in present_types:
                missing.append(description)

    return missing


def detect_contradictions(case: DisputeCase, evidence: list[EvidenceRecord]) -> list[str]:
    """Detect deterministic factual contradictions across tenant-verified evidence records."""
    _enforce_tenant(case, evidence)
    contradictions: list[str] = []

    delivered_trackings = [
        rec
        for rec in evidence
        if rec.source_type == EvidenceSourceType.CARRIER_TRACKING and _tracking_indicates_delivered(rec)
    ]
    delivery_or_msg_records = [
        rec
        for rec in evidence
        if rec.source_type in (EvidenceSourceType.CUSTOMER_MESSAGE, EvidenceSourceType.DELIVERY_RECEIPT)
    ]

    for tracking_rec in delivered_trackings:
        for other_rec in delivery_or_msg_records:
            matched_term = _find_non_delivery_term(other_rec)
            if matched_term is not None:
                contradictions.append(
                    f"Contradiction between CARRIER_TRACKING {tracking_rec.id} (status=DELIVERED) "
                    f"and {other_rec.source_type.value} {other_rec.id} "
                    f"(indicates non-delivery/delay via '{matched_term}')."
                )

    for rec in evidence:
        if rec.source_type in (EvidenceSourceType.QUOTE, EvidenceSourceType.PAYPAL_CAPTURE):
            recorded_minor = _extract_amount_minor(rec.content)
            if recorded_minor is not None and recorded_minor != case.amount_minor:
                contradictions.append(
                    f"Contradiction in {rec.source_type.value} {rec.id}: recorded amount_minor={recorded_minor} "
                    f"mismatches dispute case amount_minor={case.amount_minor}."
                )

    denied_decisions = [
        rec
        for rec in evidence
        if rec.source_type == EvidenceSourceType.POLICY_DECISION
        and str(rec.content.get("outcome", "")).strip().upper() == "DENY"
    ]
    capture_records = [
        rec for rec in evidence if rec.source_type == EvidenceSourceType.PAYPAL_CAPTURE
    ]
    for decision_rec in denied_decisions:
        for capture_rec in capture_records:
            linked_intent = (
                decision_rec.payment_intent_id is None
                or capture_rec.payment_intent_id is None
                or decision_rec.payment_intent_id == capture_rec.payment_intent_id
            )
            if linked_intent:
                contradictions.append(
                    f"Contradiction between POLICY_DECISION {decision_rec.id} (outcome=DENY) "
                    f"and PAYPAL_CAPTURE {capture_rec.id} (capture recorded despite policy denial)."
                )

    # GAP-017 Heuristic 1: Card AVS/CVV/3DS checks (3DS pass/fail vs unauthorized claim)
    case_reason_claim = f"{case.reason} {case.buyer_claim}".upper().replace("_", " ")
    unauthorized_tokens = ("UNAUTHORIZED", "FRAUD", "NOT RECOGNIZED", "DID NOT AUTHORIZE")
    if any(tok in case_reason_claim for tok in unauthorized_tokens):
        for rec in evidence:
            c = rec.content
            three_ds = c.get("three_d_secure") or c.get("3ds_status") or c.get("liability_shift")
            cvv = c.get("cvv_match") or c.get("cvv_code")
            avs = c.get("avs_match") or c.get("avs_code")
            is_3ds_pass = str(three_ds).upper() in ("TRUE", "Y", "AUTHENTICATED", "SUCCESS")
            is_cvv_match = str(cvv).upper() in ("TRUE", "Y", "M", "MATCH")
            if is_3ds_pass or is_cvv_match:
                contradictions.append(
                    f"Contradiction: Buyer claims unauthorized charge, but {rec.source_type.value} {rec.id} "
                    f"confirms authentication verification (3DS={three_ds}, CVV={cvv}, AVS={avs})."
                )

    # GAP-017 Heuristic 2: Telemetry checks (active IP/session login vs non-access claim)
    non_access_tokens = ("NOT ACCESSED", "NEVER USED", "DID NOT USE", "NO ACCESS", "SERVICE NOT RECEIVED")
    if any(tok in case_reason_claim for tok in non_access_tokens):
        for rec in evidence:
            c = rec.content
            login_time = c.get("last_login") or c.get("session_started_at") or c.get("active_timestamp")
            login_ip = c.get("ip_address") or c.get("client_ip")
            if login_time or login_ip:
                contradictions.append(
                    f"Contradiction: Buyer claims non-access, but telemetry in {rec.source_type.value} {rec.id} "
                    f"shows verified active session (login={login_time}, ip={login_ip})."
                )

    # GAP-017 Heuristic 3: Cancellation proofs (cancellation requested after renewal date vs pre-renewal claim)
    cancel_tokens = ("CANCELLED BEFORE", "CANCELED BEFORE", "CANCELLED PRIOR", "PRE-RENEWAL")
    if any(tok in case_reason_claim for tok in cancel_tokens):
        for rec in evidence:
            c = rec.content
            cancel_date = c.get("cancellation_requested_at") or c.get("cancellation_date")
            billing_date = c.get("renewal_date") or c.get("billing_date")
            if cancel_date and billing_date and str(cancel_date) > str(billing_date):
                contradictions.append(
                    f"Contradiction: Buyer claims pre-renewal cancellation, but {rec.source_type.value} {rec.id} "
                    f"shows cancellation was requested on {cancel_date}, after billing date {billing_date}."
                )

    return contradictions
