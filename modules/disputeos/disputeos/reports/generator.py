"""Deterministic grounded dispute report generator."""

from __future__ import annotations

from uuid import UUID

from contracts.enums import DisputeRecommendation
from contracts.models import (
    DisputeAnalysis,
    DisputeCase,
    DisputeEvidenceCitation,
    EvidenceRecord,
)
from pydantic import BaseModel
from security.tenant import assert_same_tenant

SYNTHETIC_BANNER = "[SYNTHETIC DEMO CASE — NOT FOR PAYPAL SUBMISSION]"


class DisputeReport(BaseModel):
    """Structured and markdown-formatted dispute report requiring human review."""

    case_id: UUID
    tenant_id: UUID
    is_synthetic: bool
    synthetic_banner: str | None
    recommendation: DisputeRecommendation
    grounded_summary: str
    citations: list[DisputeEvidenceCitation]
    contradictions: list[str]
    missing_evidence: list[str]
    rejected_claims: list[str]
    draft_response_text: str
    requires_human_approval: bool
    human_approved_for_submission: bool
    markdown_report: str


def _render_markdown_report(
    *,
    case: DisputeCase,
    analysis: DisputeAnalysis,
    evidence: list[EvidenceRecord],
    synthetic_banner: str | None,
) -> str:
    lines: list[str] = []
    if synthetic_banner:
        lines.append(f"> **{synthetic_banner}**")
        lines.append("")

    lines.extend([
        f"# DisputeOS Case Report: `{case.id}`",
        "",
        "## Case Overview",
        f"- **Case ID:** `{case.id}`",
        f"- **Tenant ID:** `{case.tenant_id}`",
        f"- **Source Type:** `{case.source_type.value}`",
        f"- **Synthetic Case:** `{case.is_synthetic}`",
        f"- **Status:** `{case.status.value}`",
        f"- **Reason:** {case.reason}",
        f"- **Amount:** {case.amount_minor} {case.currency}",
        f"- **Recommendation:** `{analysis.recommendation.value}` (confidence: {analysis.confidence_score:.2f})",
        f"- **Human Approval Required:** `{True}`",
        f"- **Human Approved For Submission:** `{case.human_approved_for_submission}`",
        "",
        "## Agentic Dispute Assessment",
        f"- **Agent Authorized:** `{analysis.agent_authorized}`",
        f"- **Agent Followed Policy:** `{analysis.agent_followed_policy}`",
        f"- **Merchant Fulfilled Order:** `{analysis.merchant_fulfilled_order}`",
        "",
        "## Grounded Summary",
        analysis.grounded_summary,
        "",
        "## Verified Citations",
    ])

    if analysis.citations:
        for citation in analysis.citations:
            lines.append(
                f"- **[evidence_id=`{citation.evidence_id}` | verified={citation.verified}]** "
                f"{citation.claim} — Excerpt: `{citation.verbatim_excerpt}`"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Contradictions Detected"])
    if analysis.contradictions:
        for item in analysis.contradictions:
            lines.append(f"- {item}")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Missing Evidence"])
    if analysis.missing_evidence:
        for item in analysis.missing_evidence:
            lines.append(f"- {item}")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Rejected / Unsupported Claims"])
    if analysis.rejected_claims:
        for item in analysis.rejected_claims:
            lines.append(f"- {item}")
    else:
        lines.append("- None")

    lines.extend(["", "## Evidence Inventory"])
    if evidence:
        for rec in evidence:
            lines.append(
                f"- `evidence_id={rec.id}` | `{rec.source_type.value}` | "
                f"{rec.title} | synthetic={rec.is_synthetic}"
            )
    else:
        lines.append("- No evidence records attached")

    lines.extend([
        "",
        "## Draft Response Text (Pending Human Approval)",
        "```text",
        analysis.draft_response_text,
        "```",
    ])

    return "\n".join(lines)


def generate_case_report(
    case: DisputeCase,
    analysis: DisputeAnalysis,
    evidence: list[EvidenceRecord],
) -> DisputeReport:
    """Generate a deterministic, tenant-isolated DisputeReport without external AI credentials."""
    assert_same_tenant(case.tenant_id, analysis.tenant_id, resource=f"dispute_analysis:{analysis.id}")
    for rec in evidence:
        assert_same_tenant(case.tenant_id, rec.tenant_id, resource=f"evidence:{rec.id}")

    synthetic_banner = SYNTHETIC_BANNER if case.is_synthetic else None
    markdown_report = _render_markdown_report(
        case=case,
        analysis=analysis,
        evidence=evidence,
        synthetic_banner=synthetic_banner,
    )

    return DisputeReport(
        case_id=case.id,
        tenant_id=case.tenant_id,
        is_synthetic=case.is_synthetic,
        synthetic_banner=synthetic_banner,
        recommendation=analysis.recommendation,
        grounded_summary=analysis.grounded_summary,
        citations=list(analysis.citations),
        contradictions=list(analysis.contradictions),
        missing_evidence=list(analysis.missing_evidence),
        rejected_claims=list(analysis.rejected_claims),
        draft_response_text=analysis.draft_response_text,
        requires_human_approval=True,
        human_approved_for_submission=case.human_approved_for_submission,
        markdown_report=markdown_report,
    )
