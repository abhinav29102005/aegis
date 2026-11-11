"""Tests for the official AEGIS Python SDK, AsyncAegisClient, and AI agent middleware."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from aegis_api.app import create_app
from aegis_sdk import (
    AegisAPIError,
    AegisClient,
    AgentAuthorizationTool,
    AsyncAegisClient,
    AsyncAgentAuthorizationTool,
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


def test_sync_sdk_full_platform_operations(tmp_path: Path) -> None:
    settings = NexusSettings(
        database_url=f"sqlite:///{tmp_path / 'platform.db'}",
        jwt_secret="platform-test-jwt-secret-key-32-bytes",
        evidence_storage_dir=str(tmp_path / "ev"),
        rate_limit_rpm=5000,
    )
    app = create_app(settings=settings, create_tables=True)

    with TestClient(app) as tc:
        client = AegisClient(client=tc)

        # 1. Auth & Org Management
        reg = client.register(
            email="platform-admin@example.com",
            password="AdminPassword!123",
            full_name="Platform Admin",
            organization_name="Platform Primary",
            organization_slug="platform-primary",
        )
        assert "access_token" in reg
        client.set_token(reg["access_token"])

        me_info = client.me()
        assert me_info["email"] == "platform-admin@example.com"
        assert len(client.list_orgs()) >= 1

        updated_org = client.update_current_org(name="Platform Primary Renamed")
        assert updated_org["name"] == "Platform Primary Renamed"

        sub_org = client.create_org(name="Platform Secondary", slug="platform-sec")
        assert sub_org["slug"] == "platform-sec"

        member = client.invite_member(
            email="invited-operator@example.com",
            full_name="Invited Operator",
            password="InvitedPassword!123",
            role="OPERATOR",
        )
        assert member["email"] == "invited-operator@example.com"
        members = client.list_members()
        assert len(members) >= 2

        updated_role = client.update_member_role(member["user_id"], role="AUDITOR")
        assert updated_role["role"] == "AUDITOR"

        # 2. Guardian: Agents, Merchants, Passports
        agent = client.create_agent(
            name="Autonomous-Procurement-Agent",
            public_fingerprint="fp-procure-001-sec",
            purpose="procurement",
            framework="langchain",
        )
        assert agent["name"] == "Autonomous-Procurement-Agent"
        agents_list = client.list_agents()
        assert len(agents_list) >= 1
        fetched_agent = client.get_agent(agent["id"])
        assert fetched_agent["id"] == agent["id"]

        suspended = client.suspend_agent(agent["id"])
        assert suspended["status"] == "SUSPENDED"
        activated = client.activate_agent(agent["id"])
        assert activated["status"] == "ACTIVE"

        merchant = client.create_merchant(
            name="AWS Cloud",
            domain="aws.amazon.com",
            category="CLOUD_INFRASTRUCTURE",
            is_allowlisted=True,
        )
        assert merchant["name"] == "AWS Cloud"
        merchants_list = client.list_merchants()
        assert len(merchants_list) >= 1
        fetched_m = client.get_merchant(merchant["id"])
        assert fetched_m["id"] == merchant["id"]

        toggled = client.toggle_merchant_allowlist(merchant["id"], is_allowlisted=False)
        assert toggled["is_allowlisted"] is False
        client.toggle_merchant_allowlist(merchant["id"], is_allowlisted=True)

        passport = client.create_passport(
            agent_id=agent["id"],
            total_budget_minor=50000,
            per_tx_limit_minor=10000,
            daily_limit_minor=20000,
            human_approval_threshold_minor=5000,
            allowed_merchant_ids=[merchant["id"]],
            allowed_categories=["CLOUD_INFRASTRUCTURE"],
            currency="USD",
        )
        assert passport["total_budget_minor"] == 50000
        passports = client.list_passports()
        assert len(passports) >= 1
        fetched_p = client.get_passport(passport["id"])
        assert fetched_p["id"] == passport["id"]

        updated_p = client.update_passport_policy(passport["id"], human_approval_threshold_minor=6000)
        assert updated_p["human_approval_threshold_minor"] == 6000

        # 3. Guardian: Proposals, Approvals, Payments
        # Proposal below approval threshold -> CHECKOUT_READY
        prop1 = client.submit_purchase_proposal(
            agent_id=agent["id"],
            passport_id=passport["id"],
            merchant_id=merchant["id"],
            merchant_name="AWS Cloud",
            merchant_category="CLOUD_INFRASTRUCTURE",
            amount_minor=3500,
            item_summary="EC2 Small Instance",
            rationale="Dev testing server",
            idempotency_key="prop-auto-3500",
        )
        p1_intent = prop1["payment_intent"]
        assert p1_intent["state"] == "CHECKOUT_READY"

        p1_fetched = client.get_payment(p1_intent["id"])
        assert p1_fetched["id"] == p1_intent["id"]
        p1_detail = client.get_payment_detail(p1_intent["id"])
        assert p1_detail["payment_intent"]["id"] == p1_intent["id"]

        # Proposal above threshold -> AWAITING_APPROVAL
        prop2 = client.submit_purchase_proposal(
            agent_id=agent["id"],
            passport_id=passport["id"],
            merchant_id=merchant["id"],
            merchant_name="AWS Cloud",
            merchant_category="CLOUD_INFRASTRUCTURE",
            amount_minor=7500,
            item_summary="GPU Instance Cluster",
            rationale="Model fine-tuning run",
            idempotency_key="prop-approval-7500",
        )
        p2_intent = prop2["payment_intent"]
        assert p2_intent["state"] == "AWAITING_APPROVAL"

        approvals = client.list_approvals()
        assert len(approvals) >= 1
        apprv_obj = client.get_approval(approvals[0]["id"])
        assert apprv_obj["id"] == approvals[0]["id"]

        # Approve proposal
        approved_res = client.approve_proposal(
            p2_intent["id"],
            approver_id="platform-admin@example.com",
            comment="Approved by manager for high-priority training",
            approved=True,
        )
        assert approved_res["payment_intent"]["state"] == "CHECKOUT_READY"

        # List payments
        payments_list = client.list_payments()
        assert len(payments_list) >= 2

        # 4. GhostPay: Timelines, Agent Profile & Analysis
        timeline = client.get_replay_timeline(p1_intent["id"])
        assert isinstance(timeline, list)

        profile = client.get_agent_profile(agent["id"])
        assert "agent_id" in profile

        # 5. DisputeOS: Cases, Evidence & Artifacts
        demo_case_detail = client.seed_demo_case()
        case_id = demo_case_detail["case"]["id"]

        disputes = client.list_dispute_cases()
        assert len(disputes) >= 1

        case_obj = client.get_dispute_case(case_id)
        assert case_obj["case"]["id"] == case_id

        client.assign_case(case_id, assigned_to="support-analyst@example.com")
        client.add_case_note(case_id, body="Reviewed invoice and delivery logs.")

        client.attach_evidence(
            case_id,
            source_type="DELIVERY_RECEIPT",
            source_ref="ref://carrier/track/123",
            title="Proof of Delivery",
            content={"status": "DELIVERED", "carrier": "FedEx", "signed_by": "Mittal"},
        )

        artifact_upload = client.upload_evidence_artifact(
            case_id,
            file_content=b"%PDF-1.4 Mock Receipt Document",
            filename="receipt.pdf",
            content_type="application/pdf",
            title="Customer Order PDF",
        )
        assert "artifact_id" in artifact_upload

        downloaded_bytes = client.download_evidence_artifact(case_id, artifact_upload["artifact_id"])
        assert downloaded_bytes == b"%PDF-1.4 Mock Receipt Document"

        analysis = client.run_case_analysis(case_id)
        assert "case" in analysis
        report = client.get_case_report(case_id)
        assert "grounded_summary" in report
        assert "case_id" in report

        # 6. Audit & Admin Logs
        metrics = client.get_overview_metrics()
        assert "budget" in metrics
        audit_events = client.list_audit_events()
        assert "items" in audit_events
        admin_logs = client.list_admin_audit_logs()
        assert "items" in admin_logs

        # 7. System, Settings, Webhooks & Worker DLQ
        sa = client.create_service_account(name="build-pipeline-sa", role="OPERATOR")
        assert sa["name"] == "build-pipeline-sa"
        sas = client.list_service_accounts()
        assert len(sas) >= 1

        key_resp = client.issue_api_key(name="ci-key", service_account_id=sa["id"], role="OPERATOR")
        assert "plaintext_key" in key_resp
        keys_list = client.list_api_keys()
        assert len(keys_list) >= 1

        rotated_key = client.rotate_api_key(key_resp["id"])
        assert "plaintext_key" in rotated_key

        revoked_key = client.revoke_api_key(rotated_key["id"])
        assert revoked_key["status"] == "REVOKED"

        endpoint = client.create_webhook_endpoint(
            url="https://hooks.example.com/aegis",
            description="Prod webhook",
            event_types=["payment.captured"],
        )
        assert endpoint["url"] == "https://hooks.example.com/aegis"
        endpoints = client.list_webhook_endpoints()
        assert len(endpoints) >= 1

        disabled = client.disable_webhook_endpoint(endpoint["id"])
        assert disabled["status"] == "DISABLED"

        deliveries = client.list_webhook_deliveries()
        assert isinstance(deliveries, list)

        outbox_items = client.list_outbox_events()
        assert isinstance(outbox_items, list)


@pytest.mark.asyncio
async def test_async_sdk_full_platform_operations(tmp_path: Path) -> None:
    settings = NexusSettings(
        database_url=f"sqlite:///{tmp_path / 'async.db'}",
        jwt_secret="async-test-jwt-secret-key-32-bytes",
        evidence_storage_dir=str(tmp_path / "ev_async"),
        rate_limit_rpm=5000,
    )
    app = create_app(settings=settings, create_tables=True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as hc:
        async with AsyncAegisClient(client=hc) as async_client:
            # Register & Auth
            reg = await async_client.register(
                email="async-owner@example.com",
                password="AsyncPassword!123",
                full_name="Async Owner",
                organization_name="Async Org",
                organization_slug="async-org",
            )
            async_client.set_token(reg["access_token"])

            me = await async_client.me()
            assert me["email"] == "async-owner@example.com"
            assert len(await async_client.list_orgs()) >= 1

            # Agent & Passport
            agent = await async_client.create_agent(
                name="Async-Bot",
                public_fingerprint="fp-async-001",
            )
            merchant = await async_client.create_merchant(
                name="Async Vendor",
                domain="async-vendor.example.com",
                category="SOFTWARE",
            )
            passport = await async_client.create_passport(
                agent_id=agent["id"],
                total_budget_minor=20000,
                per_tx_limit_minor=8000,
                daily_limit_minor=15000,
                human_approval_threshold_minor=5000,
                allowed_merchant_ids=[merchant["id"]],
                allowed_categories=["SOFTWARE"],
            )

            # AsyncAgentAuthorizationTool
            tool = AsyncAgentAuthorizationTool(
                async_client,
                agent_id=agent["id"],
                passport_id=passport["id"],
            )
            proposal = await tool.request_purchase_authorization(
                merchant_id=merchant["id"],
                merchant_name="Async Vendor",
                merchant_category="SOFTWARE",
                amount_minor=2500,
                item_summary="Async Tool Run",
                rationale="Automated batch jobs",
            )
            intent_id = proposal["payment_intent"]["id"]
            assert proposal["payment_intent"]["state"] == "CHECKOUT_READY"

            # Payment details
            payment = await async_client.get_payment(intent_id)
            assert payment["id"] == intent_id

            # GhostPay replay & simulation
            replay = await async_client.replay_by_payment(intent_id)
            assert replay["integrity_valid"] is True
            sim = await async_client.simulate_by_payment(intent_id, overrides={"per_tx_limit_minor": 1000})
            assert sim["recomputed_outcome"] == "DENY"

            # DisputeOS
            demo_case = await async_client.seed_demo_case()
            case_id = demo_case["case"]["id"]
            cases = await async_client.list_dispute_cases()
            assert len(cases) >= 1
            fetched_case = await async_client.get_dispute_case(case_id)
            assert fetched_case["case"]["id"] == case_id

            # Audit & Service accounts
            metrics = await async_client.get_overview_metrics()
            assert "budget" in metrics
            sa = await async_client.create_service_account(name="async-sa")
            assert sa["name"] == "async-sa"
            sas = await async_client.list_service_accounts()
            assert len(sas) >= 1
