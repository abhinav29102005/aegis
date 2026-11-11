"""GhostPay forensic investigation and intelligence service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from contracts import (
    ApprovalRecord,
    AuthorizationDecision,
    EvidenceRecord,
    FinancialEvent,
    Merchant,
    PaymentIntent,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    ReplayTimelineEntry,
    SpendingPassport,
)
from ghostpay.agentdna.detector import AgentDNAAnomalyResult, AgentDNADetector
from ghostpay.agentdna.explanations import format_agent_dna_explanation
from ghostpay.agentdna.profiles import AgentBehaviorProfile, build_agent_profile
from ghostpay.domain.exceptions import (
    CrossTenantAccessError,
    InvestigationNotFoundError,
    TraceNotFoundError,
)
from ghostpay.domain.models import InvestigationReport, PaymentTrace
from ghostpay.forensics.anomalies import detect_anomalies
from ghostpay.forensics.timeline import build_timeline
from ghostpay.ingestion.adapter import TraceIngestionAdapter
from ghostpay.timemachine.policies import CounterfactualPolicy
from ghostpay.timemachine.recommendations import generate_safeguard_recommendations
from ghostpay.timemachine.replay import PolicyTimeMachine

if TYPE_CHECKING:
    from ghostpay.timemachine.comparison import PolicyComparisonReport


class GhostPayService:
    """Primary orchestration service for forensic replay, Agent DNA, and investigation reporting."""

    def __init__(
        self,
        ingestion_adapter: TraceIngestionAdapter | None = None,
        agent_dna_detector: AgentDNADetector | None = None,
    ) -> None:
        self.ingestion = ingestion_adapter or TraceIngestionAdapter()
        self.dna_detector = agent_dna_detector or AgentDNADetector()
        self.investigations: dict[UUID, InvestigationReport] = {}
        self.agent_history: dict[tuple[UUID, UUID], list[PaymentTrace]] = {}  # (tenant_id, agent_id) -> traces

    # -------------------------------------------------------------------------
    # Ingestion & Trace Management
    # -------------------------------------------------------------------------
    def ingest_trace(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        payment_intent_id: UUID,
        events: list[FinancialEvent],
        quote_snapshot: QuoteSnapshot | None = None,
        evidence_records: list[EvidenceRecord] | None = None,
        recorded_decision: AuthorizationDecision | None = None,
        recorded_passport: SpendingPassport | None = None,
        recorded_merchant: Merchant | None = None,
        approval_record: ApprovalRecord | None = None,
        payment_intent: PaymentIntent | None = None,
        policy_version: str = "policy-v1",
        strict_integrity: bool = False,
    ) -> PaymentTrace:
        trace = self.ingestion.build_trace(
            tenant_id=tenant_id,
            agent_id=agent_id,
            payment_intent_id=payment_intent_id,
            events=events,
            quote_snapshot=quote_snapshot,
            evidence_records=evidence_records,
            recorded_decision=recorded_decision,
            recorded_passport=recorded_passport,
            recorded_merchant=recorded_merchant,
            approval_record=approval_record,
            payment_intent=payment_intent,
            policy_version=policy_version,
            strict_integrity=strict_integrity,
        )
        key = (tenant_id, agent_id)
        if key not in self.agent_history:
            self.agent_history[key] = []
        self.agent_history[key].append(trace)
        return trace

    def get_trace(self, tenant_id: UUID, trace_id: UUID) -> PaymentTrace:
        trace = self.ingestion.get_trace(trace_id)
        if trace is None:
            raise TraceNotFoundError(f"PaymentTrace {trace_id} not found")
        if trace.tenant_id != tenant_id:
            raise CrossTenantAccessError(
                f"Tenant isolation breach: trace tenant {trace.tenant_id} != {tenant_id}"
            )
        return trace

    def get_timeline(self, tenant_id: UUID, trace_id: UUID) -> list[ReplayTimelineEntry]:
        trace = self.get_trace(tenant_id, trace_id)
        return build_timeline(trace.ordered_events, trace.authorization_evidence)

    # -------------------------------------------------------------------------
    # Policy Time Machine Replay
    # -------------------------------------------------------------------------
    def replay(self, request: ReplayRequest) -> ReplayResult:
        """Execute deterministic, read-only counterfactual replay."""
        return PolicyTimeMachine.replay(request)

    def compare_policies(
        self,
        request: ReplayRequest,
        policies: list[CounterfactualPolicy],
    ) -> PolicyComparisonReport:
        """Compare multiple counterfactual policies against a single transaction."""
        from ghostpay.timemachine.comparison import compare_policies as _compare
        return _compare(request, policies)

    # -------------------------------------------------------------------------
    # Agent DNA Profiling & Anomaly Detection
    # -------------------------------------------------------------------------
    def get_agent_profile(self, tenant_id: UUID, agent_id: UUID) -> AgentBehaviorProfile:
        history = self.agent_history.get((tenant_id, agent_id), [])
        return build_agent_profile(tenant_id, agent_id, history)

    def analyze_agent(
        self,
        tenant_id: UUID,
        agent_id: UUID,
        target_trace_id: UUID,
    ) -> AgentDNAAnomalyResult:
        target_trace = self.get_trace(tenant_id, target_trace_id)
        history = self.agent_history.get((tenant_id, agent_id), [])

        # Build profile strictly excluding the target trace to prevent data leakage
        profile = build_agent_profile(
            tenant_id,
            agent_id,
            history,
            cutoff_time=target_trace.created_at,
            exclude_trace_id=target_trace.trace_id,
        )
        return self.dna_detector.detect(profile, target_trace)

    # -------------------------------------------------------------------------
    # End-to-End Investigation Reporting
    # -------------------------------------------------------------------------
    def create_investigation(
        self,
        *,
        tenant_id: UUID,
        trace_id: UUID,
        counterfactual_policies: list[CounterfactualPolicy] | None = None,
    ) -> InvestigationReport:
        trace = self.get_trace(tenant_id, trace_id)
        timeline = build_timeline(trace.ordered_events, trace.authorization_evidence)

        # 1. Anomaly detection (trace-level)
        dummy_req = trace.to_replay_request()
        trace_anomalies = detect_anomalies(dummy_req, timeline) if dummy_req else []

        # 2. Agent DNA profiling & detection
        history = self.agent_history.get((tenant_id, trace.agent_id), [])
        profile = build_agent_profile(
            tenant_id,
            trace.agent_id,
            history,
            cutoff_time=trace.created_at,
            exclude_trace_id=trace.trace_id,
        )
        dna_result = self.dna_detector.detect(profile, trace)

        # 3. Counterfactual replays
        replay_results: list[ReplayResult] = []
        if dummy_req and counterfactual_policies:
            for pol in counterfactual_policies:
                pol_req = dummy_req.model_copy(update={"counterfactual_overrides": pol.to_overrides_dict()})
                replay_results.append(PolicyTimeMachine.replay(pol_req))

        # 4. Safeguard recommendations
        suggested_safeguards: list[str] = []
        if replay_results:
            for r in replay_results:
                suggested_safeguards.extend(generate_safeguard_recommendations(r))
        suggested_safeguards = list(dict.fromkeys(suggested_safeguards))  # dedup preserving order

        # 5. Distinct categorization of findings
        verified_facts: list[str] = [
            f"Event chain integrity: {trace.integrity_status}",
            f"Total events recorded: {len(trace.ordered_events)}",
            f"Timeline stages verified: {sum(1 for e in timeline if e.integrity_verified)}/{len(timeline)}",
        ]
        if trace.recorded_decision:
            verified_facts.append(f"Recorded Guardian decision: {trace.recorded_decision.outcome.value}")

        deterministic_outcomes: list[str] = [
            f"Policy {trace.policy_version} original evaluation outcome: {trace.recorded_decision.outcome.value if trace.recorded_decision else 'UNKNOWN'}"
        ]
        for r in replay_results:
            deterministic_outcomes.append(
                f"Counterfactual replay under policy: {r.recomputed_outcome.value} (Drift: {r.drift_detected})"
            )

        statistical_signals: list[str] = [
            f"Agent DNA status: {dna_result.status} (Score: {dna_result.anomaly_score})"
        ]
        for sig in dna_result.signals:
            statistical_signals.append(f"DNA Signal: {sig.get('signal_type')}")

        ai_explanations: list[str] = [
            format_agent_dna_explanation(dna_result),
        ]

        inv_id = uuid4()
        evidence_refs = [e.id for e in trace.authorization_evidence]

        report = InvestigationReport(
            investigation_id=inv_id,
            tenant_id=tenant_id,
            trace_id=trace.trace_id,
            payment_intent_id=trace.payment_intent_id,
            trace_integrity_status=trace.integrity_status,
            timeline=timeline,
            detected_anomalies=trace_anomalies,
            agent_dna_signals=dna_result.signals,
            counterfactual_replay_results=replay_results,
            suggested_safeguards=suggested_safeguards,
            evidence_references=evidence_refs,
            missing_evidence=trace.missing_evidence,
            confidence_limitations=[
                "Agent DNA anomaly signals are statistical indicators and do not constitute proof of fraud.",
                "Guardian remains the authoritative spending policy governance boundary.",
            ],
            verified_facts=verified_facts,
            deterministic_policy_outcomes=deterministic_outcomes,
            statistical_anomaly_signals=statistical_signals,
            ai_explanations=ai_explanations,
        )
        self.investigations[inv_id] = report
        return report

    def get_investigation(self, tenant_id: UUID, investigation_id: UUID) -> InvestigationReport:
        report = self.investigations.get(investigation_id)
        if report is None:
            raise InvestigationNotFoundError(f"InvestigationReport {investigation_id} not found")
        if report.tenant_id != tenant_id:
            raise CrossTenantAccessError(
                f"Tenant isolation breach: investigation tenant {report.tenant_id} != {tenant_id}"
            )
        return report
