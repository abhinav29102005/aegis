"""Counterfactual policy simulation and strict override validation."""

from ghostpay.counterfactual.simulator import simulate_counterfactual
from ghostpay.counterfactual.validator import (
    ALLOWED_OVERRIDE_FIELDS,
    IMMUTABLE_OVERRIDE_FIELDS,
    ValidatedCounterfactualOverrides,
    apply_validated_counterfactual_overrides,
    validate_counterfactual_overrides,
)

__all__ = [
    "ALLOWED_OVERRIDE_FIELDS",
    "IMMUTABLE_OVERRIDE_FIELDS",
    "ValidatedCounterfactualOverrides",
    "apply_validated_counterfactual_overrides",
    "simulate_counterfactual",
    "validate_counterfactual_overrides",
]
