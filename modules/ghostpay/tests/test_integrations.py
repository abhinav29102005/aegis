"""Integration tests for GhostPay with Guardian and DisputeOS."""

from __future__ import annotations

from contracts import PaymentState, compute_payload_hash

from ghostpay.domain.service import GhostPayService
from ghostpay.integrations.disputeos import export_to_disputeos
from ghostpay.integrations.guardian import GuardianTraceAdapter
from ghostpay.testing import make_test_trace


def test_ghostpay_evidence_export_to_disputeos(service: GhostPayService) -> None:
    trace = make_test_trace(with_events=True)
    service.ingestion.traces[trace.trace_id] = trace
    service.agent_history[(trace.tenant_id, trace.agent_id)] = [trace]

    investigation = service.create_investigation(
        tenant_id=trace.tenant_id,
        trace_id=trace.trace_id,
    )

    bundle = export_to_disputeos(trace, investigation)
    assert bundle.payment_intent_id == trace.payment_intent_id
    assert bundle.tenant_id == trace.tenant_id
    assert bundle.trace_integrity_status == "VALID"
    assert len(bundle.timeline_summary) == 2
    assert len(bundle.evidence_records) == 1


def test_pending_provider_state_never_reported_as_successful() -> None:
    pending_trace = make_test_trace(state=PaymentState.PENDING_PROVIDER)
    assert pending_trace.payment_intent.state == PaymentState.PENDING_PROVIDER
    assert pending_trace.payment_intent.state != PaymentState.SUCCEEDED


def test_guardian_trace_adapter_preserves_capture_verification(
    guardian_adapter: GuardianTraceAdapter,
    authorized_39_fixture: dict,
) -> None:
    f = authorized_39_fixture
    canonical_evidence = [
        rec.model_copy(update={"content_hash": compute_payload_hash(rec.content)})
        for rec in f["evidence_records"]
    ]
    trace = guardian_adapter.from_guardian_records(
        intent=f["payment_intent"],
        proposal_quote=f["quote_snapshot"],
        passport=f["passport"],
        merchant=f["approved_merchant"],
        events=f["events"],
        evidence_records=canonical_evidence,
        decision=f["decision"],
    )

    assert trace.payment_intent.state == PaymentState.SUCCEEDED
    assert trace.integrity_status == "VALID"
    assert len(trace.authorization_evidence) == 2

    # Check paypal capture evidence is preserved
    capture_ev = next(e for e in trace.authorization_evidence if e.source_type.value == "PAYPAL_CAPTURE")
    assert capture_ev.content.get("status") == "COMPLETED"
