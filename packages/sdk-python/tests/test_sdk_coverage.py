"""Targeted tests to ensure comprehensive >=85% branch and statement SDK coverage."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from aegis_api.app import create_app
from aegis_sdk import AegisAPIError, AegisClient, AsyncAegisClient
from fastapi.testclient import TestClient
from security import NexusSettings


def test_client_not_found_lookups_and_error_handling() -> None:
    client = AegisClient(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))))
    with pytest.raises(AegisAPIError) as exc_info:
        client.get_agent(uuid4())
    assert exc_info.value.status_code == 404

    with pytest.raises(AegisAPIError) as exc_info:
        client.get_merchant(uuid4())
    assert exc_info.value.status_code == 404

    with pytest.raises(AegisAPIError) as exc_info:
        client.get_passport(uuid4())
    assert exc_info.value.status_code == 404

    with pytest.raises(AegisAPIError) as exc_info:
        client.get_approval(uuid4())
    assert exc_info.value.status_code == 404
    client.close()


@pytest.mark.asyncio
async def test_async_client_not_found_lookups() -> None:
    client = AsyncAegisClient(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))))
    with pytest.raises(AegisAPIError) as exc_info:
        await client.get_agent(uuid4())
    assert exc_info.value.status_code == 404

    with pytest.raises(AegisAPIError) as exc_info:
        await client.get_merchant(uuid4())
    assert exc_info.value.status_code == 404

    with pytest.raises(AegisAPIError) as exc_info:
        await client.get_passport(uuid4())
    assert exc_info.value.status_code == 404

    with pytest.raises(AegisAPIError) as exc_info:
        await client.get_approval(uuid4())
    assert exc_info.value.status_code == 404
    await client.close()


def test_sync_sdk_additional_coverage(tmp_path: Path) -> None:
    settings = NexusSettings(
        database_url=f"sqlite:///{tmp_path / 'extra.db'}",
        jwt_secret="extra-test-jwt-secret-key-32-bytes",
        evidence_storage_dir=str(tmp_path / "ev_extra"),
        rate_limit_rpm=5000,
    )
    app = create_app(settings=settings, create_tables=True)

    with TestClient(app) as tc:
        client = AegisClient(client=tc)
        reg = client.register(
            email="extra-admin@example.com",
            password="AdminPassword!123",
            full_name="Extra Admin",
            organization_name="Extra Org",
            organization_slug="extra-org",
        )
        client.set_token(reg["access_token"])
        org_id = reg["active_tenant_id"]

        # Test login with explicit organization_id
        login_res = client.login(email="extra-admin@example.com", password="AdminPassword!123", organization_id=org_id)
        assert "access_token" in login_res

        # Test switch_org
        switched = client.switch_org(org_id)
        assert switched["active_tenant_id"] == org_id

        # Agents & passports revoke
        ag = client.create_agent(name="ToRevoke", public_fingerprint="fp-to-revoke")
        rev_ag = client.revoke_agent(ag["id"])
        assert rev_ag["status"] == "REVOKED"

        m = client.create_merchant(name="MToRevoke", domain="m-rev.com")
        rev_passp = client.create_passport(
            agent_id=ag["id"],
            total_budget_minor=1000,
            per_tx_limit_minor=500,
            daily_limit_minor=1000,
            allowed_merchant_ids=[m["id"]],
        )
        with pytest.raises(AegisAPIError) as exc_rev:
            client.submit_purchase_proposal(
                agent_id=ag["id"],
                passport_id=rev_passp["id"],
                merchant_id=m["id"],
                merchant_name="MToRevoke",
                amount_minor=500,
                item_summary="Revoked agent test",
                rationale="Should fail closed",
            )
        assert exc_rev.value.status_code == 403

        ag_active = client.create_agent(name="ActiveForDispute", public_fingerprint="fp-active-disp")
        passp = client.create_passport(
            agent_id=ag_active["id"],
            total_budget_minor=1000,
            per_tx_limit_minor=500,
            daily_limit_minor=1000,
            allowed_merchant_ids=[m["id"]],
        )
        # Submit proposal to generate valid payment intent for dispute
        prop = client.submit_purchase_proposal(
            agent_id=ag_active["id"],
            passport_id=passp["id"],
            merchant_id=m["id"],
            merchant_name="MToRevoke",
            amount_minor=500,
            item_summary="Revoke test",
            rationale="Test",
        )
        intent_id = prop["payment_intent"]["id"]

        rev_p = client.revoke_passport(passp["id"])
        assert rev_p["status"] == "REVOKED"

        # Create dispute case manually
        created_case = client.create_dispute_case(
            payment_intent_id=intent_id,
            reason="ITEM_NOT_RECEIVED",
            buyer_claim="Never arrived",
            amount_minor=500,
            source_type="SYNTHETIC_DEMO",
            is_synthetic=True,
        )
        assert created_case["reason"] == "ITEM_NOT_RECEIVED"


@pytest.mark.asyncio
async def test_async_sdk_comprehensive_operations(tmp_path: Path) -> None:
    settings = NexusSettings(
        database_url=f"sqlite:///{tmp_path / 'async_full.db'}",
        jwt_secret="async-full-test-jwt-secret-key-32-bytes",
        evidence_storage_dir=str(tmp_path / "ev_async_full"),
        rate_limit_rpm=5000,
    )
    app = create_app(settings=settings, create_tables=True)
    transport = httpx.ASGITransport(app=app)

    async with (
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as hc,
        AsyncAegisClient(client=hc) as client,
    ):
            reg = await client.register(
                email="async-full@example.com",
                password="Password!12345",
                full_name="Async Full",
                organization_name="Async Full Org",
                organization_slug="async-full-org",
            )
            client.set_token(reg["access_token"])
            org_id = reg["active_tenant_id"]

            # Login with org
            log_res = await client.login(email="async-full@example.com", password="Password!12345", organization_id=org_id)
            assert "access_token" in log_res
            await client.switch_org(org_id)

            # Org & member ops
            await client.update_current_org(name="Renamed Org")
            await client.create_org(name="Sub Org 2", slug="sub-org-2")
            member = await client.invite_member(
                email="async-member@example.com",
                full_name="Async Member",
                password="Password!12345",
            )
            await client.list_members()
            await client.update_member_role(member["user_id"], role="AUDITOR")

            # Agent & Merchant ops
            agent = await client.create_agent(name="Async-Bot-2", public_fingerprint="fp-async-002")
            await client.list_agents()
            await client.get_agent(agent["id"])
            await client.suspend_agent(agent["id"])
            await client.activate_agent(agent["id"])
            await client.revoke_agent(agent["id"])

            agent_active = await client.create_agent(name="Async-Active", public_fingerprint="fp-async-003")
            merchant = await client.create_merchant(name="Async Vendor 2", domain="vendor2.com")
            await client.list_merchants()
            await client.get_merchant(merchant["id"])
            await client.toggle_merchant_allowlist(merchant["id"], is_allowlisted=False)
            await client.toggle_merchant_allowlist(merchant["id"], is_allowlisted=True)

            passport = await client.create_passport(
                agent_id=agent_active["id"],
                total_budget_minor=30000,
                per_tx_limit_minor=10000,
                daily_limit_minor=20000,
                human_approval_threshold_minor=4000,
                allowed_merchant_ids=[merchant["id"]],
            )
            await client.list_passports()
            await client.get_passport(passport["id"])
            await client.update_passport_policy(passport["id"], human_approval_threshold_minor=5000)

            # Proposals & Approvals
            prop = await client.submit_purchase_proposal(
                agent_id=agent_active["id"],
                passport_id=passport["id"],
                merchant_id=merchant["id"],
                merchant_name="Async Vendor 2",
                amount_minor=7000,
                item_summary="Large Instance",
                rationale="Cluster workloads",
            )
            intent_id = prop["payment_intent"]["id"]
            approvals = await client.list_approvals()
            assert len(approvals) >= 1
            await client.get_approval(approvals[0]["id"])
            approved = await client.approve_proposal(
                intent_id,
                approver_id="async-full@example.com",
                comment="Async approved",
                approved=True,
            )
            assert approved["payment_intent"]["state"] == "CHECKOUT_READY"

            await client.get_payment_detail(intent_id)
            await client.list_payments()

            # GhostPay
            await client.get_replay_timeline(intent_id)
            invs = await client.list_investigations()
            assert "items" in invs
            await client.get_agent_profile(agent_active["id"])

            # DisputeOS
            demo = await client.seed_demo_case()
            case_id = demo["case"]["id"]
            await client.assign_case(case_id, assigned_to="operator@example.com")
            await client.add_case_note(case_id, body="Note text")
            await client.attach_evidence(
                case_id,
                source_type="DELIVERY_RECEIPT",
                source_ref="ref://del/1",
                title="Delivery confirmation",
                content={"total": 100},
            )
            art = await client.upload_evidence_artifact(
                case_id,
                file_content=b"test data",
                filename="test.txt",
                content_type="text/plain",
            )
            downloaded = await client.download_evidence_artifact(case_id, art["artifact_id"])
            assert downloaded == b"test data"
            await client.run_case_analysis(case_id)
            await client.get_case_report(case_id)
            await client.approve_case(case_id, approver_id="async-full@example.com", draft_response_text="Accepted")

            # Audit, Keys, Webhooks
            await client.list_audit_events()
            await client.verify_chain(uuid4())
            await client.list_admin_audit_logs()

            sa = await client.create_service_account(name="async-pipeline-sa")
            key = await client.issue_api_key(name="async-key", service_account_id=sa["id"])
            await client.list_api_keys()
            rotated = await client.rotate_api_key(key["id"])
            await client.revoke_api_key(rotated["id"])

            ep = await client.create_webhook_endpoint(url="https://async.example.com/hook")
            await client.list_webhook_endpoints()
            await client.disable_webhook_endpoint(ep["id"])
            await client.list_webhook_deliveries()
            await client.list_outbox_events()
