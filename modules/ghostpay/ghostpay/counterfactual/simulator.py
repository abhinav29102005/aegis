"""Non-mutating counterfactual policy simulation for GhostPay."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from contracts import (
    Merchant,
    PassportStatus,
    ReplayRequest,
    ReplayResult,
    compute_quote_hash,
)

from ghostpay.replay.engine import ReplayEngine


def simulate_counterfactual(
    request: ReplayRequest,
    overrides: dict[str, Any] | None = None,
) -> ReplayResult:
    """Simulate what-if policy or environment changes without mutating original request or records.

    Supported overrides:
    - per_tx_limit_minor: int
    - total_budget_minor: int
    - allowed_merchant_ids: list[UUID | str]
    - allow_unknown_merchants: bool
    - human_approval_threshold_minor: int
    - passport_status: PassportStatus | str
    - expires_at: datetime | str
    - merchant_override: Merchant | dict | UUID | str
    - amount_override_minor: int
    """
    # 1. Deep clone the request to guarantee zero mutation of caller inputs
    cloned = request.model_copy(deep=True)

    # 2. Merge dictionary overrides
    effective_overrides: dict[str, Any] = {
        **cloned.counterfactual_overrides,
        **(overrides or {}),
    }

    # 3. Apply passport overrides to cloned object
    passport_updates: dict[str, Any] = {}
    if "per_tx_limit_minor" in effective_overrides:
        passport_updates["per_tx_limit_minor"] = int(effective_overrides["per_tx_limit_minor"])
    if "total_budget_minor" in effective_overrides:
        passport_updates["total_budget_minor"] = int(effective_overrides["total_budget_minor"])
    if "allowed_merchant_ids" in effective_overrides:
        raw_m_ids = effective_overrides["allowed_merchant_ids"]
        passport_updates["allowed_merchant_ids"] = [
            m if isinstance(m, UUID) else UUID(str(m)) for m in raw_m_ids
        ]
    if "allow_unknown_merchants" in effective_overrides:
        passport_updates["allow_unknown_merchants"] = bool(effective_overrides["allow_unknown_merchants"])
    if "human_approval_threshold_minor" in effective_overrides:
        passport_updates["human_approval_threshold_minor"] = int(effective_overrides["human_approval_threshold_minor"])
    if "passport_status" in effective_overrides:
        raw_status = effective_overrides["passport_status"]
        passport_updates["status"] = (
            raw_status if isinstance(raw_status, PassportStatus) else PassportStatus(str(raw_status))
        )
    if "expires_at" in effective_overrides:
        raw_exp = effective_overrides["expires_at"]
        if isinstance(raw_exp, str):
            exp_dt = datetime.fromisoformat(raw_exp)
        else:
            exp_dt = raw_exp
        passport_updates["expires_at"] = exp_dt

    if passport_updates:
        cloned_passport = cloned.recorded_passport.model_copy(update=passport_updates)
        cloned = cloned.model_copy(update={"recorded_passport": cloned_passport})

    # 4. Apply merchant override to cloned object
    if "merchant_override" in effective_overrides:
        m_val = effective_overrides["merchant_override"]
        if isinstance(m_val, Merchant):
            cloned_merchant = m_val
        elif isinstance(m_val, dict):
            cloned_merchant = cloned.recorded_merchant.model_copy(update=m_val)
        elif isinstance(m_val, UUID):
            cloned_merchant = cloned.recorded_merchant.model_copy(update={"id": m_val})
        else:
            cloned_merchant = cloned.recorded_merchant.model_copy(update={"id": UUID(str(m_val))})
        cloned = cloned.model_copy(update={"recorded_merchant": cloned_merchant})

    # 5. Apply amount override to cloned object
    if "amount_override_minor" in effective_overrides:
        new_amount = int(effective_overrides["amount_override_minor"])
        cloned_proposal = cloned.proposal.model_copy(update={"amount_minor": new_amount})
        new_q_hash = compute_quote_hash(
            merchant_id=cloned.quote_snapshot.merchant_id,
            amount_minor=new_amount,
            currency=cloned.quote_snapshot.currency,
            line_items=cloned.quote_snapshot.line_items,
        )
        cloned_quote = cloned.quote_snapshot.model_copy(update={
            "amount_minor": new_amount,
            "quote_hash": new_q_hash,
        })
        cloned_intent = cloned.payment_intent.model_copy(update={
            "amount_minor": new_amount,
            "quote_hash": new_q_hash,
        })
        cloned = cloned.model_copy(update={
            "proposal": cloned_proposal,
            "quote_snapshot": cloned_quote,
            "payment_intent": cloned_intent,
        })

    # 6. Replay cloned request
    result = ReplayEngine.replay(cloned)

    # 7. Invariant: counterfactual simulation NEVER triggers payment execution
    assert result.executed_payment is False, "Counterfactual simulation invariant violated: executed_payment must be False"

    return result
