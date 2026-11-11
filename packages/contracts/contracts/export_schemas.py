"""Export canonical JSON Schema definitions for all shared Nexus contracts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from contracts.models import (
    AgentIdentity,
    ApprovalRecord,
    AuthorizationDecision,
    BudgetReservation,
    DisputeAnalysis,
    DisputeCase,
    EvidenceRecord,
    FinancialEvent,
    Merchant,
    PaymentAttempt,
    PaymentIntent,
    PurchaseProposal,
    QuoteSnapshot,
    ReplayRequest,
    ReplayResult,
    SpendingPassport,
    Tenant,
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
    PaymentAttempt,
    FinancialEvent,
    EvidenceRecord,
    ReplayRequest,
    ReplayResult,
    DisputeCase,
    DisputeAnalysis,
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

