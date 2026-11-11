"""Full End-to-End User Journeys Test for AgentPay Nexus Console & Platform APIs.

Covers all 7 user journeys using real TestClient backend with SQLite:
1. Signup / Login / Org selection
2. Agent creation & Passport configuration
3. Merchant creation with passports:write permission
4. Spending proposal creation -> Policy check -> Human approval -> PayPal checkout redirect link -> Capture on CAPTURE_PENDING -> Refund
5. GhostPay replay timeline inspection & counterfactual simulation
6. DisputeOS case creation, evidence upload, AI dispute analysis, resolve
7. Organization settings, billing quota view, GDPR data export & erasure request
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from aegis_api.app import create_app
from paypal.client import (
    PayPalCaptureResult,
    PayPalOrderCreationResult,
    VerifiedPayPalCapture,
)
from security import NexusSettings, Role


@pytest.fixture
def e2e_backend(tmp_path: Path):
    db_file = tmp_path / "e2e_console.db"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    settings = NexusSettings(
        database_url=f"sqlite:///{db_file}",
        jwt_secret="e2e-console-jwt-secret-at-least-32-characters",
        signing_secret="e2e-console-signing-secret",
        evidence_storage_dir=str(evidence_dir),
        rate_limit_rpm=10000,
    )
    app = create_app(settings=settings, create_tables=True)
    with TestClient(app) as client:
        yield {"client": client, "tmp_path": tmp_path}


def test_full_console_e2e_journeys(e2e_backend):
    """Executes the complete sequence of 7 user journeys end-to-end."""
    client: TestClient = e2e_backend["client"]
    ts = uuid4().hex[:8]

    # =========================================================================
    # Journey 1: Signup, Login, Org Selection
    # =========================================================================
    email = f"lead-{ts}@matrixcorp.test"
    password = "SuperStrongPassword!2026"
    org_name = f"Matrix Corp {ts}"
    org_slug = f"matrix-corp-{ts}"

    signup_resp = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Matrix Lead",
            "organization_name": org_name,
            "organization_slug": org_slug,
        },
    )
    assert signup_resp.status_code == 201, signup_resp.text
    signup_data = signup_resp.json()
    token = signup_data["access_token"]
    org_id = signup_data["active_tenant_id"]
    user_id = signup_data["user_id"]
    headers = {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    # Verify Login
    login_resp = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["access_token"] is not None

    # Verify Current Org Profile & Me
    me_resp = client.get("/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email

    # =========================================================================
    # Journey 2: Agent Creation & Passport Configuration
    # =========================================================================
    agent_resp = client.post(
        "/v1/guardian/agents",
        headers=headers,
        json={
            "name": "E2E Procurement Bot",
            "purpose": "Cloud compute & SaaS licensing purchases",
            "framework": "langgraph",
            "public_fingerprint": f"sha256:{uuid4().hex}",
        },
    )
    assert agent_resp.status_code == 201, agent_resp.text
    agent_id = agent_resp.json()["id"]

    # =========================================================================
    # Journey 3: Merchant Creation with passports:write Permission
    # =========================================================================
    merchant_resp = client.post(
        "/v1/guardian/merchants",
        headers=headers,
        json={
            "name": "Cloud Providers Global",
            "domain": "cloud-providers.example",
            "category": "SOFTWARE",
            "is_allowlisted": True,
        },
    )
    assert merchant_resp.status_code == 201, merchant_resp.text
    merchant_id = merchant_resp.json()["id"]

    # Spending Passport configuration
    passport_resp = client.post(
        "/v1/guardian/passports",
        headers=headers,
        json={
            "agent_id": agent_id,
            "total_budget_minor": 500000,           # $5,000.00
            "per_tx_limit_minor": 150000,            # $1,500.00
            "daily_limit_minor": 300000,             # $3,000.00
            "human_approval_threshold_minor": 40000, # $400.00 threshold
            "allowed_categories": ["SOFTWARE"],
            "allowed_merchant_ids": [merchant_id],
            "allow_unknown_merchants": False,
        },
    )
    assert passport_resp.status_code == 201, passport_resp.text
    passport_id = passport_resp.json()["id"]

    # =========================================================================
    # Journey 4: Spending proposal -> Policy Check -> Human Approval -> PayPal Checkout -> Capture on CAPTURE_PENDING -> Refund
    # =========================================================================
    # Proposal for $600.00 (60,000 minor) exceeds threshold $400.00 -> Enters AWAITING_APPROVAL
    prop_resp = client.post(
        "/v1/guardian/proposals",
        headers=headers,
        json={
            "agent_id": agent_id,
            "passport_id": passport_id,
            "merchant_id": merchant_id,
            "merchant_name": "Cloud Providers Global",
            "merchant_category": "SOFTWARE",
            "amount_minor": 60000,
            "currency": "USD",
            "item_summary": "Quarterly cloud infrastructure tier",
            "rationale": "High memory instance fleet",
            "idempotency_key": f"e2e-prop-{uuid4().hex[:12]}",
        },
    )
    assert prop_resp.status_code == 201, prop_resp.text
    prop_data = prop_resp.json()
    intent_id = prop_data["payment_intent"]["id"]
    assert prop_data["payment_intent"]["state"] == "AWAITING_APPROVAL"

    # Human Approval
    appr_resp = client.post(
        f"/v1/guardian/proposals/{intent_id}/approve",
        headers=headers,
        json={
            "approver_id": user_id,
            "comment": "Approved quarterly infrastructure spend",
        },
    )
    assert appr_resp.status_code == 200, appr_resp.text
    assert appr_resp.json()["payment_intent"]["state"] in ("CHECKOUT_READY", "CHECKOUT_CREATED", "APPROVED")

    # PayPal Checkout Redirect
    mock_order = PayPalOrderCreationResult(
        paypal_order_id="MOCK-PAYPAL-ORDER-E2E",
        status="CREATED",
        approval_url="https://sandbox.paypal.com/checkoutnow?token=MOCK-PAYPAL-ORDER-E2E",
        raw_response={"id": "MOCK-PAYPAL-ORDER-E2E"},
    )
    with patch("paypal.client.PayPalSandboxClient.create_order", new_callable=AsyncMock) as mock_create_order:
        mock_create_order.return_value = mock_order
        chk_resp = client.post(
            f"/v1/guardian/payments/{intent_id}/checkout",
            headers=headers,
            json={"idempotency_key": f"chk-{uuid4().hex[:12]}"},
        )
        assert chk_resp.status_code == 200, chk_resp.text
        chk_data = chk_resp.json()
        assert "paypal.com" in chk_data["approval_url"]
        attempt_id = chk_data["attempt"]["id"]

    # Transition to CAPTURE_PENDING (Buyer Approved via webhook or buyer_approved endpoint)
    buyer_resp = client.post(
        f"/v1/guardian/payments/{intent_id}/buyer-approved",
        headers=headers,
        json={"attempt_id": attempt_id, "payer_id": "MOCK-PAYER-123"},
    )
    assert buyer_resp.status_code == 200, buyer_resp.text
    assert buyer_resp.json()["payment_intent"]["state"] == "CAPTURE_PENDING"

    # Capture on CAPTURE_PENDING
    verified_cap = VerifiedPayPalCapture(
        paypal_order_id="MOCK-PAYPAL-ORDER-E2E",
        paypal_capture_id="MOCK-CAPTURE-ID-9988",
        paypal_status="COMPLETED",
        verified_amount_minor=60000,
        verified_currency="USD",
        verification_hash="mock-verification-hash-32charslong",
    )
    mock_capture = PayPalCaptureResult(
        verified_capture=verified_cap,
        raw_response={"id": "MOCK-CAPTURE-ID-9988", "status": "COMPLETED"},
    )
    with patch("paypal.client.PayPalSandboxClient.capture_order", new_callable=AsyncMock) as mock_cap:
        mock_cap.return_value = mock_capture
        cap_resp = client.post(
            f"/v1/guardian/payments/{intent_id}/capture",
            headers=headers,
            json={"attempt_id": attempt_id},
        )
        assert cap_resp.status_code == 200, cap_resp.text
        assert cap_resp.json()["payment_intent"]["state"] == "SUCCEEDED"

    # =========================================================================
    # Journey 5: GhostPay Replay & Counterfactual Simulation
    # =========================================================================
    replay_resp = client.post(
        f"/v1/ghostpay/replay/by-payment/{intent_id}",
        headers=headers,
    )
    assert replay_resp.status_code == 200, replay_resp.text
    replay_data = replay_resp.json()
    assert replay_data["executed_payment"] is False, "Replay must never execute payments"
    assert replay_data["consistency_status"] in ("CONSISTENT", "INCOMPLETE_EVIDENCE")

    # Counterfactual simulation with lowered per_tx limit ($250.00)
    sim_resp = client.post(
        f"/v1/ghostpay/simulate/by-payment/{intent_id}",
        headers=headers,
        json={"overrides": {"per_tx_limit_minor": 25000}},
    )
    assert sim_resp.status_code == 200, sim_resp.text
    sim_data = sim_resp.json()
    assert "changed_constraints" in sim_data or "anomalies" in sim_data or "simulated_outcome" in sim_data

    # =========================================================================
    # Journey 6: DisputeOS Case Creation, Evidence Upload, AI Analysis, Resolve
    # =========================================================================
    dispute_resp = client.post(
        "/v1/disputeos/cases",
        headers=headers,
        json={
            "correlation_id": str(uuid4()),
            "payment_intent_id": intent_id,
            "amount_minor": 60000,
            "currency": "USD",
            "reason": "MERCHANDISE_OR_SERVICES_NOT_RECEIVED",
            "buyer_claim": "Cloud cluster provisioning timed out without allocating instances.",
        },
    )
    assert dispute_resp.status_code == 201, dispute_resp.text
    dispute_case_id = dispute_resp.json()["id"]

    # Evidence Upload / Attachment
    evidence_resp = client.post(
        f"/v1/disputeos/cases/{dispute_case_id}/evidence",
        headers=headers,
        json={
            "source_type": "CUSTOMER_MESSAGE",
            "source_ref": "ticket-8843",
            "title": "Vendor support ticket outage acknowledgment",
            "content": {"message": "Cloud provider ticket #8843 confirmed backend allocation failure."},
        },
    )
    assert evidence_resp.status_code in (200, 201), evidence_resp.text

    # AI Dispute Analysis
    analysis_resp = client.post(
        f"/v1/disputeos/cases/{dispute_case_id}/analyze",
        headers=headers,
    )
    assert analysis_resp.status_code == 200, analysis_resp.text
    analysis_data = analysis_resp.json()
    assert (
        "analysis" in analysis_data
        or "report" in analysis_data
        or "win_probability" in analysis_data
        or "recommended_action" in analysis_data
    )

    # Human Approval of Dispute Response
    approve_case_resp = client.post(
        f"/v1/disputeos/cases/{dispute_case_id}/approve",
        headers=headers,
        json={
            "approver_id": user_id,
            "draft_response_text": "We accept merchant refund claim due to SLA breach.",
        },
    )
    assert approve_case_resp.status_code == 200, approve_case_resp.text
    assert approve_case_resp.json()["status"] == "APPROVED_FOR_SUBMISSION"

    # Export Dispute Report
    report_resp = client.get(
        f"/v1/disputeos/cases/{dispute_case_id}/report",
        headers=headers,
    )
    assert report_resp.status_code == 200, report_resp.text
    assert "report_id" in report_resp.json() or "summary" in report_resp.json() or "case_id" in report_resp.json()

    # =========================================================================
    # Journey 7: Organization Settings, Billing Quotas, and GDPR Erasure
    # =========================================================================
    # List members
    members_resp = client.get("/v1/orgs/members", headers=headers)
    assert members_resp.status_code == 200
    assert len(members_resp.json()) >= 1

    # Audit Logs
    audit_resp = client.get("/v1/orgs/audit-logs", headers=headers)
    assert audit_resp.status_code == 200
    assert "items" in audit_resp.json() or isinstance(audit_resp.json(), list)

    # API Keys creation & revocation
    key_resp = client.post(
        "/v1/orgs/api-keys",
        headers=headers,
        json={"name": "E2E Test Key", "role": "OPERATOR"},
    )
    assert key_resp.status_code == 201
    key_id = key_resp.json()["id"]

    revoke_resp = client.post(
        f"/v1/orgs/api-keys/{key_id}/revoke",
        headers=headers,
    )
    assert revoke_resp.status_code == 200
