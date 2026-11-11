"""Mandatory Trace and Provenance Tests (T01 - T06)."""

from __future__ import annotations

import pytest
from contracts.fixtures import (
    TENANT_ALPHA_ID,
    TENANT_BETA_ID,
)

from ghostpay.domain.exceptions import CrossTenantAccessError, IntegrityError
from ghostpay.ingestion.adapter import TraceIngestionAdapter
from ghostpay.ingestion.validation import TraceValidator
from ghostpay.testing import make_test_trace


def test_t01_valid_guardian_event_stream_reconstructs_expected_timeline(
    ingestion_adapter: TraceIngestionAdapter,
) -> None:
    """T01: Valid Guardian event stream reconstructs the expected timeline."""
    trace = make_test_trace(with_events=True)
    ingested = ingestion_adapter.build_trace(
        tenant_id=trace.tenant_id,
        agent_id=trace.agent_id,
        payment_intent_id=trace.payment_intent_id,
        events=trace.ordered_events,
        quote_snapshot=trace.quote_snapshot,
        evidence_records=trace.authorization_evidence,
        recorded_decision=trace.recorded_decision,
        recorded_passport=trace.recorded_passport,
        recorded_merchant=trace.recorded_merchant,
        payment_intent=trace.payment_intent,
    )
    assert ingested.integrity_status == "VALID"
    assert len(ingested.ordered_events) == 2
    assert ingested.ordered_events[0].sequence_number == 1
    assert ingested.ordered_events[1].sequence_number == 2


def test_t02_tampered_financial_event_is_rejected_or_quarantined(
    ingestion_adapter: TraceIngestionAdapter,
) -> None:
    """T02: Tampered financial event is rejected or quarantined."""
    trace = make_test_trace(with_events=True, tampered_event=True)

    # 1. Non-strict mode quarantines trace with TAMPERED status
    ingested = ingestion_adapter.build_trace(
        tenant_id=trace.tenant_id,
        agent_id=trace.agent_id,
        payment_intent_id=trace.payment_intent_id,
        events=trace.ordered_events,
        quote_snapshot=trace.quote_snapshot,
        evidence_records=trace.authorization_evidence,
        strict_integrity=False,
    )
    assert ingested.integrity_status == "TAMPERED"
    assert any("EVENT_HASH_TAMPERED" in err for err in ingested.missing_evidence)

    # 2. Strict integrity mode raises IntegrityError
    with pytest.raises(IntegrityError):
        ingestion_adapter.build_trace(
            tenant_id=trace.tenant_id,
            agent_id=trace.agent_id,
            payment_intent_id=trace.payment_intent_id,
            events=trace.ordered_events,
            quote_snapshot=trace.quote_snapshot,
            evidence_records=trace.authorization_evidence,
            strict_integrity=True,
        )


def test_t03_duplicate_identical_event_ingestion_is_idempotent(
    ingestion_adapter: TraceIngestionAdapter,
) -> None:
    """T03: Duplicate identical event ingestion is idempotent."""
    trace = make_test_trace(with_events=True)
    ev = trace.ordered_events[0]

    # Ingest once
    res1 = ingestion_adapter.ingest_event(TENANT_ALPHA_ID, ev)
    # Ingest identical copy
    res2 = ingestion_adapter.ingest_event(TENANT_ALPHA_ID, ev)

    assert res1.id == res2.id
    assert res1.event_hash == res2.event_hash


def test_t04_conflicting_duplicate_event_produces_integrity_error(
    ingestion_adapter: TraceIngestionAdapter,
) -> None:
    """T04: Conflicting duplicate event produces an integrity error."""
    trace = make_test_trace(with_events=True)
    ev = trace.ordered_events[0]

    ingestion_adapter.ingest_event(TENANT_ALPHA_ID, ev)

    # Create conflicting event with same ID but different payload
    conflicting = ev.model_copy(
        update={
            "payload": {"amount_minor": 999999},
            "event_hash": "conflicting-hash-9999999999999",
        }
    )

    with pytest.raises(IntegrityError) as exc_info:
        ingestion_adapter.ingest_event(TENANT_ALPHA_ID, conflicting)

    assert "Conflicting duplicate event" in str(exc_info.value)


def test_t05_missing_event_sequence_is_explicitly_detected(
    ingestion_adapter: TraceIngestionAdapter,
) -> None:
    """T05: Missing event sequence is explicitly detected."""
    trace = make_test_trace(with_events=True, missing_sequence=True)

    is_valid, errors = TraceValidator.validate_event_chain(trace.ordered_events)
    assert is_valid is False
    assert any("MISSING_EVENT_SEQUENCE" in err for err in errors)

    ingested = ingestion_adapter.build_trace(
        tenant_id=trace.tenant_id,
        agent_id=trace.agent_id,
        payment_intent_id=trace.payment_intent_id,
        events=trace.ordered_events,
        strict_integrity=False,
    )
    assert any("MISSING_EVENT_SEQUENCE" in err for err in ingested.missing_evidence)


def test_t06_cross_tenant_trace_access_is_denied(
    ingestion_adapter: TraceIngestionAdapter,
) -> None:
    """T06: Cross-tenant trace access is denied."""
    trace = make_test_trace(tenant_id=TENANT_ALPHA_ID)

    # Attempting to ingest tenant alpha trace under tenant beta
    with pytest.raises((CrossTenantAccessError, PermissionError)):
        ingestion_adapter.build_trace(
            tenant_id=TENANT_BETA_ID,
            agent_id=trace.agent_id,
            payment_intent_id=trace.payment_intent_id,
            events=trace.ordered_events,
            payment_intent=trace.payment_intent,
        )
