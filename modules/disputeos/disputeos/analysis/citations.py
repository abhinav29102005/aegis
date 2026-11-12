"""Strict semantic evidence citation and summary grounding validation for DisputeOS."""

from __future__ import annotations

import re
from uuid import UUID

from contracts.hashing import canonical_json
from contracts.models import DisputeCase, DisputeEvidenceCitation, EvidenceRecord
from pydantic import BaseModel

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "was", "were", "are",
    "has", "have", "had", "not", "but", "into", "onto", "upon", "about", "after",
    "before", "during", "while", "where", "when", "which", "who", "whom", "their",
    "there", "these", "those", "such", "than", "then", "also", "only", "been",
    "being", "will", "would", "could", "should", "may", "might", "must", "shall",
    "shows", "show", "shown", "confirms", "confirm", "confirmed", "indicates",
    "indicate", "indicated", "states", "state", "stated", "verified", "verify",
    "based", "according", "prior", "required", "require", "requires",
})

# Generic 1-word tokens, currency codes, and schema keys that must never ground arbitrary claims alone.
_GENERIC_SINGLE_TOKENS = frozenset({
    "usd", "eur", "gbp", "cad", "aud", "jpy", "chf", "inr",
    "status", "currency", "amount", "title", "content", "type", "name", "value",
    "data", "code", "result", "outcome", "decision", "true", "false", "null",
    "none", "id", "date", "time", "text", "note", "info", "item", "user",
    "order", "case", "claim", "record", "source", "ref", "hash", "yes", "no",
    "summary", "evidence", "human", "review", "approval", "external", "submission",
    "agent", "policy", "merchant", "buyer", "recommendation", "dispute",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NUMBER_RE = re.compile(r"\b\d{2,}\b")
_EVIDENCE_ID_TAG_RE = re.compile(r"\[evidence_id=[^\]]+\]", re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_BOILERPLATE_SENTENCES = frozenset({
    "human review and approval are required prior to any external submission",
    "human review required",
    "pending mandatory human approval",
})


def _extract_tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _meaningful_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in _extract_tokens(text)
        if len(tok) >= 3 and tok not in _STOPWORDS and tok not in _GENERIC_SINGLE_TOKENS
    }


def _tokens_match(a: str, b_set: set[str]) -> bool:
    if a in b_set:
        return True
    if len(a) >= 5:
        prefix = a[:5]
        return any(b.startswith(prefix) or a.startswith(b[:5]) for b in b_set if len(b) >= 5)
    return False


class CandidateClaim(BaseModel):
    """Unverified claim proposed by deterministic rules or an optional LLM reviewer."""

    claim: str
    evidence_id: UUID | None = None
    verbatim_excerpt: str = ""


class CitationValidator:
    """Validates that factual claims and LLM summaries are semantically grounded in tenant-owned evidence."""

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

            content_json = canonical_json(record.content)
            searchable = f"{record.title} {content_json}"
            if excerpt.lower() not in searchable.lower():
                rejected_claims.append(
                    f"Rejected claim '{preview}': verbatim_excerpt not found in evidence_id {candidate.evidence_id}."
                )
                continue

            # Reject generic 1-word / low-information substrings (e.g. "USD", "status")
            excerpt_tokens = _extract_tokens(excerpt)
            if len(excerpt) < 4 or not excerpt_tokens:
                rejected_claims.append(
                    f"Rejected claim '{preview}': verbatim_excerpt '{excerpt}' is too short or generic."
                )
                continue

            if len(excerpt_tokens) == 1:
                single = excerpt_tokens[0]
                if single in _GENERIC_SINGLE_TOKENS:
                    rejected_claims.append(
                        f"Rejected claim '{preview}': generic 1-word verbatim_excerpt '{excerpt}' cannot ground a claim."
                    )
                    continue
                # Reject if the 1-word excerpt only appears as a JSON object key name
                non_key_json = re.sub(r'"[^"]+"\s*:', " ", content_json.lower())
                if single not in _extract_tokens(f"{record.title} {non_key_json}"):
                    rejected_claims.append(
                        f"Rejected claim '{preview}': verbatim_excerpt '{excerpt}' matches only a JSON field key."
                    )
                    continue
                claim_tokens_all = set(_extract_tokens(claim_text))
                if not _tokens_match(single, claim_tokens_all):
                    rejected_claims.append(
                        f"Rejected claim '{preview}': claim is semantically ungrounded in 1-word excerpt '{excerpt}'."
                    )
                    continue

            excerpt_meaningful = _meaningful_tokens(excerpt)
            if not excerpt_meaningful:
                rejected_claims.append(
                    f"Rejected claim '{preview}': verbatim_excerpt contains only generic tokens."
                )
                continue

            claim_without_id_tag = _EVIDENCE_ID_TAG_RE.sub("", claim_text)
            claim_meaningful = _meaningful_tokens(claim_without_id_tag)
            title_meaningful = _meaningful_tokens(record.title)
            grounding_tokens = excerpt_meaningful | title_meaningful

            if claim_meaningful and not any(_tokens_match(tok, grounding_tokens) for tok in claim_meaningful):
                rejected_claims.append(
                    f"Rejected claim '{preview}': claim is semantically ungrounded in cited evidence_id {candidate.evidence_id}."
                )
                continue

            # Reject claims introducing multi-digit numbers absent from the cited evidence record
            claim_no_uuids = _UUID_RE.sub("", claim_without_id_tag)
            searchable_lower = searchable.lower()
            ungrounded_nums = [
                num for num in _NUMBER_RE.findall(claim_no_uuids) if num not in searchable_lower
            ]
            if ungrounded_nums:
                rejected_claims.append(
                    f"Rejected claim '{preview}': introduces ungrounded numeric values ({', '.join(ungrounded_nums)})."
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

    def validate_summary(
        self,
        summary: str,
        citations: list[DisputeEvidenceCitation],
        *,
        case: DisputeCase | None = None,
        recommendation_value: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Verify every substantive sentence in an LLM summary is grounded in cited excerpts and case facts."""
        cleaned = summary.replace("[SYNTHETIC DEMO CASE — NOT FOR PAYPAL SUBMISSION]", "").strip()
        if not cleaned:
            return False, ["Summary is empty."]
        if not citations:
            return False, ["No verified citations available to ground summary."]

        corpus_parts: list[str] = []
        for citation in citations:
            corpus_parts.append(citation.verbatim_excerpt)
            corpus_parts.append(citation.claim)
        if case is not None:
            corpus_parts.extend(
                [
                    str(case.id),
                    case.reason,
                    str(case.amount_minor),
                    case.currency,
                ]
            )
        if recommendation_value:
            corpus_parts.append(recommendation_value)

        cited_corpus = " ".join(corpus_parts)
        cited_corpus_lower = cited_corpus.lower()
        cited_meaningful = _meaningful_tokens(cited_corpus)

        raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
        sentences = [s.strip() for s in raw_sentences if s.strip()]
        if not sentences:
            return False, ["Summary contains no sentences."]

        ungrounded_reasons: list[str] = []
        substantive_count = 0

        for sentence in sentences:
            normalized_sentence = re.sub(r"[.!?\s]+$", "", sentence.lower()).strip()
            if normalized_sentence in _BOILERPLATE_SENTENCES:
                continue

            # Reject multi-digit numbers not present in cited excerpts or case facts
            sentence_no_uuids = _UUID_RE.sub("", sentence)
            for num in _NUMBER_RE.findall(sentence_no_uuids):
                if num not in cited_corpus_lower:
                    ungrounded_reasons.append(
                        f"Summary sentence introduces ungrounded number '{num}': {sentence[:100]}"
                    )

            sent_meaningful = _meaningful_tokens(sentence_no_uuids)
            if not sent_meaningful:
                continue
            substantive_count += 1

            matched = sum(1 for tok in sent_meaningful if _tokens_match(tok, cited_meaningful))
            ratio = matched / len(sent_meaningful)
            if matched == 0 or ratio < 0.30:
                ungrounded_reasons.append(
                    f"Summary sentence is ungrounded in cited evidence excerpts ({matched}/{len(sent_meaningful)} tokens): {sentence[:100]}"
                )

        if substantive_count == 0:
            return False, ["Summary contains no substantive grounded claims."]

        return (len(ungrounded_reasons) == 0), ungrounded_reasons
