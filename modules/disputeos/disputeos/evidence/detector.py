"""Deterministic missing-evidence and contradiction detection for DisputeOS."""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
    "INR",
    "DELIVERY",
    "MERCHANDISE",
    "NEVER_ARRIVED",
)

_UNAUTHORIZED_REASON_TOKENS: tuple[str, ...] = (
    "UNAUTHORIZED",
    "UNAUTHORISED",
    "FRAUD",
    "STOLEN_CARD",
    "ACCOUNT_TAKEOVER",
    "NO_AUTHORIZATION",
)

_SUBSCRIPTION_REASON_TOKENS: tuple[str, ...] = (
    "SUBSCRIPTION",
    "RECURRING",
    "CANCELLED_RECURRING",
    "CANCELED_RECURRING",
    "BILLING_AGREEMENT",
    "CANCELLED",
    "CANCELED",
)

_SNAD_REASON_TOKENS: tuple[str, ...] = (
    "SIGNIFICANTLY_NOT_AS_DESCRIBED",
    "NOT_AS_DESCRIBED",
    "SNAD",
    "DEFECTIVE",
    "DAMAGED",
    "COUNTERFEIT",
    "WRONG_ITEM",
)

_NON_DELIVERY_PATTERN = re.compile(
    r"\b("
    r"not delivered|non-delivery|non delivery|undelivered|delayed|never arrived|"
    r"never delivered|failed delivery|lost in transit|lost|missing package|"
    r"returned to sender|wrong address|unshipped|out of stock|backordered|not received"
    r")\b"
)

_SNAD_ADMISSION_PATTERN = re.compile(
    r"\b("
    r"wrong item|defective|damaged in transit|damaged item|counterfeit|"
    r"not as described|significantly not as described|missing parts|broken on arrival"
    r")\b"
)

_CARD_VERIFICATION_KEYS: frozenset[str] = frozenset({
    "avs_result",
    "avs_code",
    "cvv_result",
    "cvv2_match",
    "three_ds",
    "3ds_status",
    "eci",
    "authentication_result",
    "card_verification",
})

_TELEMETRY_KEYS: frozenset[str] = frozenset({
    "ip_address",
    "buyer_ip",
    "device_fingerprint",
    "device_id",
    "user_agent",
    "session_id",
    "geo_ip",
    "ip_country",
    "telemetry",
})

_SUBSCRIPTION_KEYS: frozenset[str] = frozenset({
    "subscription_id",
    "billing_agreement_id",
    "cancellation_status",
    "cancelled_at",
    "canceled_at",
    "cancellation_proof",
    "cancellation_confirmed",
    "renewal_notice_sent",
    "recurring_consent",
    "terms_accepted_at",
})

_SNAD_SPEC_KEYS: frozenset[str] = frozenset({
    "line_items",
    "item_description",
    "product_specs",
    "listing_snapshot",
    "sku",
    "condition",
    "item_condition",
})

_SNAD_INSPECTION_KEYS: frozenset[str] = frozenset({
    "rma_status",
    "return_policy",
    "inspection_report",
    "quality_check",
    "merchant_response",
    "resolution_offer",
    "pre_shipment_condition",
})

_FAILED_CARD_CHECK_VALUES: frozenset[str] = frozenset({
    "N",
    "NO_MATCH",
    "FAIL",
    "FAILED",
    "MISMATCH",
    "REJECTED",
    "U",
    "ATTEMPT_FAILED",
})

_CANCELLED_STATUS_VALUES: frozenset[str] = frozenset({
    "CANCELLED",
    "CANCELED",
    "TERMINATED",
    "REVOKED",
})


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


def _collect_nested_keys(value: Any) -> dict[str, Any]:
    """Collect lowercase leaf/nested dict keys across content dictionaries for heuristic inspection."""
    collected: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, val in value.items():
            lowered = str(key).strip().lower()
            if val is not None and lowered not in collected:
                collected[lowered] = val
            if isinstance(val, dict):
                for nested_k, nested_v in _collect_nested_keys(val).items():
                    if nested_k not in collected:
                        collected[nested_k] = nested_v
    return collected


def _has_any_nonempty_key(evidence: list[EvidenceRecord], keys: frozenset[str]) -> bool:
    for rec in evidence:
        flat = _collect_nested_keys(rec.content)
        for key in keys:
            val = flat.get(key)
            if val not in (None, "", [], {}):
                return True
    return False


