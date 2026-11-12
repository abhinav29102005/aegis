"""Feature-flagged PayPal Sandbox Disputes adapter with strict human-approval gating."""

from __future__ import annotations

from typing import Any

from contracts import DisputeCase, DisputeSourceType, compute_payload_hash
from paypal import PayPalDisputesDisabledError, PayPalSandboxClient
from security import NexusSettings, get_settings


class PayPalDisputeAdapter:
    """Adapter around PayPal Sandbox Disputes API v1.

    Never auto-submits dispute responses, never issues refunds, and strictly rejects
    synthetic cases or unapproved response payloads.
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
        execute_external: bool = False,
        evidence_type: str = "PROOF_OF_DELIVERY",
    ) -> dict[str, Any]:
        """Prepare or submit a human-approved dispute response payload without auto-submitting or refunding."""
        if case.is_synthetic or case.source_type == DisputeSourceType.SYNTHETIC_DEMO:
            raise ValueError("Synthetic dispute cases cannot be submitted to PayPal")

        expected_hash = compute_payload_hash({
            "case_id": str(case.id),
            "draft_response_text": draft_response_text,
        })
        if (
            not case.human_approved_for_submission
            or case.response_payload_hash != expected_hash
        ):
            raise PermissionError("Human approval required before external submission")

        if not self.is_enabled():
            raise PayPalDisputesDisabledError(
                "PayPal Disputes API is disabled; set PAYPAL_DISPUTES_API_ENABLED=true in sandbox mode."
            )

        external_resp = None
        submitted = False
        if execute_external:
            if not case.paypal_dispute_id:
                raise ValueError("paypal_dispute_id is required for external PayPal submission")
            client = self._get_client()
            external_resp = await client.provide_evidence(
                dispute_id=case.paypal_dispute_id,
                evidence_type=evidence_type,
                notes=draft_response_text,
            )
            submitted = True

        return {
            "status": "SUBMITTED" if submitted else "APPROVED_PAYLOAD_READY",
            "submitted": submitted,
            "auto_submitted": False,
            "refund_issued": False,
            "case_id": str(case.id),
            "paypal_dispute_id": case.paypal_dispute_id,
            "approved_by": case.approved_by,
            "response_payload_hash": expected_hash,
            "draft_response_text": draft_response_text,
            "mode": self.settings.paypal_mode,
            "external_response": external_resp,
        }

    async def accept_dispute_claim(
        self,
        *,
        case: DisputeCase,
        note: str = "",
    ) -> dict[str, Any]:
        """Accept a dispute claim via PayPal API when permitted."""
        if case.is_synthetic or case.source_type == DisputeSourceType.SYNTHETIC_DEMO:
            raise ValueError("Synthetic dispute cases cannot be accepted via PayPal API")
        if not self.is_enabled():
            raise PayPalDisputesDisabledError(
                "PayPal Disputes API is disabled; set PAYPAL_DISPUTES_API_ENABLED=true in sandbox mode."
            )
        if not case.paypal_dispute_id:
            raise ValueError("paypal_dispute_id is required to accept dispute claim")

        client = self._get_client()
        result = await client.accept_claim(case.paypal_dispute_id, note=note)
        return {
            "status": "ACCEPTED",
            "paypal_dispute_id": case.paypal_dispute_id,
            "case_id": str(case.id),
            "result": result,
        }
