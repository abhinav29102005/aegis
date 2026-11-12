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


def _is_causally_linked(src: EvidenceRecord, dst: EvidenceRecord) -> bool:
    """Determine whether two evidence records have causal linkage."""
    if src.payment_intent_id and dst.payment_intent_id:
        return src.payment_intent_id == dst.payment_intent_id
    if src.correlation_id and dst.correlation_id:
        return src.correlation_id == dst.correlation_id
    if src.source_ref and (src.source_ref in dst.source_ref or src.source_ref in str(dst.content)):
        return True
    if dst.source_ref and (dst.source_ref in src.source_ref or dst.source_ref in str(src.content)):
        return True
    return src.collected_at <= dst.collected_at


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
        src_records = by_type[src_type]
        dst_records = by_type[dst_type]

        matched_any = False
        for src_rec in src_records:
            for dst_rec in dst_records:
                if _is_causally_linked(src_rec, dst_rec):
                    matched_any = True
                    edges.append(
                        EvidenceEdge(
                            from_id=str(src_rec.id),
                            to_id=str(dst_rec.id),
                            relation=relation,
                        )
                    )
        if not matched_any and src_records and dst_records:
            # Fallback to single chronological pair to maintain pipeline connectivity
            edges.append(
                EvidenceEdge(
                    from_id=str(src_records[0].id),
                    to_id=str(dst_records[0].id),
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