def _parse_iso_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str) and value.strip():
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = f"{cleaned[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


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
    claim_upper = case.buyer_claim.upper()
    combined_upper = f"{reason_upper} {claim_upper}"

    if any(token in reason_upper for token in _DELIVERY_REASON_TOKENS):
        for source_type, description in _DELIVERY_REQUIRED:
            if source_type not in present_types:
                missing.append(description)

    if any(token in combined_upper for token in _UNAUTHORIZED_REASON_TOKENS):
        if not _has_any_nonempty_key(evidence, _CARD_VERIFICATION_KEYS):
            missing.append(
                "Missing AVS/CVV/3DS card verification telemetry "
                "(avs_result, cvv_result, or 3DS authentication status required for unauthorized dispute)."
            )
        if not _has_any_nonempty_key(evidence, _TELEMETRY_KEYS):
            missing.append(
                "Missing IP/device telemetry "
                "(ip_address, device_fingerprint, or session_id required for unauthorized dispute)."
            )

    if any(token in combined_upper for token in _SUBSCRIPTION_REASON_TOKENS) and not _has_any_nonempty_key(
        evidence, _SUBSCRIPTION_KEYS
    ):
        missing.append(
            "Missing subscription/cancellation proof "
            "(subscription_id, cancellation_status, cancelled_at, or recurring consent log required)."
        )

    if any(token in combined_upper for token in _SNAD_REASON_TOKENS):
        if not _has_any_nonempty_key(evidence, _SNAD_SPEC_KEYS):
            missing.append(
                "Missing SIGNIFICANTLY_NOT_AS_DESCRIBED item specification packet "
                "(line_items, product_specs, condition, or listing_snapshot required)."
            )
        if not _has_any_nonempty_key(evidence, _SNAD_INSPECTION_KEYS):
            missing.append(
                "Missing SIGNIFICANTLY_NOT_AS_DESCRIBED inspection/RMA packet "
                "(inspection_report, rma_status, return_policy, or pre_shipment_condition required)."
            )

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

    # Card AVS / CVV / 3DS check contradictions
    for rec in evidence:
        flat = _collect_nested_keys(rec.content)
        for check_key in ("avs_result", "avs_code", "cvv_result", "cvv2_match", "three_ds", "3ds_status", "authentication_result"):
            val = flat.get(check_key)
            if val is not None and str(val).strip().upper() in _FAILED_CARD_CHECK_VALUES:
                contradictions.append(
                    f"Card verification failure in {rec.source_type.value} {rec.id}: "
                    f"{check_key}={val} contradicts authorized payment verification."
                )

    # IP / Device / Geo telemetry contradictions
    observed_ips: list[tuple[EvidenceRecord, str]] = []
    observed_devices: list[tuple[EvidenceRecord, str]] = []
    for rec in evidence:
        flat = _collect_nested_keys(rec.content)
        ip_val = flat.get("ip_address") or flat.get("buyer_ip")
        if isinstance(ip_val, str) and ip_val.strip():
            observed_ips.append((rec, ip_val.strip()))
        dev_val = flat.get("device_fingerprint") or flat.get("device_id")
        if isinstance(dev_val, str) and dev_val.strip():
            observed_devices.append((rec, dev_val.strip()))

        ip_country = flat.get("ip_country")
        billing_country = flat.get("billing_country")
        if ip_country and billing_country and str(ip_country).strip().upper() != str(billing_country).strip().upper():
            contradictions.append(
                f"Geo-IP mismatch in {rec.source_type.value} {rec.id}: "
                f"ip_country={ip_country} differs from billing_country={billing_country}."
            )
        if flat.get("device_mismatch") is True or flat.get("vpn_tor_detected") is True or flat.get("velocity_anomaly") is True:
            contradictions.append(
                f"Telemetry risk anomaly in {rec.source_type.value} {rec.id}: "
                f"device/network telemetry flagged anomalous activity."
            )

    if len({ip for _, ip in observed_ips}) > 1:
        first_rec, first_ip = observed_ips[0]
        second_rec, second_ip = next((r, ip) for r, ip in observed_ips if ip != first_ip)
        contradictions.append(
            f"IP telemetry contradiction between {first_rec.source_type.value} {first_rec.id} ({first_ip}) "
            f"and {second_rec.source_type.value} {second_rec.id} ({second_ip})."
        )
    if len({dev for _, dev in observed_devices}) > 1:
        first_rec, first_dev = observed_devices[0]
        second_rec, second_dev = next((r, dev) for r, dev in observed_devices if dev != first_dev)
        contradictions.append(
            f"Device fingerprint contradiction between {first_rec.source_type.value} {first_rec.id} ({first_dev}) "
            f"and {second_rec.source_type.value} {second_rec.id} ({second_dev})."
        )

    # Subscription cancellation contradictions
    for rec in evidence:
        flat = _collect_nested_keys(rec.content)
        cancel_status = str(flat.get("cancellation_status", "")).strip().upper()
        cancelled_at = _parse_iso_dt(flat.get("cancelled_at") or flat.get("canceled_at"))
        is_cancelled = cancel_status in _CANCELLED_STATUS_VALUES or flat.get("cancellation_confirmed") is True or cancelled_at is not None
        if not is_cancelled:
            continue
        for capture_rec in capture_records:
            cap_flat = _collect_nested_keys(capture_rec.content)
            cap_time = _parse_iso_dt(cap_flat.get("verified_at")) or capture_rec.collected_at
            if cancelled_at is None or cancelled_at <= cap_time:
                contradictions.append(
                    f"Subscription cancellation contradiction between {rec.source_type.value} {rec.id} "
                    f"(cancelled prior to charge) and PAYPAL_CAPTURE {capture_rec.id}."
                )

    # SIGNIFICANTLY_NOT_AS_DESCRIBED (SNAD) contradictions
    quoted_conditions = {
        str(_collect_nested_keys(rec.content).get("condition") or _collect_nested_keys(rec.content).get("item_condition")).strip().upper()
        for rec in evidence
        if rec.source_type in (EvidenceSourceType.QUOTE, EvidenceSourceType.PROPOSAL)
        and (_collect_nested_keys(rec.content).get("condition") or _collect_nested_keys(rec.content).get("item_condition"))
    }
    quoted_skus = {
        str(_collect_nested_keys(rec.content).get("sku")).strip().upper()
        for rec in evidence
        if rec.source_type in (EvidenceSourceType.QUOTE, EvidenceSourceType.PROPOSAL)
        and _collect_nested_keys(rec.content).get("sku")
    }
    for rec in evidence:
        flat = _collect_nested_keys(rec.content)
        if any(flat.get(flag) is True for flag in ("defective", "wrong_item", "damaged_in_transit", "sku_mismatch", "counterfeit")):
            contradictions.append(
                f"SIGNIFICANTLY_NOT_AS_DESCRIBED contradiction in {rec.source_type.value} {rec.id}: "
                f"fulfillment record flags defective/wrong/damaged item."
            )
        if rec.source_type in (EvidenceSourceType.DELIVERY_RECEIPT, EvidenceSourceType.CUSTOMER_MESSAGE):
            obs_cond = flat.get("condition") or flat.get("item_condition")
            if obs_cond and quoted_conditions and str(obs_cond).strip().upper() not in quoted_conditions:
                contradictions.append(
                    f"SIGNIFICANTLY_NOT_AS_DESCRIBED condition mismatch in {rec.source_type.value} {rec.id}: "
                    f"observed condition={obs_cond} contradicts quoted {sorted(quoted_conditions)}."
                )
            obs_sku = flat.get("sku") or flat.get("delivered_sku")
            if obs_sku and quoted_skus and str(obs_sku).strip().upper() not in quoted_skus:
                contradictions.append(
                    f"SIGNIFICANTLY_NOT_AS_DESCRIBED SKU mismatch in {rec.source_type.value} {rec.id}: "
                    f"delivered sku={obs_sku} contradicts quoted {sorted(quoted_skus)}."
                )
            if rec.source_type == EvidenceSourceType.CUSTOMER_MESSAGE:
                msg_blob = " ".join([rec.title, *_flatten_text(rec.content)]).lower().replace("_", " ")
                snad_match = _SNAD_ADMISSION_PATTERN.search(msg_blob)
                if snad_match:
                    contradictions.append(
                        f"SIGNIFICANTLY_NOT_AS_DESCRIBED admission in {rec.source_type.value} {rec.id}: "
                        f"message indicates '{snad_match.group(1)}'."
                    )

    return contradictions
