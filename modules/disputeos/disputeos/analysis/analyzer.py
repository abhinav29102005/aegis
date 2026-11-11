"""Deterministic dispute analyzer with optional fail-closed LLM reviewer grounding."""

from __future__ import annotations

import re
from typing import Protocol

from contracts.enums import DisputeRecommendation, EvidenceSourceType
from contracts.hashing import canonical_json
from contracts.models import (
    DisputeAnalysis,
    DisputeCase,
    DisputeEvidenceCitation,
    EvidenceRecord,
)
from security.tenant import assert_same_tenant

from disputeos.analysis.citations import CandidateClaim, CitationValidator
from disputeos.evidence.detector import detect_contradictions, detect_missing_evidence

SYNTHETIC_BANNER = "[SYNTHETIC DEMO CASE — NOT FOR PAYPAL SUBMISSION]"

_NON_DELIVERY_MARKERS = (
    "non-delivery",
    "non delivery",
    "not delivered",
    "not_delivered",
    "undelivered",
    "never delivered",
    "failed delivery",
    "not received",
    "dispatch was delayed",
)


class LLMReviewerProtocol(Protocol):
    """Protocol for optional LLM-assisted dispute review."""

    def review(
        self,
        *,
        case: DisputeCase,
        evidence: list[EvidenceRecord],
        missing: list[str],
        contradictions: list[str],
    ) -> tuple[str, list[CandidateClaim]]: ...


def _record_text(record: EvidenceRecord) -> str:
    return f"{record.title} {canonical_json(record.content)}"


def _is_denied_or_revoked(record: EvidenceRecord) -> bool:
    content = record.content
    for key in ("outcome", "decision", "status"):
        val = str(content.get(key, "")).upper()
        if val in {"DENY", "DENIED", "REJECTED", "REVOKED", "EXPIRED"}:
            return True

    if content.get("revoked") is True or content.get("denied") is True:
        return True
    if (
        content.get("authorized") is False
        or content.get("approved") is False
        or content.get("allowed") is False
    ):
        return True

    reason_codes = content.get("reason_codes")
    if isinstance(reason_codes, list):
        for code in reason_codes:
            if str(code).upper().startswith("DENIED_"):
                return True

    return False


def _evaluate_agent_authorized(evidence: list[EvidenceRecord]) -> bool:
    auth_types = {
        EvidenceSourceType.POLICY_DECISION,
        EvidenceSourceType.HUMAN_APPROVAL,
        EvidenceSourceType.PROPOSAL,
    }
    relevant = [rec for rec in evidence if rec.source_type in auth_types]
    if not relevant:
        return False
    return not any(_is_denied_or_revoked(rec) for rec in relevant)


def _evaluate_agent_followed_policy(evidence: list[EvidenceRecord]) -> bool:
    policy_records = [
        rec for rec in evidence if rec.source_type == EvidenceSourceType.POLICY_DECISION
    ]
    if not policy_records:
        return False
    if any(_is_denied_or_revoked(rec) for rec in policy_records):
        return False

    for rec in policy_records:
        content = rec.content
        for key in ("outcome", "decision", "status", "result"):
            if str(content.get(key, "")).upper() == "ALLOW":
                return True
        if content.get("allowed") is True:
            return True
        if re.search(r"\bALLOW\b", _record_text(rec), re.IGNORECASE):
            return True
    return False


def _contradictions_show_non_delivery(contradictions: list[str]) -> bool:
    for entry in contradictions:
        lower = entry.lower()
        if any(marker in lower for marker in _NON_DELIVERY_MARKERS):
            return True
    return False


def _record_confirms_delivery(record: EvidenceRecord) -> bool:
    text = _record_text(record)
    if re.search(
        r"\b(UNDELIVERED|NOT[ _]DELIVERED|NON[- ]DELIVERY|FAILED[ _]DELIVERY)\b",
        text,
        re.IGNORECASE,
    ):
        return False

    if record.content.get("delivered") is True:
        return True

    status = str(
        record.content.get("status", record.content.get("delivery_status", ""))
    ).upper()
    if status in {"DELIVERED", "CONFIRMED", "COMPLETED"}:
        return True

    return bool(re.search(r"\bDELIVERED\b", text, re.IGNORECASE))


def _evaluate_merchant_fulfilled_order(
    evidence: list[EvidenceRecord],
    contradictions: list[str],
) -> bool | None:
    if _contradictions_show_non_delivery(contradictions):
        return False
    if contradictions:
        return None

    tracking_confirmed = any(
        _record_confirms_delivery(rec)
        for rec in evidence
        if rec.source_type == EvidenceSourceType.CARRIER_TRACKING
    )
    receipt_confirmed = any(
        _record_confirms_delivery(rec)
        for rec in evidence
        if rec.source_type == EvidenceSourceType.DELIVERY_RECEIPT
    )
    if tracking_confirmed and receipt_confirmed:
        return True
    return None


