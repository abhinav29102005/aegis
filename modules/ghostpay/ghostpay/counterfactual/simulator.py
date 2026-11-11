"""Validated, non-mutating counterfactual policy simulation for GhostPay."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from contracts import (
    Merchant,
    PassportStatus,
    ReplayRequest,
    ReplayResult,
    compute_quote_hash,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
)

from ghostpay.replay.engine import ReplayEngine

NonnegativeMoney = Annotated[int, Field(strict=True, ge=0)]
PositiveMoney = Annotated[int, Field(strict=True, gt=0)]


class CounterfactualOverrides(BaseModel):
    """Supported hypothetical changes; omitted fields preserve recorded values."""

    model_config = ConfigDict(extra="forbid")

    per_tx_limit_minor: NonnegativeMoney | None = None
    total_budget_minor: NonnegativeMoney | None = None
    allowed_merchant_ids: list[UUID] | None = None
    allow_unknown_merchants: StrictBool | None = None
    human_approval_threshold_minor: NonnegativeMoney | None = None
    passport_status: PassportStatus | None = None
    expires_at: AwareDatetime | None = None
    merchant_override: Merchant | dict[str, Any] | UUID | None = None
    amount_override_minor: PositiveMoney | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Override values must not be null; omit unchanged fields")
        return value


def simulate_counterfactual(
    request: ReplayRequest,
    overrides: dict[str, Any] | None = None,
) -> ReplayResult:
    """Validate changes and replay an isolated copy without financial side effects."""
    # Revalidate nested objects, including values changed via unvalidated model_copy.
    cloned = ReplayRequest.model_validate(request.model_dump()).model_copy(deep=True)
    effective = CounterfactualOverrides.model_validate(
        {
            **cloned.counterfactual_overrides,
            **(overrides or {}),
        }
    ).model_dump(exclude_unset=True)

    baseline = ReplayEngine.replay(cloned)

    passport_updates = {
        key: effective[key]
        for key in (
            "per_tx_limit_minor",
            "total_budget_minor",
            "allowed_merchant_ids",
            "allow_unknown_merchants",
            "human_approval_threshold_minor",
            "expires_at",
        )
        if key in effective
    }
    if "passport_status" in effective:
        passport_updates["status"] = effective["passport_status"]
    cloned.recorded_passport = type(cloned.recorded_passport).model_validate(
        {
            **cloned.recorded_passport.model_dump(),
            **passport_updates,
        }
    )

    if "merchant_override" in effective:
        merchant = effective["merchant_override"]
        # model_dump serializes a supplied Merchant as a full mapping.
        updates = merchant if isinstance(merchant, dict) else {"id": merchant}
        # An ID-only substitution must not inherit the original merchant's trust.
        candidate = Merchant.model_validate(
            {
                **cloned.recorded_merchant.model_dump(),
                **updates,
            }
        )

        if candidate.id != cloned.recorded_merchant.id and "is_allowlisted" not in updates:
            candidate.is_allowlisted = False
        cloned.recorded_merchant = candidate

    if "amount_override_minor" in effective:
        amount = effective["amount_override_minor"]
        cloned.proposal = type(cloned.proposal).model_validate(
            {
                **cloned.proposal.model_dump(),
                "amount_minor": amount,
            }
        )
        quote_updates = {
            "amount_minor": amount,
            "quote_hash": compute_quote_hash(
                merchant_id=cloned.quote_snapshot.merchant_id,
                amount_minor=amount,
                currency=cloned.quote_snapshot.currency,
                line_items=cloned.quote_snapshot.line_items,
            ),
        }
        cloned.quote_snapshot = type(cloned.quote_snapshot).model_validate(
            {
                **cloned.quote_snapshot.model_dump(),
                **quote_updates,
            }
        )

    result = ReplayEngine._replay(cloned, hypothetical=True)
    # Hypothetical changes cannot repair or hide problems in the source snapshot.
    if not baseline.integrity_valid:
        result.integrity_valid = False
        result.consistency_status = "INTEGRITY_FAILURE"
        result.anomalies = sorted(set(result.anomalies + baseline.anomalies))
    result.missing_evidence = sorted(
        set(result.missing_evidence + baseline.missing_evidence)
    )
    if result.integrity_valid and result.missing_evidence:
        result.consistency_status = "INCOMPLETE_EVIDENCE"
    result.explanation = (
        f"Hypothetical initial authorization simulation. Original outcome: {result.original_outcome.value}. "
        f"Recomputed outcome: {result.recomputed_outcome.value}. "
        f"Consistency status: {result.consistency_status}. Integrity valid: {result.integrity_valid}. "
        f"Missing evidence count: {len(result.missing_evidence)}. "
        "Source integrity and completeness remain prerequisites; no payment executed."
    )
    assert result.executed_payment is False, (
        "Counterfactual simulation must not execute payments"
    )
    return result
