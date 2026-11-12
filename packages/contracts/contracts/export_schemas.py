"""Export canonical JSON Schema definitions for all shared Nexus contracts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from contracts.models import (
    AgentIdentity,
    AP2CheckoutMandate,
    AP2MandatePayload,
    AP2PaymentMandate,
    ApprovalRecord,
    AuthorizationDecision,
    BudgetReservation,
    DeflectionAlert,
    DisputeAnalysis,
    DisputeCase,
    DisputeEvidenceCitation,
    EvidenceRecord,
    FinancialEvent,
    Merchant,
    PaymentAttempt,
    PaymentIntent,
    PayPalBuyerApproval,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    ReplayTimelineEntry,
    SpendingPassport,
    StripeEventEnvelope,
    StripePaymentIntentPayload,
    StripeSharedPaymentToken,
    StripeSmartDisputePayload,
    TAPTokenPayload,
    Tenant,
    TokenProvenanceProof,
    VerifiedPayPalCapture,
    X402SettlementProof,
)

MODELS = [
    Tenant,
    AgentIdentity,
    Merchant,
    SpendingPassport,
    PurchaseProposal,
    QuoteSnapshot,
    PaymentIntent,
    AuthorizationDecision,
    ApprovalRecord,
    BudgetReservation,
    PayPalBuyerApproval,
    VerifiedPayPalCapture,
    PaymentAttempt,
    FinancialEvent,
    EvidenceRecord,
    ReplayTimelineEntry,
    ReplayRequest,
    ReplayResult,
    DisputeCase,
    DisputeEvidenceCitation,
    DisputeAnalysis,
    DeflectionAlert,
    AP2CheckoutMandate,
    AP2PaymentMandate,
    AP2MandatePayload,
    TokenProvenanceProof,
    TAPTokenPayload,
    X402SettlementProof,
    StripePaymentIntentPayload,
    StripeSharedPaymentToken,
    StripeSmartDisputePayload,
    StripeEventEnvelope,
]


def export_all_schemas(output_path: Path | None = None) -> dict:
    _, top_schema = models_json_schema(
        [(m, "validation") for m in MODELS],
        title="AgentPay Nexus Canonical Contracts",
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(top_schema, indent=2) + "\n", encoding="utf-8")
    return top_schema


if __name__ == "__main__":
    default_out = Path(__file__).resolve().parent.parent / "schemas" / "contracts.schema.json"
    export_all_schemas(default_out)
    print(f"Exported schemas to {default_out}")

