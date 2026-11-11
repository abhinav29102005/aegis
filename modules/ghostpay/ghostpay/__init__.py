"""GhostPay — Deterministic replay, counterfactual policy simulation, anomaly detection, and evidence provenance."""

from ghostpay.anomalies import detect_anomalies
from ghostpay.api import create_ghostpay_router, router
from ghostpay.counterfactual import (
    ALLOWED_OVERRIDE_FIELDS,
    IMMUTABLE_OVERRIDE_FIELDS,
    ValidatedCounterfactualOverrides,
    apply_validated_counterfactual_overrides,
    simulate_counterfactual,
    validate_counterfactual_overrides,
)
from ghostpay.errors import (
    GhostPayError,
    OverrideValidationError,
    ReplayExecutionForbiddenError,
    UnsupportedPolicyVersionError,
)
from ghostpay.provenance import (
    check_missing_evidence,
    enforce_request_tenancy,
    verify_evidence_digest,
    verify_provenance_and_integrity,
    verify_quote_snapshot_integrity,
)
from ghostpay.replay import (
    DEFAULT_POLICY_VERSION,
    SUPPORTED_POLICY_VERSIONS,
    ReplayEngine,
    evaluate_deterministic_policy,
    get_registered_policy_versions,
    resolve_policy_evaluator,
)
from ghostpay.repository import GhostPayReplayRepository
from ghostpay.timelines import build_timeline

__all__ = [
    "ALLOWED_OVERRIDE_FIELDS",
    "DEFAULT_POLICY_VERSION",
    "IMMUTABLE_OVERRIDE_FIELDS",
    "SUPPORTED_POLICY_VERSIONS",
    "GhostPayError",
    "GhostPayReplayRepository",
    "OverrideValidationError",
    "ReplayEngine",
    "ReplayExecutionForbiddenError",
    "UnsupportedPolicyVersionError",
    "ValidatedCounterfactualOverrides",
    "apply_validated_counterfactual_overrides",
    "build_timeline",
    "check_missing_evidence",
    "create_ghostpay_router",
    "detect_anomalies",
    "enforce_request_tenancy",
    "evaluate_deterministic_policy",
    "get_registered_policy_versions",
    "resolve_policy_evaluator",
    "router",
    "simulate_counterfactual",
    "validate_counterfactual_overrides",
    "verify_evidence_digest",
    "verify_provenance_and_integrity",
    "verify_quote_snapshot_integrity",
]

