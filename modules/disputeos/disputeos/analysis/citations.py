"""Strict evidence citation validation for DisputeOS claims."""

from __future__ import annotations

from uuid import UUID

from contracts.hashing import canonical_json
from contracts.models import DisputeEvidenceCitation, EvidenceRecord
from pydantic import BaseModel


class CandidateClaim(BaseModel):
    """Unverified claim proposed by deterministic rules or an optional LLM reviewer."""

    claim: str
    evidence_id: UUID | None = None
    verbatim_excerpt: str = ""


class CitationValidator:
    """Validates that every factual claim cites a tenant-owned evidence record and verbatim excerpt."""

    def validate_claims(
        self,
        claims: list[CandidateClaim],
        evidence: list[EvidenceRecord],
        tenant_id: UUID,
    ) -> tuple[list[DisputeEvidenceCitation], list[str]]:
        """Validate candidate claims against available evidence for a single tenant.

        Returns a tuple of (verified_citations, rejected_claim_reasons).
        """
        evidence_by_id: dict[UUID, EvidenceRecord] = {rec.id: rec for rec in evidence}
        verified_citations: list[DisputeEvidenceCitation] = []
        rejected_claims: list[str] = []

        for candidate in claims:
            claim_text = candidate.claim.strip()
            preview = (claim_text[:80] + "...") if len(claim_text) > 80 else (claim_text or "<empty claim>")

            if not claim_text:
                rejected_claims.append(f"Rejected claim '{preview}': claim text is empty.")
                continue

            if candidate.evidence_id is None:
                rejected_claims.append(f"Rejected claim '{preview}': missing evidence_id.")
                continue

            record = evidence_by_id.get(candidate.evidence_id)
            if record is None:
                rejected_claims.append(
                    f"Rejected claim '{preview}': evidence_id {candidate.evidence_id} not found in evidence."
                )
                continue

            if record.tenant_id != tenant_id:
                rejected_claims.append(
                    f"Rejected claim '{preview}': evidence_id {candidate.evidence_id} "
                    f"belongs to another tenant ({record.tenant_id})."
                )
                continue

            excerpt = candidate.verbatim_excerpt.strip()
            if not excerpt:
                rejected_claims.append(
                    f"Rejected claim '{preview}': empty verbatim_excerpt for evidence_id {candidate.evidence_id}."
                )
                continue

            searchable = f"{record.title} {canonical_json(record.content)}"
            if excerpt.lower() not in searchable.lower():
                rejected_claims.append(
                    f"Rejected claim '{preview}': verbatim_excerpt not found in evidence_id {candidate.evidence_id}."
                )
                continue

            verified_citations.append(
                DisputeEvidenceCitation(
                    claim=claim_text[:500],
                    evidence_id=record.id,
                    verbatim_excerpt=excerpt[:500],
                    verified=True,
                )
            )

        return verified_citations, rejected_claims