def _choose_recommendation(
    *,
    agent_authorized: bool,
    agent_followed_policy: bool,
    merchant_fulfilled_order: bool | None,
    missing: list[str],
    contradictions: list[str],
) -> DisputeRecommendation:
    if _contradictions_show_non_delivery(contradictions):
        return DisputeRecommendation.ACCEPT_AND_REFUND
    if missing:
        return DisputeRecommendation.NEED_MORE_EVIDENCE
    if agent_authorized and agent_followed_policy and merchant_fulfilled_order is True:
        return DisputeRecommendation.CHALLENGE_WITH_EVIDENCE
    return DisputeRecommendation.OFFER_PARTIAL_OR_RETURN


def _compute_confidence(
    *,
    recommendation: DisputeRecommendation,
    missing: list[str],
    contradictions: list[str],
) -> float:
    if recommendation == DisputeRecommendation.ACCEPT_AND_REFUND:
        score = 0.90 - (0.05 * len(missing))
    elif recommendation == DisputeRecommendation.CHALLENGE_WITH_EVIDENCE:
        score = 0.92
    elif recommendation == DisputeRecommendation.NEED_MORE_EVIDENCE:
        score = 0.65 - (0.10 * len(missing))
    else:
        score = 0.60 - (0.05 * len(contradictions))
    return round(max(0.10, min(0.95, score)), 2)


def _build_deterministic_claims(evidence: list[EvidenceRecord]) -> list[CandidateClaim]:
    claims: list[CandidateClaim] = []
    for rec in evidence:
        content_json = canonical_json(rec.content)
        excerpt = content_json[:450] if len(content_json) > 2 else rec.title[:450]
        claim_text = f"{rec.source_type.value}: {rec.title} [evidence_id={rec.id}]"
        claims.append(
            CandidateClaim(
                claim=claim_text[:500],
                evidence_id=rec.id,
                verbatim_excerpt=excerpt,
            )
        )
    return claims


def _build_deterministic_summary(
    *,
    case: DisputeCase,
    recommendation: DisputeRecommendation,
    agent_authorized: bool,
    agent_followed_policy: bool,
    merchant_fulfilled_order: bool | None,
    citations: list[DisputeEvidenceCitation],
    missing: list[str],
    contradictions: list[str],
) -> str:
    parts: list[str] = []
    if case.is_synthetic:
        parts.append(SYNTHETIC_BANNER)

    fulfilled_label = (
        "Yes"
        if merchant_fulfilled_order is True
        else ("No" if merchant_fulfilled_order is False else "Unverified")
    )
    parts.append(
        f"Case {case.id} ({case.reason}, {case.amount_minor} {case.currency}): "
        f"Recommendation={recommendation.value}. "
        f"Agent authorized={'Yes' if agent_authorized else 'No'}; "
        f"Policy followed={'Yes' if agent_followed_policy else 'No'}; "
        f"Merchant fulfilled order={fulfilled_label}."
    )

    if citations:
        cited = "; ".join(f"{c.claim}" for c in citations)
        parts.append(f"Grounded evidence: {cited}.")
    else:
        parts.append("No verified evidence records were available to support factual claims.")

    if contradictions:
        parts.append(f"Contradictions detected: {'; '.join(contradictions)}.")
    if missing:
        parts.append(f"Missing evidence: {'; '.join(missing)}.")

    parts.append("Human review and approval are required prior to any external submission.")
    return " ".join(parts)[:4000]


def _build_draft_response(
    *,
    case: DisputeCase,
    recommendation: DisputeRecommendation,
    citations: list[DisputeEvidenceCitation],
    missing: list[str],
    contradictions: list[str],
) -> str:
    lines: list[str] = []
    if case.is_synthetic:
        lines.append(SYNTHETIC_BANNER)

    lines.append(
        f"Dispute Response Draft for Case {case.id} "
        f"(Reason: {case.reason}, Amount: {case.amount_minor} {case.currency}):"
    )

    if recommendation == DisputeRecommendation.ACCEPT_AND_REFUND:
        lines.append(
            "Recommended Action: Accept dispute and process refund due to confirmed non-delivery contradiction."
        )
    elif recommendation == DisputeRecommendation.CHALLENGE_WITH_EVIDENCE:
        lines.append(
            "Recommended Action: Challenge dispute using verified authorization, policy compliance, and delivery evidence."
        )
    elif recommendation == DisputeRecommendation.NEED_MORE_EVIDENCE:
        lines.append(
            "Recommended Action: Hold external submission and collect missing evidence before responding."
        )
    else:
        lines.append(
            "Recommended Action: Offer partial refund or return resolution based on incomplete verification."
        )

    if citations:
        lines.append("Referenced Evidence:")
        for citation in citations:
            lines.append(f"- [evidence_id={citation.evidence_id}] {citation.claim}")

    if contradictions:
        lines.append(f"Contradictions Surfaced: {'; '.join(contradictions)}")
    if missing:
        lines.append(f"Missing Evidence Items: {'; '.join(missing)}")

    lines.append("Status: Pending mandatory human approval before any external PayPal submission.")
    return "\n".join(lines)[:4000]


