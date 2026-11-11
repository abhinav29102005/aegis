"""Comprehensive integration tests for the unified AEGIS FastAPI platform."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from aegis_api.app import create_app
from contracts import DecisionOutcome, DisputeStatus, PaymentState
from fastapi.testclient import TestClient
from paypal import PayPalSandboxClient
from security import NexusSettings, Role


def _build_mock_paypal_client(*, webhook_verified: bool = True) -> tuple[PayPalSandboxClient, dict[str, str]]:
    """Build a PayPalSandboxClient backed by stateful httpx.MockTransport."""
    state: dict[str, str] = {"order_status": "CREATED", "webhook_verified": "true" if webhook_verified else "false"}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "mock-pp-token", "expires_in": 3600})
        if path == "/v2/checkout/orders" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "PP-ORDER-TEST-001",
                    "status": "CREATED",
                    "links": [
                        {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP-ORDER-TEST-001"}
                    ],
                },
            )
        if path.startswith("/v2/checkout/orders/") and request.method == "GET":
            order_id = path.rsplit("/", 1)[-1]
            if state["order_status"] == "COMPLETED":
                return httpx.Response(
                    200,
                    json={
                        "id": order_id,
                        "status": "COMPLETED",
                        "purchase_units": [
                            {
                                "payments": {
                                    "captures": [
                                        {
                                            "id": "PP-CAP-001",
                                            "status": "COMPLETED",
                                            "amount": {"currency_code": "USD", "value": "39.00"},
                                        }
                                    ]
                                }
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"id": order_id, "status": state["order_status"]})
        if path.endswith("/capture") and request.method == "POST":
            state["order_status"] = "COMPLETED"
            return httpx.Response(
                201,
                json={
                    "id": "PP-ORDER-TEST-001",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": "PP-CAP-001",
                                        "status": "COMPLETED",
                                        "amount": {"currency_code": "USD", "value": "39.00"},
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if path == "/v1/notifications/verify-webhook-signature":
            verdict = "SUCCESS" if state["webhook_verified"] == "true" else "FAILURE"
            return httpx.Response(200, json={"verification_status": verdict})
        return httpx.Response(404, json={"error": f"Unhandled mock path {path}"})

    settings = NexusSettings(
        paypal_client_id="sandbox-client",
        paypal_client_secret="sandbox-secret",
        paypal_webhook_id="WH-123",
    )
    async_client = httpx.AsyncClient(base_url="https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    return PayPalSandboxClient(settings=settings, http_client=async_client), state


@pytest.fixture()
def platform_env(tmp_path: Path):
    db_path = tmp_path / "aegis_api_test.db"
    evidence_dir = tmp_path / "evidence"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret-for-platform-tests-32b",
        signing_secret="test-hmac-secret-for-platform-tests",
        evidence_storage_dir=str(evidence_dir),
        rate_limit_rpm=5000,
        paypal_client_id="sandbox-client",
        paypal_client_secret="sandbox-secret",
        paypal_webhook_id="WH-123",
    )
    paypal_client, pp_state = _build_mock_paypal_client()
    app = create_app(settings=settings, paypal_client=paypal_client, create_tables=True)
    with TestClient(app) as client:
        yield client, settings, pp_state, db_path, evidence_dir


def test_auth_rbac_tenant_isolation_and_api_key_lifecycle(platform_env) -> None:
    client, _, _, _, _ = platform_env

    # Unauthenticated requests or forged X-Tenant-Id header are rejected fail-closed
    unauth = client.get("/v1/overview/metrics", headers={"X-Tenant-Id": str(uuid4())})
    assert unauth.status_code == 401

    # Register Org A owner
    reg_a = client.post(
        "/v1/auth/register",
        json={
            "email": "owner-a@example.com",
            "password": "StrongPassword!123",
            "full_name": "Alice Owner",
            "organization_name": "Org Alpha",
            "organization_slug": "org-alpha",
        },
    )
    assert reg_a.status_code == 201
    token_a = reg_a.json()["access_token"]
    org_a_id = reg_a.json()["active_tenant_id"]

    # Register Org B owner
    reg_b = client.post(
        "/v1/auth/register",
        json={
            "email": "owner-b@example.com",
            "password": "StrongPassword!123",
            "full_name": "Bob Owner",
            "organization_name": "Org Beta",
            "organization_slug": "org-beta",
        },
    )
    assert reg_b.status_code == 201
    org_b_id = reg_b.json()["active_tenant_id"]

    # Cross-org spoofing via X-Org-Id without membership must be denied 403
    spoof = client.get(
        "/v1/overview/metrics",
        headers={"Authorization": f"Bearer {token_a}", "X-Org-Id": org_b_id},
    )
    assert spoof.status_code == 403

    # Owner A creates a Viewer and a Service Account API key (AGENT_SERVICE)
    add_viewer = client.post(
        "/v1/orgs/members",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "email": "viewer-a@example.com",
            "full_name": "Vera Viewer",
            "password": "StrongPassword!456",
            "role": Role.VIEWER.value,
        },
    )
    assert add_viewer.status_code == 201

    login_viewer = client.post(
        "/v1/auth/login",
        json={"email": "viewer-a@example.com", "password": "StrongPassword!456"},
    )
    assert login_viewer.status_code == 200
    viewer_token = login_viewer.json()["access_token"]

    # Viewer can read metrics, cannot create agents or approve proposals
    assert client.get("/v1/overview/metrics", headers={"Authorization": f"Bearer {viewer_token}"}).status_code == 200
    assert (
        client.post(
            "/v1/guardian/agents",
            headers={"Authorization": f"Bearer {viewer_token}"},
            json={"name": "rogue", "public_fingerprint": "fp-rogue-12345"},
        ).status_code
        == 403
    )

    # Create service account & API key
    svc_resp = client.post(
        "/v1/orgs/service-accounts",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "purchasing-bot", "description": "LangGraph buyer", "role": Role.AGENT_SERVICE.value},
    )
    assert svc_resp.status_code == 201
    svc_id = svc_resp.json()["id"]

    key_resp = client.post(
        "/v1/orgs/api-keys",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "bot-key-1", "service_account_id": svc_id, "role": Role.AGENT_SERVICE.value},
    )
    assert key_resp.status_code == 201
    raw_key = key_resp.json()["plaintext_key"]
    key_id = key_resp.json()["id"]
    assert raw_key.startswith("aegis_")

    # Service API key can authenticate and read agents, but CANNOT approve human approvals
    assert client.get("/v1/guardian/agents", headers={"X-API-Key": raw_key}).status_code == 200
    denied_approve = client.post(
        f"/v1/guardian/proposals/{uuid4()}/approve",
        headers={"X-API-Key": raw_key},
        json={"approver_id": "bot-tried-to-approve", "approved": True},
    )
    assert denied_approve.status_code == 403

    # Rotate key -> old key immediately stops working, new key works -> revoke -> stops working
    rot_resp = client.post(
        f"/v1/orgs/api-keys/{key_id}/rotate",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert rot_resp.status_code == 200
    new_key = rot_resp.json()["plaintext_key"]
    new_key_id = rot_resp.json()["id"]
    assert client.get("/v1/guardian/agents", headers={"X-API-Key": raw_key}).status_code == 401
    assert client.get("/v1/guardian/agents", headers={"X-API-Key": new_key}).status_code == 200

    assert (
        client.post(
            f"/v1/orgs/api-keys/{new_key_id}/revoke",
            headers={"Authorization": f"Bearer {token_a}"},
        ).status_code
        == 200
    )
    assert client.get("/v1/guardian/agents", headers={"X-API-Key": new_key}).status_code == 401

    # Admin audit logs recorded key issuance, rotation, revocation
    audits = client.get("/v1/orgs/audit-logs", headers={"Authorization": f"Bearer {token_a}"}).json()
    actions = {item["action"] for item in audits["items"]}
    assert {"ORG_REGISTERED", "API_KEY_ISSUED", "API_KEY_ROTATED", "API_KEY_REVOKED"}.issubset(actions)
    assert org_a_id != org_b_id


def test_full_guardian_ghostpay_disputeos_persistence_and_restart_recovery(platform_env) -> None:
    client, settings, pp_state, _, evidence_dir = platform_env

    # 1. Register Org Alpha and Org Beta
    reg_a = client.post(
        "/v1/auth/register",
        json={
            "email": "alpha-ops@example.com",
            "password": "AlphaPassword!123",
            "full_name": "Alpha Ops",
            "organization_name": "Alpha Treasury",
            "organization_slug": "alpha-treasury",
        },
    ).json()
    headers_a = {"Authorization": f"Bearer {reg_a['access_token']}"}
    tenant_a = UUID(reg_a["active_tenant_id"])

    reg_b = client.post(
        "/v1/auth/register",
        json={
            "email": "beta-ops@example.com",
            "password": "BetaPassword!123",
            "full_name": "Beta Ops",
            "organization_name": "Beta Treasury",
            "organization_slug": "beta-treasury",
        },
    ).json()
    headers_b = {"Authorization": f"Bearer {reg_b['access_token']}"}

    # 2. Guardian onboarding: Agent, Merchant, Passport, Budget
    agent = client.post(
        "/v1/guardian/agents",
        headers=headers_a,
        json={"name": "Procurement-AI", "purpose": "Cloud SaaS procurement", "public_fingerprint": "fp-alpha-001"},
    )
    assert agent.status_code == 201
    agent_id = agent.json()["id"]

    merchant = client.post(
        "/v1/guardian/merchants",
        headers=headers_a,
        json={"name": "CloudDocs Pro", "domain": "clouddocs.example.com", "category": "SOFTWARE", "is_allowlisted": True},
    )
    assert merchant.status_code == 201
    merchant_id = merchant.json()["id"]

    passport = client.post(
        "/v1/guardian/passports",
        headers=headers_a,
        json={
            "agent_id": agent_id,
            "total_budget_minor": 10000,
            "per_tx_limit_minor": 5000,
            "daily_limit_minor": 8000,
            "human_approval_threshold_minor": 3000,
            "allowed_merchant_ids": [merchant_id],
            "allowed_categories": ["SOFTWARE"],
        },
    )
    assert passport.status_code == 201
    passport_id = passport.json()["id"]

    # 3. Submit proposal ($39.00 -> above $30 approval threshold -> AWAITING_APPROVAL)
    proposal_body = {
        "agent_id": agent_id,
        "passport_id": passport_id,
        "merchant_id": merchant_id,
        "merchant_name": "CloudDocs Pro",
        "merchant_category": "SOFTWARE",
        "amount_minor": 3900,
        "currency": "USD",
        "item_summary": "Annual Pro Plan",
        "rationale": "Needed for documentation pipeline",
        "idempotency_key": "idem-alpha-3900-1",
    }
    prop_resp = client.post("/v1/guardian/proposals", headers=headers_a, json=proposal_body)
    assert prop_resp.status_code == 201
    prop_data = prop_resp.json()
    assert prop_data["decision"]["outcome"] == DecisionOutcome.ESCALATE.value
    intent_id = prop_data["payment_intent"]["id"]
    correlation_id = prop_data["payment_intent"]["correlation_id"]
    assert prop_data["payment_intent"]["state"] == PaymentState.AWAITING_APPROVAL.value

    # Idempotent replay returns same intent without duplicate reservation
    prop_dup = client.post("/v1/guardian/proposals", headers=headers_a, json=proposal_body)
    assert prop_dup.status_code == 201
    assert prop_dup.json()["payment_intent"]["id"] == intent_id

    # Cross-tenant Org B cannot read Org A's payment
    assert client.get(f"/v1/guardian/payments/{intent_id}", headers=headers_b).status_code == 403

    # 4. Human approval -> Checkout -> Buyer approved -> Capture
    approve_resp = client.post(
        f"/v1/guardian/proposals/{intent_id}/approve",
        headers=headers_a,
        json={"approver_id": "ignored", "approved": True, "comment": "Approved by treasury lead"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["payment_intent"]["state"] == PaymentState.CHECKOUT_READY.value

    checkout_resp = client.post(
        f"/v1/guardian/payments/{intent_id}/checkout",
        headers=headers_a,
        json={"attempt_number": 1},
    )
    assert checkout_resp.status_code == 200
    attempt_id = checkout_resp.json()["attempt"]["id"]
    assert checkout_resp.json()["attempt"]["paypal_order_id"] == "PP-ORDER-TEST-001"
    assert checkout_resp.json()["payment_intent"]["state"] == PaymentState.AWAITING_PAYPAL_BUYER.value

    pp_state["order_status"] = "APPROVED"
    buyer_resp = client.post(
        f"/v1/guardian/payments/{intent_id}/buyer-approved",
        headers=headers_a,
        json={"attempt_id": attempt_id, "payer_id": "PAYER-TEST-01"},
    )
    assert buyer_resp.status_code == 200
    assert buyer_resp.json()["attempt"]["buyer_approval"]["payer_id"] == "PAYER-TEST-01"

    capture_resp = client.post(
        f"/v1/guardian/payments/{intent_id}/capture",
        headers=headers_a,
        json={"attempt_id": attempt_id},
    )
    assert capture_resp.status_code == 200
    assert capture_resp.json()["payment_intent"]["state"] == PaymentState.SUCCEEDED.value

    # PayPal signed webhook fails closed on invalid signature and records on valid signature
    pp_headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
        "paypal-transmission-id": "TX-1",
        "paypal-transmission-sig": "sig-placeholder",
        "paypal-transmission-time": "2026-11-11T00:00:00Z",
    }
    pp_state["webhook_verified"] = "false"
    bad_wh = client.post(
        "/v1/paypal/webhooks",
        headers=pp_headers,
        json={"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
    )
    assert bad_wh.status_code == 401

    pp_state["webhook_verified"] = "true"
    good_wh = client.post(
        "/v1/paypal/webhooks",
        headers=pp_headers,
        json={
            "id": "WH-EVT-2",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "PP-CAP-001", "supplementary_data": {"related_ids": {"order_id": "PP-ORDER-TEST-001"}}},
        },
    )
    assert good_wh.status_code == 200
    assert good_wh.json()["matched_payment_intent_id"] == intent_id

    # 5. GhostPay DB-backed Replay, Counterfactual Simulation, Timeline, and Persisted Investigations
    replay_resp = client.post(f"/v1/ghostpay/replay/by-payment/{intent_id}", headers=headers_a, json={})
    assert replay_resp.status_code == 200
    replay_body = replay_resp.json()
    assert replay_body["executed_payment"] is False
    assert replay_body["integrity_valid"] is True
    assert replay_body["anomalies"] == []

    sim_resp = client.post(
        f"/v1/ghostpay/simulate/by-payment/{intent_id}",
        headers=headers_a,
        json={"overrides": {"per_tx_limit_minor": 2000, "allow_unknown_merchants": False}, "persist_investigation": True},
    )
    assert sim_resp.status_code == 200
    assert sim_resp.json()["recomputed_outcome"] == DecisionOutcome.DENY.value
    assert sim_resp.json()["original_outcome"] != sim_resp.json()["recomputed_outcome"]

    inv_list = client.get("/v1/ghostpay/investigations", headers=headers_a).json()
    assert inv_list["total"] >= 2

    # 6. DisputeOS DB-backed Case, Object Storage Artifact Upload/Download, Analysis, Report & Human Gate
    case_resp = client.post(
        "/v1/disputeos/cases",
        headers=headers_a,
        json={
            "correlation_id": correlation_id,
            "payment_intent_id": intent_id,
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "buyer_claim": "Customer claims SaaS seat provisioning never arrived.",
            "amount_minor": 3900,
            "currency": "USD",
            "source_type": "SYNTHETIC_DEMO",
            "is_synthetic": True,
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["id"]

    # Assign & add note
    assert (
        client.post(f"/v1/disputeos/cases/{case_id}/assign", headers=headers_a, json={"assigned_to": "investigator@example.com"}).status_code
        == 200
    )
    assert (
        client.post(f"/v1/disputeos/cases/{case_id}/notes", headers=headers_a, json={"body": "Verified TLS provisioning logs."}).status_code
        == 200
    )

    # Upload real binary artifact stored on disk (not inside DB), verify hash & download, and tenant isolation
    payload_bytes = b"Invoice #INV-2026-001\nProvisioned License: active\n"
    upload_resp = client.post(
        f"/v1/disputeos/cases/{case_id}/artifacts",
        headers=headers_a,
        files={"file": ("delivery-receipt.txt", payload_bytes, "text/plain")},
        data={"title": "Signed Provisioning Receipt", "source_type": "DELIVERY_RECEIPT"},
    )
    assert upload_resp.status_code == 201
    artifact_id = upload_resp.json()["artifact_id"]
    assert upload_resp.json()["sha256"] == hashlib.sha256(payload_bytes).hexdigest()

    # Cross-tenant download must fail 403
    assert client.get(f"/v1/disputeos/cases/{case_id}/artifacts/{artifact_id}", headers=headers_b).status_code == 403

    dl_resp = client.get(f"/v1/disputeos/cases/{case_id}/artifacts/{artifact_id}", headers=headers_a)
    assert dl_resp.status_code == 200
    assert dl_resp.content == payload_bytes
    assert any(evidence_dir.rglob("*delivery-receipt.txt"))

    # Analyze & verify human approval gate before submit + synthetic submission block
    analyze_resp = client.post(f"/v1/disputeos/cases/{case_id}/analyze", headers=headers_a)
    assert analyze_resp.status_code == 200
    assert analyze_resp.json()["report"]["case_id"] == case_id

    unapproved_submit = client.post(f"/v1/disputeos/cases/{case_id}/submit", headers=headers_a)
    assert unapproved_submit.status_code == 403

    approve_case_resp = client.post(
        f"/v1/disputeos/cases/{case_id}/approve",
        headers=headers_a,
        json={"approver_id": "ignored", "draft_response_text": "Provisioning logs confirm active delivery."},
    )
    assert approve_case_resp.status_code == 200
    assert approve_case_resp.json()["status"] == DisputeStatus.APPROVED_FOR_SUBMISSION.value

    synthetic_submit = client.post(f"/v1/disputeos/cases/{case_id}/submit", headers=headers_a)
    assert synthetic_submit.status_code == 403
    assert "synthetic" in str(synthetic_submit.json()).lower()

    # 7. Overview metrics & Audit Chain verification
    overview = client.get("/v1/overview/metrics", headers=headers_a).json()
    assert overview["payments"]["by_state"].get(PaymentState.SUCCEEDED.value) == 1
    assert overview["budget"]["spent_minor"] == 3900
    assert overview["open_disputes"] == 1

    audit = client.get(
        "/v1/audit-events",
        headers=headers_a,
        params={"correlation_id": correlation_id},
    ).json()
    assert audit["chain_verified"] is True
    assert audit["count"] >= 6

    # 8. Simulate full API server restart with a brand-new FastAPI app pointing at the same SQLite DB
    paypal_client_2, _ = _build_mock_paypal_client()
    app_restarted = create_app(settings=settings, paypal_client=paypal_client_2, create_tables=False)
    with TestClient(app_restarted) as client_2:
        login_a = client_2.post(
            "/v1/auth/login",
            json={"email": "alpha-ops@example.com", "password": "AlphaPassword!123"},
        ).json()
        h2 = {"Authorization": f"Bearer {login_a['access_token']}"}
        detail = client_2.get(f"/v1/guardian/payments/{intent_id}/detail", headers=h2).json()
        assert detail["payment_intent"]["state"] == PaymentState.SUCCEEDED.value
        assert len(detail["events"]) >= 6

        persisted_case = client_2.get(f"/v1/disputeos/cases/{case_id}", headers=h2).json()
        assert persisted_case["assigned_to"] == "investigator@example.com"
        assert len(persisted_case["notes"]) == 1
        assert len(persisted_case["artifacts"]) == 1

        persisted_inv = client_2.get("/v1/ghostpay/investigations", headers=h2).json()
        assert persisted_inv["total"] >= 2
        assert tenant_a is not None


def test_rate_limiter_enforces_429(tmp_path: Path) -> None:
    db_path = tmp_path / "ratelimit.db"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-rate-limit-secret-key-32-chars",
        rate_limit_rpm=2,
    )
    app = create_app(settings=settings, create_tables=True)
    with TestClient(app) as client:
        # /health is exempt
        for _ in range(5):
            assert client.get("/health").status_code == 200
        # Other routes trigger 429 on 3rd call
        assert client.get("/v1/overview/metrics").status_code == 401
        assert client.get("/v1/overview/metrics").status_code == 401
        limited = client.get("/v1/overview/metrics")
        assert limited.status_code == 429
        assert limited.json()["error_code"] == "RATE_LIMIT_EXCEEDED"
