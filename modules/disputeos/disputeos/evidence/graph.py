"""Evidence provenance graph models and causal builder for DisputeOS."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from contracts import DisputeCase, EvidenceRecord, EvidenceSourceType
from pydantic import BaseModel, Field
from security import assert_same_tenant

from disputeos.ingestion.normalizer import verify_evidence_digest


class EvidenceNode(BaseModel):
    """Single evidence node in a dispute's provenance graph."""

    id: UUID
    source_type: EvidenceSourceType
    title: str
    source_ref: str
    content_hash: str
    is_synthetic: bool
    collected_at: datetime | None = None
    payment_intent_id: UUID | None = None
    correlation_id: UUID | None = None
    digest_verified: bool = True


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

_STAGE_INDEX: dict[EvidenceSourceType, int] = {
    stage_type: idx for idx, (stage_type, _) in enumerate(_LIFECYCLE_STAGES)
}
_STAGE_RELATION: dict[int, str] = {
    idx: relation for idx, (_, relation) in enumerate(_LIFECYCLE_STAGES)
}
_CAUSAL_REF_KEYS: tuple[str, ...] = (
    "proposal_id",
    "quote_snapshot_id",
    "paypal_order_id",
    "paypal_capture_id",
    "tracking_number",
)


def _is_causally_linked(src: EvidenceRecord, dst: EvidenceRecord) -> bool:
    """Return True if src causally precedes dst on intent/correlation, time, and artifact refs."""
    if src.payment_intent_id is not None and dst.payment_intent_id is not None:
        if src.payment_intent_id != dst.payment_intent_id:
            return False
    elif src.correlation_id != dst.correlation_id:
        return False

    if src.collected_at > dst.collected_at:
        return False

    for key in _CAUSAL_REF_KEYS:
        src_val = src.content.get(key)
        dst_val = dst.content.get(key)
        if src_val and dst_val and str(src_val).strip() != str(dst_val).strip():
            return False

    return True


def build_evidence_graph(case: DisputeCase, evidence: list[EvidenceRecord]) -> EvidenceGraph:
    """Build a tenant-verified, causally linked evidence provenance graph for a dispute case."""
    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []
    by_stage: dict[int, list[EvidenceRecord]] = {}

    sorted_evidence = sorted(
        evidence,
        key=lambda rec: (
            rec.collected_at,
            _STAGE_INDEX.get(rec.source_type, len(_LIFECYCLE_STAGES)),
            str(rec.id),
        ),
    )

    for rec in sorted_evidence:
        assert_same_tenant(case.tenant_id, rec.tenant_id, "evidence_record")
        nodes.append(
            EvidenceNode(
                id=rec.id,
                source_type=rec.source_type,
                title=rec.title,
                source_ref=rec.source_ref,
                content_hash=rec.content_hash,
                is_synthetic=rec.is_synthetic,
                collected_at=rec.collected_at,
                payment_intent_id=rec.payment_intent_id,
                correlation_id=rec.correlation_id,
                digest_verified=verify_evidence_digest(rec),
            )
        )
        edges.append(
            EvidenceEdge(
                from_id=str(rec.id),
                to_id=str(case.id),
                relation="EVIDENCE_FOR_CASE",
            )
        )
        stage_idx = _STAGE_INDEX.get(rec.source_type)
        if stage_idx is not None:
            by_stage.setdefault(stage_idx, []).append(rec)

    for dst_rec in sorted_evidence:
        dst_stage = _STAGE_INDEX.get(dst_rec.source_type)
        if dst_stage is None:
            continue
        for cand_stage in range(dst_stage - 1, -1, -1):
            candidates = by_stage.get(cand_stage)
            if not candidates:
                continue
            linked = [src_rec for src_rec in candidates if _is_causally_linked(src_rec, dst_rec)]
            if linked:
                relation = _STAGE_RELATION[cand_stage]
                for src_rec in linked:
                    edges.append(
                        EvidenceEdge(
                            from_id=str(src_rec.id),
                            to_id=str(dst_rec.id),
                            relation=relation,
                        )
                    )
                break

    return EvidenceGraph(
        dispute_case_id=case.id,
        tenant_id=case.tenant_id,
        correlation_id=case.correlation_id,
        nodes=nodes,
        edges=edges,
    )
