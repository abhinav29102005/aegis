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
from ghostpay.counterfactual import simulate_counterfactual
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
from ghostpay.forensics import (
    ProvenanceEdge,
    ProvenanceGraph,
    ProvenanceNode,
    build_provenance_graph,
    build_timeline,
    correlate_evidence_ids,
    format_event_summary,
    verify_evidence_digest,
    verify_provenance_and_integrity,
    verify_quote_snapshot_integrity,
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
)
from ghostpay.replay import ReplayEngine, evaluate_deterministic_policy
from ghostpay.timemachine import (
    CounterfactualPolicy,
    PolicyComparisonEntry,
    PolicyComparisonReport,
    PolicyTimeMachine,
    compare_policies,
    generate_safeguard_recommendations,
)

__all__ = [
    # Domain & Services
    "GhostPayService",
    "PaymentTrace",
    "InvestigationReport",
    "GhostPayError",
    "IntegrityError",
    "MissingEvidenceError",
    "InsufficientHistoryError",
    "CrossTenantAccessError",
    "IllegalSideEffectError",
    "TraceNotFoundError",
    "InvestigationNotFoundError",
    # Policy Time Machine
    "PolicyTimeMachine",
    "ReplayEngine",
    "CounterfactualPolicy",
    "PolicyComparisonEntry",
    "PolicyComparisonReport",
    "compare_policies",
    "generate_safeguard_recommendations",
    "evaluate_deterministic_policy",
    "simulate_counterfactual",
    # Agent DNA
    "AgentDNADetector",
    "AgentBehaviorProfile",
    "AgentDNAAnomalyResult",
    "AgentFeatureVector",
    "build_agent_profile",
    "extract_agent_features",
    "format_agent_dna_explanation",
    # Forensics & Provenance
    "build_timeline",
    "format_event_summary",
    "correlate_evidence_ids",
    "ProvenanceNode",
    "ProvenanceEdge",
    "ProvenanceGraph",
    "build_provenance_graph",
    "verify_evidence_digest",
    "verify_quote_snapshot_integrity",
    "verify_provenance_and_integrity",
    "check_missing_evidence",
    "detect_anomalies",
    "enforce_request_tenancy",
    # Ingestion & Integrations
    "TraceIngestionAdapter",
    "TraceValidator",
    "GuardianTraceAdapter",
    "DisputeOSEvidenceBundle",
    "export_to_disputeos",
    # API
    "create_ghostpay_router",
    "router",
]
