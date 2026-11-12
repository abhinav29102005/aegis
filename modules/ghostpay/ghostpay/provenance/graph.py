"""Lightweight provenance graph construction for GhostPay traces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ghostpay.domain.models import PaymentTrace


@dataclass
class ProvenanceNode:
    """Single node in a transaction provenance graph."""

    node_id: str
    node_type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProvenanceEdge:
    """Directed relationship edge between two provenance nodes."""

    source_id: str
    target_id: str
    relationship: str
    is_inferred: bool = False


@dataclass
class ProvenanceGraph:
    """Directed provenance graph linking mandates, proposals, quotes, decisions, and events."""

    nodes: dict[str, ProvenanceNode] = field(default_factory=dict)
    edges: list[ProvenanceEdge] = field(default_factory=list)

    def add_node(self, node_id: str, node_type: str, properties: dict[str, Any] | None = None) -> None:
        self.nodes[node_id] = ProvenanceNode(node_id, node_type, properties or {})

    def add_edge(self, source_id: str, target_id: str, relationship: str, is_inferred: bool = False) -> None:
        self.edges.append(ProvenanceEdge(source_id, target_id, relationship, is_inferred))


def build_provenance_graph(trace: PaymentTrace) -> ProvenanceGraph:
    """Build a directed provenance graph representing verified trace relationships."""
    graph = ProvenanceGraph()

    intent_id = str(trace.payment_intent_id)
    graph.add_node(
        intent_id,
        "PAYMENT_INTENT",
        {"state": trace.payment_intent.state if trace.payment_intent else "UNKNOWN"},
    )

    if trace.recorded_passport:
        passport_id = str(trace.recorded_passport.id)
        graph.add_node(passport_id, "SPENDING_PASSPORT", {"status": trace.recorded_passport.status.value})
        graph.add_edge(passport_id, intent_id, "GOVERNS")

    if trace.quote_snapshot:
        quote_id = str(trace.quote_snapshot.id)
        graph.add_node(
            quote_id,
            "QUOTE",
            {"quote_hash": trace.quote_snapshot.quote_hash, "amount_minor": trace.quote_snapshot.amount_minor},
        )
        graph.add_edge(quote_id, intent_id, "BOUND_TO")

    if trace.recorded_decision:
        decision_id = str(trace.recorded_decision.id)
        graph.add_node(decision_id, "POLICY_DECISION", {"outcome": trace.recorded_decision.outcome.value})
        graph.add_edge(decision_id, intent_id, "EVALUATED_FOR")

    prev_ev_id: str | None = None
    for ev in trace.ordered_events:
        ev_id = str(ev.id)
        graph.add_node(ev_id, "FINANCIAL_EVENT", {"type": ev.event_type.value, "seq": ev.sequence_number})
        graph.add_edge(ev_id, intent_id, "RECORDS")
        if prev_ev_id:
            graph.add_edge(prev_ev_id, ev_id, "CHAINED_TO")
        prev_ev_id = ev_id

    return graph
