"""Timeline and provenance graph reconstruction tests."""

from __future__ import annotations

from contracts import compute_payload_hash
from contracts.fixtures import build_authorized_39_purchase_fixture

from ghostpay.forensics import build_provenance_graph as compat_build_provenance_graph
from ghostpay.forensics import build_timeline as compat_build_timeline
from ghostpay.provenance import build_provenance_graph
from ghostpay.testing import make_test_trace
from ghostpay.timelines import build_timeline


def test_timeline_reconstruction_from_fixture() -> None:
    fixture = build_authorized_39_purchase_fixture()
    events = fixture["events"]
    evidence = [
        rec.model_copy(update={"content_hash": compute_payload_hash(rec.content)})
        for rec in fixture["evidence_records"]
    ]

    timeline = build_timeline(events, evidence)
    assert compat_build_timeline(events, evidence) == timeline
    assert len(timeline) == len(events)
    assert [e.sequence_number for e in timeline] == [1, 2, 3, 4]
    assert all(e.integrity_verified for e in timeline)
    assert "proposal created" in timeline[0].summary.lower()
    assert "capture verified" in timeline[3].summary.lower()


def test_provenance_graph_construction() -> None:
    trace = make_test_trace(with_events=True)
    graph = build_provenance_graph(trace)
    compat_graph = compat_build_provenance_graph(trace)
    assert len(compat_graph.edges) == len(graph.edges)

    assert str(trace.payment_intent_id) in graph.nodes
    assert len(graph.edges) > 0
    relationships = [e.relationship for e in graph.edges]
    assert "BOUND_TO" in relationships
    assert "GOVERNS" in relationships
    assert "RECORDS" in relationships
