"""Tests for the official AEGIS Python SDK and LangGraph-compatible AgentAuthorizationTool."""

from __future__ import annotations

from pathlib import Path

from aegis_api.app import create_app
from aegis_sdk import (
    AegisAPIError,
    AegisClient,
    AgentAuthorizationTool,
    verify_webhook_signature,
)
from contracts import PaymentState
from fastapi.testclient import TestClient
from security import NexusSettings, Role, sign_hmac_sha256


def test_python_sdk_full_agent_and_replay_flow(tmp_path: Path) -> None:
    settings = NexusSettings(
        database_url=f"sqlite:///{tmp_path / 'sdk.db'}",
        jwt_secret="sdk-test-jwt-secret-key-at-least-32-bytes",
        evidence_storage_dir=str(tmp_path / "ev"),
        rate_limit_rpm=5000,
    )
    app = create_app(settings=settings, create_tables=True)

    with TestClient(app) as tc:
        sdk = AegisClient(client=tc)
        reg = sdk.register(
            email="sdk-owner@example.com",
            password="StrongPassword!123",
            full_name="SDK Owner",
            organization_name="SDK Org",
            organization_slug="sdk-org",
        )
        sdk.set_token(reg["access_token"])

        agent = tc.post(
            "/v1/guardian/agents",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
            json={"name": "SDK-Agent", "public_fingerprint": "fp-sdk-001"},
        ).json()
        merchant = tc.post(
            "/v1/guardian/merchants",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
            json={"name": "SDK Vendor", "domain": "vendor.example.com", "category": "SOFTWARE", "is_allowlisted": True},
        ).json()
        passport = tc.post(
            "/v1/guardian/passports",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
            json={
                "agent_id": agent["id"],
                "total_budget_minor": 10000,
                "per_tx_limit_minor": 5000,
                "daily_limit_minor": 10000,
                "human_approval_threshold_minor": 4000,
                "allowed_merchant_ids": [merchant["id"]],
                "allowed_categories": ["SOFTWARE"],
            },
        ).json()

        svc = tc.post(
            "/v1/orgs/service-accounts",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
            json={"name": "sdk-svc", "role": Role.AGENT_SERVICE.value},
        ).json()
        api_key = tc.post(
            "/v1/orgs/api-keys",
            headers={"Authorization": f"Bearer {reg['access_token']}"},
            json={"name": "sdk-key", "service_account_id": svc["id"], "role": Role.AGENT_SERVICE.value},
        ).json()["plaintext_key"]

        # Agent uses restricted AGENT_SERVICE API key via AgentAuthorizationTool
        agent_client = AegisClient(client=tc, api_key=api_key)
        tool = AgentAuthorizationTool(agent_client, agent_id=agent["id"], passport_id=passport["id"])
        proposal = tool.request_purchase_authorization(
            merchant_id=merchant["id"],
            merchant_name="SDK Vendor",
            merchant_category="SOFTWARE",
            amount_minor=1900,
            item_summary="SDK Tool Run",
            rationale="Automated build tool license",
            idempotency_key="sdk-auto-1900",
        )
        intent_id = proposal["payment_intent"]["id"]
        assert proposal["payment_intent"]["state"] == PaymentState.CHECKOUT_READY.value

        # Agent attempts to self-approve -> blocked by RBAC with AegisAPIError 403
        try:
            agent_client.approve_proposal(intent_id, approver_id="rogue-agent")
            raise AssertionError("Expected AegisAPIError 403")
        except AegisAPIError as exc:
            assert exc.status_code == 403

        # Owner runs GhostPay replay & counterfactual simulation via SDK
        replay = sdk.replay_by_payment(intent_id)
        assert replay["executed_payment"] is False
        assert replay["integrity_valid"] is True
        sim = sdk.simulate_by_payment(intent_id, overrides={"per_tx_limit_minor": 1000})
        assert sim["recomputed_outcome"] == "DENY"
        assert sim["original_outcome"] != sim["recomputed_outcome"]
        invs = sdk.list_investigations(payment_intent_id=intent_id)
        assert invs["total"] >= 2


def test_sdk_webhook_signature_helper() -> None:
    secret = "whsec_abc123"
    body = {"id": "evt-1", "event_type": "PAYMENT_CAPTURED", "payload": {"amount_minor": 3900}}
    sig = f"sha256={sign_hmac_sha256(body, secret)}"
    assert verify_webhook_signature(payload_body=body, signature_header=sig, signing_secret=secret) is True
    assert verify_webhook_signature(payload_body=body, signature_header="sha256=deadbeef", signing_secret=secret) is False
