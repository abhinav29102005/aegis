"""Strict Pydantic v2 counterfactual override validation for GhostPay."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts import (
    Merchant,
    PassportStatus,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    SpendingPassport,
    compute_quote_hash,
)
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from pydantic_core import PydanticCustomError
from security import assert_same_tenant

from ghostpay.errors import OverrideValidationError

ALLOWED_OVERRIDE_FIELDS: frozenset[str] = frozenset({
    "per_tx_limit_minor",
    "total_budget_minor",
    "daily_limit_minor",
    "allowed_merchant_ids",
    "allow_unknown_merchants",
    "allowed_categories",
    "human_approval_threshold_minor",
    "passport_status",
    "expires_at",
    "merchant_override",
    "amount_override_minor",
    "currency_override",
})

IMMUTABLE_OVERRIDE_FIELDS: frozenset[str] = frozenset({
    "id",
    "replay_id",
    "tenant_id",
    "correlation_id",
    "payment_intent",
    "payment_intent_id",
    "proposal_id",
    "quote_snapshot_id",
    "decision_id",
    "recorded_decision",
    "approval_record",
    "events",
    "evidence_records",
    "event_hash",
    "previous_event_hash",
    "content_hash",
    "quote_hash",
    "state",
    "executed_payment",
    "paypal_order_id",
    "paypal_capture_id",
    "verified_capture",
    "buyer_approval",
    "sequence_number",
})


def _normalize_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _parse_strict_int(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PydanticCustomError(
            "invalid_integer",
            "{field_name} must be an integer, got {actual_type}.",
            {"field_name": field_name, "actual_type": type(value).__name__},
        )
    if value < minimum:
        op = ">=" if minimum == 0 else ">"
        raise PydanticCustomError(
            "invalid_bounds",
            "{field_name} must be {op} {minimum}, got {actual_value}.",
            {"field_name": field_name, "op": op, "minimum": minimum, "actual_value": value},
        )
    return value


def _parse_strict_uuid(value: Any, *, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise PydanticCustomError(
            "invalid_uuid_type",
            "{field_name} must be a valid UUID string, got {actual_type}.",
            {"field_name": field_name, "actual_type": type(value).__name__},
        )
    if not value.strip():
        raise PydanticCustomError(
            "empty_uuid",
            "{field_name} cannot be an empty UUID string.",
            {"field_name": field_name},
        )
    try:
        return UUID(value.strip())
    except ValueError as exc:
        raise PydanticCustomError(
            "malformed_uuid",
            "{field_name} contains malformed UUID '{raw}'.",
            {"field_name": field_name, "raw": value},
        ) from exc


def _parse_strict_datetime(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, bool):
        raise PydanticCustomError(
            "invalid_datetime_type",
            "{field_name} must be an ISO-8601 datetime string or datetime, not bool.",
            {"field_name": field_name},
        )
    if isinstance(value, datetime):
        return _normalize_utc(value)
    if not isinstance(value, str):
        raise PydanticCustomError(
            "invalid_datetime_type",
            "{field_name} must be a valid ISO-8601 datetime string or datetime, got {actual_type}.",
            {"field_name": field_name, "actual_type": type(value).__name__},
        )
    if not value.strip():
        raise PydanticCustomError(
            "empty_datetime",
            "{field_name} must be a valid ISO-8601 datetime string or datetime.",
            {"field_name": field_name},
        )
    text = value.strip()
    if "-" not in text:
        raise PydanticCustomError(
            "invalid_datetime_format",
            "{field_name} must be a valid ISO-8601 datetime string, got '{raw}'.",
            {"field_name": field_name, "raw": value},
        )
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PydanticCustomError(
            "invalid_datetime_format",
            "{field_name} has invalid ISO-8601 timestamp '{raw}'.",
            {"field_name": field_name, "raw": value},
        ) from exc
    return _normalize_utc(parsed)


class ValidatedCounterfactualOverrides(BaseModel):
    """Strict allowlisted counterfactual override schema with full type/bounds validation."""

    model_config = ConfigDict(extra="forbid")

    per_tx_limit_minor: int | None = None
    total_budget_minor: int | None = None
    daily_limit_minor: int | None = None
    allowed_merchant_ids: list[UUID] | None = None
    allow_unknown_merchants: bool | None = None
    allowed_categories: list[str] | None = None
    human_approval_threshold_minor: int | None = None
    passport_status: PassportStatus | None = None
    expires_at: datetime | None = None
    merchant_override: Merchant | dict[str, Any] | UUID | str | None = None
    amount_override_minor: int | None = None
    currency_override: str | None = None

    @field_validator(
        "per_tx_limit_minor",
        "total_budget_minor",
        "daily_limit_minor",
        "human_approval_threshold_minor",
        mode="before",
    )
    @classmethod
    def _validate_non_negative_int(cls, v: Any, info: Any) -> int | None:
        if v is None:
            return None
        return _parse_strict_int(v, field_name=info.field_name, minimum=0)

    @field_validator("amount_override_minor", mode="before")
    @classmethod
    def _validate_positive_int(cls, v: Any) -> int | None:
        if v is None:
            return None
        return _parse_strict_int(v, field_name="amount_override_minor", minimum=1)

    @field_validator("allow_unknown_merchants", mode="before")
    @classmethod
    def _validate_strict_bool(cls, v: Any) -> bool | None:
        if v is None:
            return None
        if not isinstance(v, bool):
            raise PydanticCustomError(
                "invalid_boolean",
                "allow_unknown_merchants must be a boolean, got {actual_type}.",
                {"actual_type": type(v).__name__},
            )
        return v

    @field_validator("allowed_merchant_ids", mode="before")
    @classmethod
    def _validate_merchant_ids(cls, v: Any) -> list[UUID] | None:
        if v is None:
            return None
        if isinstance(v, (str, bytes)) or not isinstance(v, (list, tuple)):
            raise PydanticCustomError(
                "invalid_uuid_list",
                "allowed_merchant_ids must be a list of UUID values.",
            )
        return [_parse_strict_uuid(item, field_name="allowed_merchant_ids[]") for item in v]

    @field_validator("allowed_categories", mode="before")
    @classmethod
    def _validate_categories(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, (str, bytes)) or not isinstance(v, (list, tuple)):
            raise PydanticCustomError(
                "invalid_category_list",
                "allowed_categories must be a list of category strings.",
            )
        cleaned: list[str] = []
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise PydanticCustomError(
                    "invalid_category_item",
                    "Each category in allowed_categories must be a non-empty string.",
                )
            cleaned.append(item.strip())
        return cleaned

    @field_validator("passport_status", mode="before")
    @classmethod
    def _validate_status(cls, v: Any) -> PassportStatus | None:
        if v is None:
            return None
        if isinstance(v, PassportStatus):
            return v
        if not isinstance(v, str):
            raise PydanticCustomError(
                "invalid_passport_status_type",
                "passport_status must be a valid PassportStatus string, got {actual_type}.",
                {"actual_type": type(v).__name__},
            )
        try:
            return PassportStatus(v.strip().upper())
        except ValueError as exc:
            valid = ", ".join(s.value for s in PassportStatus)
            raise PydanticCustomError(
                "invalid_passport_status",
                "Invalid passport_status '{raw}'. Allowed values: {valid}.",
                {"raw": v, "valid": valid},
            ) from exc

    @field_validator("expires_at", mode="before")
    @classmethod
    def _validate_expires_at(cls, v: Any) -> datetime | None:
        if v is None:
            return None
        return _parse_strict_datetime(v, field_name="expires_at")

    @field_validator("currency_override", mode="before")
    @classmethod
    def _validate_currency(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise PydanticCustomError(
                "invalid_currency_type",
                "currency_override must be a 3-letter ISO currency code string, got {actual_type}.",
                {"actual_type": type(v).__name__},
            )
        code = v.strip().upper()
        if len(code) != 3 or not code.isascii() or not code.isalpha():
            raise PydanticCustomError(
                "invalid_currency_code",
                "Invalid currency_override '{raw}'. Expected 3-letter alphabetic ISO code (e.g., USD).",
                {"raw": v},
            )
        return code


def validate_counterfactual_overrides(
    raw_overrides: Mapping[str, Any] | None,
) -> ValidatedCounterfactualOverrides:
    """Validate raw counterfactual override dictionary against strict allowlist and types."""
    if raw_overrides is None:
        return ValidatedCounterfactualOverrides()
    if not isinstance(raw_overrides, Mapping):
        raise OverrideValidationError(
            "Counterfactual overrides must be a JSON object/mapping.",
            errors=[{"field": "overrides", "message": "Expected mapping/dict payload."}],
        )

    errors: list[dict[str, Any]] = []
    for key, val in raw_overrides.items():
        if not isinstance(key, str):
            errors.append({"field": str(key), "message": "Override keys must be strings."})
            continue
        if key in IMMUTABLE_OVERRIDE_FIELDS:
            errors.append({
                "field": key,
                "message": (
                    f"Override field '{key}' targets an immutable transaction, evidence, "
                    "or execution attribute and cannot be mutated."
                ),
            })
        elif key not in ALLOWED_OVERRIDE_FIELDS:
            errors.append({
                "field": key,
                "message": (
                    f"Unknown counterfactual override field '{key}'. "
                    f"Allowed fields: {sorted(ALLOWED_OVERRIDE_FIELDS)}"
                ),
            })
        elif val is None:
            errors.append({
                "field": key,
                "message": f"Override field '{key}' cannot be null.",
            })

    if errors:
        raise OverrideValidationError(
            "; ".join(err["message"] for err in errors),
            errors=errors,
        )

    try:
        return ValidatedCounterfactualOverrides.model_validate(dict(raw_overrides))
    except ValidationError as exc:
        formatted = [
            {
                "field": ".".join(str(loc) for loc in err.get("loc", ())) or "overrides",
                "message": err.get("msg", "Invalid override value"),
            }
            for err in exc.errors()
        ]
        raise OverrideValidationError(
            "; ".join(item["message"] for item in formatted),
            errors=formatted,
        ) from exc


def _validate_and_build_merchant_override(
    override_value: Merchant | dict[str, Any] | UUID | str,
    *,
    base_merchant: Merchant,
    expected_tenant_id: UUID,
) -> Merchant:
    """Reconstruct and tenant-validate a Merchant override without unvalidated model_copy."""
    if isinstance(override_value, Merchant):
        assert_same_tenant(expected_tenant_id, override_value.tenant_id, "merchant_override")
        try:
            return Merchant.model_validate(override_value.model_dump())
        except ValidationError as exc:
            raise OverrideValidationError(
                f"Invalid merchant_override model: {exc}",
                errors=[{"field": "merchant_override", "message": str(exc)}],
            ) from exc

    if isinstance(override_value, Mapping):
        if not override_value:
            raise OverrideValidationError(
                "merchant_override dictionary cannot be empty.",
                errors=[{"field": "merchant_override", "message": "Dictionary cannot be empty."}],
            )
        unknown_keys = set(override_value.keys()) - set(Merchant.model_fields.keys())
        if unknown_keys:
            raise OverrideValidationError(
                f"Unknown merchant_override field(s): {sorted(unknown_keys)}",
                errors=[
                    {
                        "field": "merchant_override",
                        "message": f"Unknown field(s): {sorted(unknown_keys)}",
                    }
                ],
            )
        if "tenant_id" in override_value:
            try:
                override_tenant = _parse_strict_uuid(
                    override_value["tenant_id"],
                    field_name="merchant_override.tenant_id",
                )
            except ValueError as exc:
                raise OverrideValidationError(
                    str(exc),
                    errors=[{"field": "merchant_override.tenant_id", "message": str(exc)}],
                ) from exc
            # Fail closed with TenantIsolationError (HTTP 403) on cross-tenant merchant override
            assert_same_tenant(expected_tenant_id, override_tenant, "merchant_override")

        merged_merchant = {**base_merchant.model_dump(), **dict(override_value)}
        try:
            validated_merchant = Merchant.model_validate(merged_merchant)
        except ValidationError as exc:
            formatted = [
                {
                    "field": "merchant_override." + ".".join(str(x) for x in err.get("loc", ())),
                    "message": err.get("msg", "Invalid merchant_override field"),
                }
                for err in exc.errors()
            ]
            raise OverrideValidationError(
                "; ".join(item["message"] for item in formatted),
                errors=formatted,
            ) from exc
        assert_same_tenant(expected_tenant_id, validated_merchant.tenant_id, "merchant_override")
        return validated_merchant

    if isinstance(override_value, (UUID, str)):
        try:
            merchant_uuid = _parse_strict_uuid(override_value, field_name="merchant_override")
        except ValueError as exc:
            raise OverrideValidationError(
                str(exc),
                errors=[{"field": "merchant_override", "message": str(exc)}],
            ) from exc
        merged_merchant = {**base_merchant.model_dump(), "id": merchant_uuid}
        return Merchant.model_validate(merged_merchant)

    raise OverrideValidationError(
        f"Invalid merchant_override type: {type(override_value).__name__}.",
        errors=[
            {
                "field": "merchant_override",
                "message": "Expected Merchant object, dict, or UUID.",
            }
        ],
    )


def apply_validated_counterfactual_overrides(
    request: ReplayRequest,
    raw_overrides: Mapping[str, Any] | None,
) -> tuple[ReplayRequest, ValidatedCounterfactualOverrides, list[str]]:
    """Validate overrides and build a strictly reconstructed deep-isolated hypothetical ReplayRequest.

    Original ``request`` and all nested records remain unmutated. Immutable transaction,
    evidence, and capture records are copied intact and cleared of raw overrides so baseline
    vs hypothetical evaluation runs deterministically.
    """
    validated = validate_counterfactual_overrides(raw_overrides)
    applied_fields = [
        name
        for name in ValidatedCounterfactualOverrides.model_fields
        if getattr(validated, name) is not None
    ]

    # Deep copy first so caller objects are completely isolated
    isolated = request.model_copy(deep=True)

    # 1. Reconstruct hypothetical SpendingPassport via Model.model_validate
    passport_data = isolated.recorded_passport.model_dump()
    if validated.per_tx_limit_minor is not None:
        passport_data["per_tx_limit_minor"] = validated.per_tx_limit_minor
    if validated.total_budget_minor is not None:
        passport_data["total_budget_minor"] = validated.total_budget_minor
    if validated.daily_limit_minor is not None:
        passport_data["daily_limit_minor"] = validated.daily_limit_minor
    if validated.allowed_merchant_ids is not None:
        passport_data["allowed_merchant_ids"] = validated.allowed_merchant_ids
    if validated.allow_unknown_merchants is not None:
        passport_data["allow_unknown_merchants"] = validated.allow_unknown_merchants
    if validated.allowed_categories is not None:
        passport_data["allowed_categories"] = validated.allowed_categories
    if validated.human_approval_threshold_minor is not None:
        passport_data["human_approval_threshold_minor"] = validated.human_approval_threshold_minor
    if validated.passport_status is not None:
        passport_data["status"] = validated.passport_status
    if validated.expires_at is not None:
        passport_data["expires_at"] = validated.expires_at

    try:
        hypothetical_passport = SpendingPassport.model_validate(passport_data)
    except ValidationError as exc:
        raise OverrideValidationError(
            f"Invalid passport override parameters: {exc}",
            errors=[{"field": "recorded_passport", "message": str(exc)}],
        ) from exc

    # 2. Reconstruct hypothetical Merchant via Model.model_validate + tenant guard
    hypothetical_merchant = isolated.recorded_merchant
    if validated.merchant_override is not None:
        hypothetical_merchant = _validate_and_build_merchant_override(
            validated.merchant_override,
            base_merchant=isolated.recorded_merchant,
            expected_tenant_id=request.tenant_id,
        )

    # 3. Reconstruct hypothetical PurchaseProposal and QuoteSnapshot via Model.model_validate
    hypothetical_proposal = isolated.proposal
    hypothetical_quote = isolated.quote_snapshot

    if validated.amount_override_minor is not None or validated.currency_override is not None:
        new_amount = (
            validated.amount_override_minor
            if validated.amount_override_minor is not None
            else isolated.proposal.amount_minor
        )
        new_currency = (
            validated.currency_override
            if validated.currency_override is not None
            else isolated.proposal.currency
        )
        proposal_data = {
            **isolated.proposal.model_dump(),
            "amount_minor": new_amount,
            "currency": new_currency,
        }
        quote_amount = (
            validated.amount_override_minor
            if validated.amount_override_minor is not None
            else isolated.quote_snapshot.amount_minor
        )
        quote_currency = (
            validated.currency_override
            if validated.currency_override is not None
            else isolated.quote_snapshot.currency
        )
        new_q_hash = compute_quote_hash(
            merchant_id=isolated.quote_snapshot.merchant_id,
            amount_minor=quote_amount,
            currency=quote_currency,
            line_items=isolated.quote_snapshot.line_items,
        )
        quote_data = {
            **isolated.quote_snapshot.model_dump(),
            "amount_minor": quote_amount,
            "currency": quote_currency,
            "quote_hash": new_q_hash,
        }
        try:
            hypothetical_proposal = PurchaseProposal.model_validate(proposal_data)
            hypothetical_quote = QuoteSnapshot.model_validate(quote_data)
        except ValidationError as exc:
            raise OverrideValidationError(
                f"Invalid proposal/quote override parameters: {exc}",
                errors=[{"field": "proposal_or_quote", "message": str(exc)}],
            ) from exc

    # 4. Reconstruct top-level ReplayRequest cleanly (immutable records preserved, overrides cleared)
    hypothetical_request = isolated.model_copy(
        update={
            "recorded_passport": hypothetical_passport,
            "recorded_merchant": hypothetical_merchant,
            "proposal": hypothetical_proposal,
            "quote_snapshot": hypothetical_quote,
            "counterfactual_overrides": {},
        }
    )
    return hypothetical_request, validated, applied_fields
