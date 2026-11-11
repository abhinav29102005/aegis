"""Non-mutating counterfactual policy simulation for GhostPay."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from contracts import ReplayRequest, ReplayResult

from ghostpay.counterfactual.validator import (
    apply_validated_counterfactual_overrides,
)
from ghostpay.errors import OverrideValidationError, ReplayExecutionForbiddenError
from ghostpay.provenance.verifier import enforce_request_tenancy
from ghostpay.replay.engine import ReplayEngine
from ghostpay.replay.registry import resolve_policy_evaluator


def simulate_counterfactual(
    request: ReplayRequest,
    overrides: Mapping[str, Any] | None = None,
) -> ReplayResult:
    """Simulate what-if policy changes on isolated validated copies without mutating originals.

    Supported override keys (strictly allowlisted & Pydantic v2 validated):
    - per_tx_limit_minor: int (>= 0)
    - total_budget_minor: int (>= 0)
    - daily_limit_minor: int (>= 0)
    - allowed_merchant_ids: list[UUID]
    - allow_unknown_merchants: bool
    - allowed_categories: list[str]
    - human_approval_threshold_minor: int (>= 0)
    - passport_status: PassportStatus | str
    - expires_at: datetime | ISO-8601 str
    - merchant_override: Merchant | dict | UUID | UUID str (same tenant enforced)
    - amount_override_minor: int (> 0)
    - currency_override: str (3-letter ISO code)
    """
    if overrides is not None and not isinstance(overrides, Mapping):
        raise OverrideValidationError(
            "Counterfactual overrides must be a mapping/dict.",
            errors=[{"field": "overrides", "message": "Expected mapping/dict payload."}],
        )

    # 1. Fail closed on tenant isolation & policy version before applying overrides
    enforce_request_tenancy(request)
    resolve_policy_evaluator(request.policy_version)

    # 2. Merge dictionary overrides safely without mutating caller objects
    effective_overrides: dict[str, Any] = {
        **request.counterfactual_overrides,
        **dict(overrides or {}),
    }

    # 3. Validate overrides and reconstruct isolated hypothetical ReplayRequest
    hypothetical_request, _validated, applied_fields = apply_validated_counterfactual_overrides(
        request,
        effective_overrides,
    )

    # 4. Evaluate baseline (unmodified recorded policy) vs hypothetical (with overrides)
    baseline_request = request.model_copy(deep=True, update={"counterfactual_overrides": {}})
    baseline_result = ReplayEngine.replay(baseline_request)
    hypothetical_result = ReplayEngine.replay(hypothetical_request)

    # 5. Annotate baseline vs hypothetical comparison inside frozen ReplayResult contract
    comparison_constraints = list(hypothetical_result.changed_constraints)
    baseline_vs_hypothetical = (
        f"COUNTERFACTUAL_COMPARISON: baseline_recomputed={baseline_result.recomputed_outcome.value} "
        f"-> hypothetical={hypothetical_result.recomputed_outcome.value} "
        f"(recorded={baseline_result.original_outcome.value}, overrides={applied_fields})"
    )
    comparison_constraints.insert(0, baseline_vs_hypothetical)

    explanation = (
        f"Counterfactual simulation (read-only, executed_payment=False) for "
        f"correlation_id={request.correlation_id} using policy_version={hypothetical_result.policy_version}. "
        f"Applied overrides={applied_fields}. "
        f"Recorded outcome={baseline_result.original_outcome.value}; "
        f"baseline recomputed={baseline_result.recomputed_outcome.value}; "
        f"hypothetical outcome={hypothetical_result.recomputed_outcome.value} "
        f"({[r.value for r in hypothetical_result.recomputed_reason_codes]}). "
        f"Status={hypothetical_result.consistency_status}, drift_detected={hypothetical_result.drift_detected}."
    )[:2000]

    final_result = hypothetical_result.model_copy(
        update={
            "changed_constraints": comparison_constraints,
            "explanation": explanation,
            "executed_payment": False,
        }
    )

    # 6. Safety invariant: counterfactual simulation NEVER executes a payment
    if final_result.executed_payment is not False:
        raise ReplayExecutionForbiddenError(
            "Counterfactual simulation invariant violated: executed_payment must remain False."
        )

    return final_result