class DisputeAnalyzer:
    """Deterministic dispute intelligence analyzer with optional grounded LLM review."""

    def __init__(self, llm_reviewer: LLMReviewerProtocol | None = None) -> None:
        self.llm_reviewer = llm_reviewer
        self.citation_validator = CitationValidator()

    def analyze(
        self,
        *,
        case: DisputeCase,
        evidence: list[EvidenceRecord],
    ) -> DisputeAnalysis:
        """Analyze a dispute case and its evidence, producing a grounded DisputeAnalysis."""
        assert_same_tenant(case.tenant_id, case.tenant_id, resource=f"dispute_case:{case.id}")
        for rec in evidence:
            assert_same_tenant(case.tenant_id, rec.tenant_id, resource=f"evidence:{rec.id}")

        missing = detect_missing_evidence(case, evidence)
        contradictions = detect_contradictions(case, evidence)

        agent_authorized = _evaluate_agent_authorized(evidence)
        agent_followed_policy = _evaluate_agent_followed_policy(evidence)
        merchant_fulfilled_order = _evaluate_merchant_fulfilled_order(evidence, contradictions)

        recommendation = _choose_recommendation(
            agent_authorized=agent_authorized,
            agent_followed_policy=agent_followed_policy,
            merchant_fulfilled_order=merchant_fulfilled_order,
            missing=missing,
            contradictions=contradictions,
        )
        confidence_score = _compute_confidence(
            recommendation=recommendation,
            missing=missing,
            contradictions=contradictions,
        )

        det_claims = _build_deterministic_claims(evidence)
        det_citations, det_rejected = self.citation_validator.validate_claims(
            det_claims,
            evidence,
            case.tenant_id,
        )
        det_summary = _build_deterministic_summary(
            case=case,
            recommendation=recommendation,
            agent_authorized=agent_authorized,
            agent_followed_policy=agent_followed_policy,
            merchant_fulfilled_order=merchant_fulfilled_order,
            citations=det_citations,
            missing=missing,
            contradictions=contradictions,
        )

        citations = det_citations
        rejected_claims = list(det_rejected)
        grounded_summary = det_summary
        generated_with_llm = False

        if self.llm_reviewer is not None:
            try:
                llm_summary, llm_claims = self.llm_reviewer.review(
                    case=case,
                    evidence=evidence,
                    missing=missing,
                    contradictions=contradictions,
                )
                llm_citations, llm_rejected = self.citation_validator.validate_claims(
                    llm_claims,
                    evidence,
                    case.tenant_id,
                )
                if llm_citations and llm_summary.strip():
                    citations = llm_citations
                    rejected_claims = llm_rejected
                    summary_text = llm_summary.strip()
                    if case.is_synthetic and SYNTHETIC_BANNER not in summary_text:
                        summary_text = f"{SYNTHETIC_BANNER} {summary_text}"
                    grounded_summary = summary_text[:4000]
                    generated_with_llm = True
                else:
                    rejected_claims.extend(llm_rejected)
            except Exception:  # noqa: BLE001
                # Fail closed to deterministic summary without corrupting case state.
                citations = det_citations
                rejected_claims = list(det_rejected)
                grounded_summary = det_summary
                generated_with_llm = False

        draft_response_text = _build_draft_response(
            case=case,
            recommendation=recommendation,
            citations=citations,
            missing=missing,
            contradictions=contradictions,
        )

        return DisputeAnalysis(
            tenant_id=case.tenant_id,
            correlation_id=case.correlation_id,
            dispute_case_id=case.id,
            is_synthetic=case.is_synthetic,
            recommendation=recommendation,
            confidence_score=confidence_score,
            agent_authorized=agent_authorized,
            agent_followed_policy=agent_followed_policy,
            merchant_fulfilled_order=merchant_fulfilled_order,
            contradictions=list(contradictions),
            missing_evidence=list(missing),
            citations=citations,
            rejected_claims=rejected_claims,
            grounded_summary=grounded_summary,
            draft_response_text=draft_response_text,
            requires_human_approval=True,
            generated_with_llm=generated_with_llm,
        )
