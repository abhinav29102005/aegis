"""Evidence provenance graph models and builder for DisputeOS."""

from __future__ import annotations

from uuid import UUID

from contracts import DisputeCase, EvidenceRecord, EvidenceSourceType
from pydantic import BaseModel, Field
from security import assert_same_tenant


class EvidenceNode(BaseModel):
    """Single evidence node in a dispute's provenance graph."""

    id: UUID
    source_type: EvidenceSourceType
    title: str
    source_ref: str
    content_hash: str
    is_synthetic: bool


class EvidenceEdge(BaseModel):
    """Directed relationship between two nodes (or a node and its dispute case)."""

    from_id: str
    to_id: str
    relation: str


class EvidenceGraph(BaseModel):
    """Tenant-scoped evidence provenance graph for a single DisputeCase."""

    dispute_case_id: UUID
    tenant_id: UUID
    correlation_id: UUID
    nodes: list[EvidenceNode] = Field(default_factory=list)
    edges: list[EvidenceEdge] = Field(default_factory=list)


_LIFECYCLE_STAGES: tuple[tuple[EvidenceSourceType, str], ...] = (
    (EvidenceSourceType.PROPOSAL, "PROPOSED_TO"),
    (EvidenceSourceType.QUOTE, "QUOTED_INTO"),
    (EvidenceSourceType.POLICY_DECISION, "EVALUATED_FOR"),
    (EvidenceSourceType.HUMAN_APPROVAL, "APPROVED_FOR"),
    (EvidenceSourceType.PAYPAL_ORDER, "ORDERED_AS"),
    (EvidenceSourceType.PAYPAL_CAPTURE, "CAPTURED_AS"),
    (EvidenceSourceType.PAYPAL_WEBHOOK, "CONFIRMED_BY_WEBHOOK"),
    (EvidenceSourceType.CARRIER_TRACKING, "SHIPPED_WITH"),
    (EvidenceSourceType.DELIVERY_RECEIPT, "DELIVERED_WITH"),
    (EvidenceSourceType.CUSTOMER_MESSAGE, "DISPUTED_IN"),
)


def build_evidence_graph(case: DisputeCase, evidence: list[EvidenceRecord]) -> EvidenceGraph:
    """Build a tenant-verified evidence provenance graph for a dispute case."""
    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []
    by_type: dict[EvidenceSourceType, list[EvidenceRecord]] = {}

    for rec in evidence:
        assert_same_tenant(case.tenant_id, rec.tenant_id, "evidence_record")
        nodes.append(
            EvidenceNode(
                id=rec.id,
                source_type=rec.source_type,
                title=rec.title,
                source_ref=rec.source_ref,
                content_hash=rec.content_hash,
                is_synthetic=rec.is_synthetic,
            )
        )
        edges.append(
            EvidenceEdge(
                from_id=str(rec.id),
                to_id=str(case.id),
                relation="EVIDENCE_FOR_CASE",
            )
        )
        by_type.setdefault(rec.source_type, []).append(rec)

    present_stages = [
        (stage_type, relation)
        for stage_type, relation in _LIFECYCLE_STAGES
        if stage_type in by_type
    ]
    for idx in range(len(present_stages) - 1):
        src_type, relation = present_stages[idx]
        dst_type, _ = present_stages[idx + 1]
        for src_rec in by_type[src_type]:
            for dst_rec in by_type[dst_type]:
                edges.append(
                    EvidenceEdge(
                        from_id=str(src_rec.id),
                        to_id=str(dst_rec.id),
                        relation=relation,
                    )
                )

    return EvidenceGraph(
        dispute_case_id=case.id,
        tenant_id=case.tenant_id,
        correlation_id=case.correlation_id,
        nodes=nodes,
        edges=edges,
    )
