"""Feature-flagged PayPal Sandbox Disputes adapter with strict human-approval gating."""

from __future__ import annotations

from typing import Any

import httpx
from contracts import (
    DisputeCase,
    DisputeSourceType,
    EvidenceRecord,
    EvidenceSourceType,
    compute_payload_hash,
)
from paypal import (
    PayPalAPIError,
    PayPalDisputesDisabledError,
    PayPalSandboxClient,
    PayPalTimeoutError,
)
from security import NexusSettings, get_settings


def _normalize_paypal_response(raw_response: Any, *, operation: str) -> dict[str, Any]:
    if hasattr(raw_response, "status_code"):
        code = int(raw_response.status_code)
        if code < 200 or code >= 300:
            raise PayPalAPIError(
                f"PayPal {operation} failed ({code})",
                status_code=code,
            )
        if hasattr(raw_response, "json"):
            try:
                parsed = raw_response.json()
                return parsed if isinstance(parsed, dict) else {"raw": parsed}
            except ValueError:
                return {"status_code": code}
        return {"status_code": code}

    if isinstance(raw_response, dict):
        maybe_code = raw_response.get("status_code")
        if isinstance(maybe_code, int) and maybe_code >= 400:
            raise PayPalAPIError(
                f"PayPal {operation} failed ({maybe_code})",
                status_code=maybe_code,
            )
        return raw_response

    return {"result": raw_response}


class PayPalDisputeAdapter:
    """Adapter around PayPal Sandbox Disputes API v1.

    Never auto-submits dispute responses, never issues unapproved refunds, and
    strictly rejects synthetic cases or unapproved response payloads.
    """

    def __init__(
        self,
        settings: NexusSettings | None = None,
        paypal_client: PayPalSandboxClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._paypal_client = paypal_client

    def is_enabled(self) -> bool:
        """Return True only when Disputes API flag is enabled and PayPal mode is sandbox."""
        return bool(
            self.settings.paypal_disputes_api_enabled
            and self.settings.paypal_mode.lower() == "sandbox"
        )

    def _get_client(self) -> PayPalSandboxClient:
        if self._paypal_client is None:
            self._paypal_client = PayPalSandboxClient(self.settings)
        return self._paypal_client

    def _validate_preconditions(self, case: DisputeCase) -> str:
        if case.is_synthetic or case.source_type == DisputeSourceType.SYNTHETIC_DEMO:
            raise ValueError("Synthetic dispute cases cannot be submitted to PayPal")

        if not case.human_approved_for_submission or not case.approved_by:
            raise PermissionError("Human approval required before external submission")

        if not self.is_enabled():
            raise PayPalDisputesDisabledError(
                "PayPal Disputes API is disabled; set PAYPAL_DISPUTES_API_ENABLED=true in sandbox mode."
            )

        dispute_id = (case.paypal_dispute_id or "").strip()
        if not dispute_id:
            raise ValueError(
                f"Dispute case {case.id} requires paypal_dispute_id before external PayPal submission"
            )
        return dispute_id

    async def list_sandbox_disputes(self) -> dict[str, Any]:
        """List PayPal Sandbox disputes if feature-flagged on; fail closed otherwise."""
        if not self.is_enabled():
            raise PayPalDisputesDisabledError(
                "PayPal Disputes API is disabled; set PAYPAL_DISPUTES_API_ENABLED=true in sandbox mode."
            )
        return await self._get_client().list_disputes()

    async def submit_dispute_response(
        self,
        *,
        case: DisputeCase,
        draft_response_text: str,
        evidence_records: list[EvidenceRecord] | None = None,
        files: list[tuple[str, bytes, str]] | None = None,
        evidence_type: str = "PROOF_OF_FULFILLMENT",
    ) -> dict[str, Any]:
        """Submit a human-approved dispute response to PayPal Disputes v1 provide-evidence API."""
        if case.is_synthetic or case.source_type == DisputeSourceType.SYNTHETIC_DEMO:
            raise ValueError("Synthetic dispute cases cannot be submitted to PayPal")

        expected_hash = compute_payload_hash({
            "case_id": str(case.id),
            "draft_response_text": draft_response_text,
        })
        if (
            not case.human_approved_for_submission
            or not case.approved_by
            or case.response_payload_hash != expected_hash
        ):
            raise PermissionError("Human approval required before external submission")

        if not self.is_enabled():
            raise PayPalDisputesDisabledError(
                "PayPal Disputes API is disabled; set PAYPAL_DISPUTES_API_ENABLED=true in sandbox mode."
            )

        dispute_id = (case.paypal_dispute_id or "").strip()
        if not dispute_id:
            raise ValueError(
                f"Dispute case {case.id} requires paypal_dispute_id before external PayPal submission"
            )

        tracking_info: list[dict[str, str]] = []
        for rec in evidence_records or []:
            if rec.source_type == EvidenceSourceType.CARRIER_TRACKING:
                carrier = rec.content.get("carrier")
                tracking_number = rec.content.get("tracking_number")
                if carrier and tracking_number:
                    tracking_info.append({
                        "carrier_name": str(carrier),
                        "tracking_number": str(tracking_number),
                    })

        evidence_entry: dict[str, Any] = {
            "evidence_type": evidence_type,
            "notes": draft_response_text[:2000],
        }
        if tracking_info:
            evidence_entry["evidence_info"] = {"tracking_info": tracking_info}
        evidence_payload: dict[str, Any] = {"evidences": [evidence_entry]}

        client = self._get_client()
        provide_fn = getattr(client, "provide_evidence", None)
        if provide_fn is None:
            raise PayPalAPIError(
                "PayPal client does not implement provide_evidence",
                status_code=501,
            )

        try:
            raw_response = await provide_fn(dispute_id, evidence_payload, files=files)
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(
                f"PayPal provide_evidence timed out for dispute {dispute_id}"
            ) from exc

        response_data = _normalize_paypal_response(raw_response, operation="provide_evidence")

        return {
            "status": "SUBMITTED_TO_PAYPAL",
            "submitted": True,
            "auto_submitted": False,
            "refund_issued": False,
            "case_id": str(case.id),
            "paypal_dispute_id": dispute_id,
            "approved_by": case.approved_by,
            "response_payload_hash": expected_hash,
            "draft_response_text": draft_response_text,
            "mode": self.settings.paypal_mode,
            "paypal_response": response_data,
        }

    async def accept_dispute_claim(
        self,
        *,
        case: DisputeCase,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Accept a PayPal dispute claim (and issue refund) only after explicit human approval."""
        dispute_id = self._validate_preconditions(case)
        client = self._get_client()
        accept_fn = getattr(client, "accept_claim", None)
        if accept_fn is None:
            raise PayPalAPIError(
                "PayPal client does not implement accept_claim",
                status_code=501,
            )

        try:
            raw_response = await accept_fn(dispute_id, note=note)
        except httpx.TimeoutException as exc:
            raise PayPalTimeoutError(
                f"PayPal accept_claim timed out for dispute {dispute_id}"
            ) from exc

        response_data = _normalize_paypal_response(raw_response, operation="accept_claim")
        return {
            "status": "CLAIM_ACCEPTED",
            "submitted": True,
            "auto_submitted": False,
            "refund_issued": True,
            "case_id": str(case.id),
            "paypal_dispute_id": dispute_id,
            "approved_by": case.approved_by,
            "mode": self.settings.paypal_mode,
            "paypal_response": response_data,
        }
