"""Timeline and provenance graph reconstruction tests."""

from __future__ import annotations

from contracts.fixtures import build_authorized_39_purchase_fixture

from ghostpay.provenance.verifier import build_provenance_graph
from ghostpay.testing import make_test_trace
from ghostpay.timelines.builder import build_timeline


def test_timeline_reconstruction_from_fixture() -> None:
    fixture = build_authorized_39_purchase_fixture()
    events = fixture["events"]
    evidence = fixture["evidence_records"]

    timeline = build_timeline(events, evidence)
    assert len(timeline) == len(events)
    assert [e.sequence_number for e in timeline] == [1, 2, 3, 4]
    assert all(e.integrity_verified for e in timeline)
    assert "proposal created" in timeline[0].summary.lower()
    assert "capture verified" in timeline[3].summary.lower()


def test_provenance_graph_construction() -> None:
    trace = make_test_trace(with_events=True)
    graph = build_provenance_graph(trace)

    assert str(trace.payment_intent_id) in graph.nodes
    assert len(graph.edges) > 0
    relationships = [e.relationship for e in graph.edges]
    assert "BOUND_TO" in relationships
    assert "GOVERNS" in relationships
    assert "RECORDS" in relationships
