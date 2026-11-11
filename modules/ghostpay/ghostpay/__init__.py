"""GhostPay — Policy Time Machine, Agent DNA, and Financial Forensics for AgentPay Nexus."""

from ghostpay.agentdna import (
    AgentBehaviorProfile,
    AgentDNAAnomalyResult,
    AgentDNADetector,
    AgentFeatureVector,
    build_agent_profile,
    extract_agent_features,
    format_agent_dna_explanation,
)
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
from ghostpay.domain import (
    CrossTenantAccessError,
    GhostPayError,
    GhostPayService,
    IllegalSideEffectError,
    InsufficientHistoryError,
    IntegrityError,
    InvestigationNotFoundError,
    InvestigationReport,
    MissingEvidenceError,
    PaymentTrace,
    TraceNotFoundError,
)
from ghostpay.errors import (
    OverrideValidationError,
    ReplayExecutionForbiddenError,
    UnsupportedPolicyVersionError,
)
from ghostpay.forensics import (
    ProvenanceEdge,
    ProvenanceGraph,
    ProvenanceNode,
    build_provenance_graph,
    correlate_evidence_ids,
    format_event_summary,
)
from ghostpay.ingestion import TraceIngestionAdapter, TraceValidator
from ghostpay.integrations import (
    DisputeOSEvidenceBundle,
    GuardianTraceAdapter,
    export_to_disputeos,
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
from ghostpay.timemachine import (
    CounterfactualPolicy,
    PolicyComparisonEntry,
    PolicyComparisonReport,
    PolicyTimeMachine,
    compare_policies,
    generate_safeguard_recommendations,
)

__all__ = [
    "ALLOWED_OVERRIDE_FIELDS",
    "DEFAULT_POLICY_VERSION",
    "IMMUTABLE_OVERRIDE_FIELDS",
    "SUPPORTED_POLICY_VERSIONS",
    "AgentBehaviorProfile",
    "AgentDNAAnomalyResult",
    "AgentDNADetector",
    "AgentFeatureVector",
    "CounterfactualPolicy",
    "CrossTenantAccessError",
    "DisputeOSEvidenceBundle",
    "GhostPayError",
    "GhostPayReplayRepository",
    "GhostPayService",
    "GuardianTraceAdapter",
    "IllegalSideEffectError",
    "InsufficientHistoryError",
    "IntegrityError",
    "InvestigationNotFoundError",
    "InvestigationReport",
    "MissingEvidenceError",
    "OverrideValidationError",
    "PaymentTrace",
    "PolicyComparisonEntry",
    "PolicyComparisonReport",
    "PolicyTimeMachine",
    "ProvenanceEdge",
    "ProvenanceGraph",
    "ProvenanceNode",
    "ReplayEngine",
    "ReplayExecutionForbiddenError",
    "TraceIngestionAdapter",
    "TraceNotFoundError",
    "TraceValidator",
    "UnsupportedPolicyVersionError",
    "ValidatedCounterfactualOverrides",
    "apply_validated_counterfactual_overrides",
    "build_agent_profile",
    "build_provenance_graph",
    "build_timeline",
    "check_missing_evidence",
    "compare_policies",
    "correlate_evidence_ids",
    "create_ghostpay_router",
    "detect_anomalies",
    "enforce_request_tenancy",
    "evaluate_deterministic_policy",
    "export_to_disputeos",
    "extract_agent_features",
    "format_agent_dna_explanation",
    "format_event_summary",
    "generate_safeguard_recommendations",
    "get_registered_policy_versions",
    "resolve_policy_evaluator",
    "router",
    "simulate_counterfactual",
    "validate_counterfactual_overrides",
    "verify_evidence_digest",
    "verify_provenance_and_integrity",
    "verify_quote_snapshot_integrity",
]
