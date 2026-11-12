"""Automated RBAC negative matrix and privilege escalation verification tests.

Validates that for all 6 canonical roles:
- OWNER
- ADMIN
- OPERATOR
- AUDITOR
- AGENT_SERVICE
- VIEWER

Any unauthorized operation is rejected with HTTP 403 Forbidden fail-closed.
Also verifies privilege escalation prevention: an ADMIN cannot escalate
themselves or other users to OWNER, and cannot modify organization configuration
without OWNER credentials.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from aegis_api.app import create_app
from fastapi.testclient import TestClient
from security import NexusSettings, Role, create_access_token


@pytest.fixture()
def platform_rbac_env(tmp_path: Path):
    db_path = tmp_path / "rbac_matrix.db"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="rbac-test-jwt-secret-key-at-least-32b",
        signing_secret="rbac-test-signing-secret",
        evidence_storage_dir=str(tmp_path / "evidence"),
        rate_limit_rpm=10000,
    )
    app = create_app(settings=settings, create_tables=True)
    with TestClient(app) as client:
        # 1. Register organization and OWNER
        reg_resp = client.post(
            "/v1/auth/register",
            json={
                "email": "owner@aegis-matrix.test",
                "password": "StrongPassword!123",
                "full_name": "Org Owner",
                "organization_name": "Matrix Corp",
                "organization_slug": "matrix-corp",
            },
        )
        assert reg_resp.status_code == 201, reg_resp.text
        owner_token = reg_resp.json()["access_token"]
        org_id = UUID(reg_resp.json()["active_tenant_id"])
        owner_id = UUID(reg_resp.json()["user_id"])

        # 2. Register all member roles in the DB
        role_tokens: dict[Role, str] = {Role.OWNER: owner_token}
        role_user_ids: dict[Role, UUID] = {Role.OWNER: owner_id}

        all_member_roles = [Role.ADMIN, Role.OPERATOR, Role.AUDITOR, Role.AGENT_SERVICE, Role.VIEWER]
        for role in all_member_roles:
            email = f"{role.value.lower()}@aegis-matrix.test"
            pwd = "StrongPassword!456"
            add_resp = client.post(
                "/v1/orgs/members",
                headers={"Authorization": f"Bearer {owner_token}"},
                json={
                    "email": email,
                    "password": pwd,
                    "full_name": f"User {role.value}",
                    "role": role.value,
                },
            )
            assert add_resp.status_code == 201, f"Failed adding {role}: {add_resp.text}"
            u_id = UUID(add_resp.json()["user_id"])
            role_user_ids[role] = u_id

            # Login to get valid authenticated session token
            login_resp = client.post(
                "/v1/auth/login",
                json={"email": email, "password": pwd},
            )
            assert login_resp.status_code == 200, f"Login failed for {role}"
            role_tokens[role] = login_resp.json()["access_token"]

        # 3. Create service account and API key for AGENT_SERVICE
        sa_resp = client.post(
            "/v1/orgs/service-accounts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "procurement-worker", "role": Role.AGENT_SERVICE.value},
        )
        assert sa_resp.status_code == 201, sa_resp.text
        sa_id = sa_resp.json()["id"]

        key_resp = client.post(
            "/v1/orgs/api-keys",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "worker-key",
                "service_account_id": sa_id,
                "role": Role.AGENT_SERVICE.value,
            },
        )
        assert key_resp.status_code == 201, key_resp.text
        raw_api_key = key_resp.json()["plaintext_key"]

        yield {
            "client": client,
            "org_id": org_id,
            "owner_token": owner_token,
            "role_tokens": role_tokens,
            "role_user_ids": role_user_ids,
            "raw_api_key": raw_api_key,
            "settings": settings,
        }


def test_rbac_6_roles_negative_matrix(platform_rbac_env):
    """Exhaustive negative test matrix verifying unauthorized actions return 403 Forbidden."""
    client: TestClient = platform_rbac_env["client"]
    role_tokens: dict[Role, str] = platform_rbac_env["role_tokens"]

    # Matrix of operations: (method, path, body, expected_permitted_roles)
    operations: list[dict] = [
        # 1. Organization Management (only OWNER has org:manage)
        {
            "name": "update_org_profile",
            "method": "PATCH",
            "path": "/v1/orgs/current",
            "body": {"name": "Escalated Org Name"},
            "permitted": {Role.OWNER},
        },
        # 2. Member Management (OWNER, ADMIN have members:manage)
        {
            "name": "add_org_member",
            "method": "POST",
            "path": "/v1/orgs/members",
            "body": {
                "email": "intruder@evil.test",
                "password": "Password!999",
                "role": Role.VIEWER.value,
            },
            "permitted": {Role.OWNER, Role.ADMIN},
        },
        # 3. API Key & Credential Management (OWNER, ADMIN have keys:manage)
        {
            "name": "create_api_key",
            "method": "POST",
            "path": "/v1/orgs/api-keys",
            "body": {"name": "unauth-key", "role": Role.AGENT_SERVICE.value},
            "permitted": {Role.OWNER, Role.ADMIN},
        },
        # 4. Agent Registration (OWNER, ADMIN, OPERATOR have agents:write)
        {
            "name": "register_agent",
            "method": "POST",
            "path": "/v1/guardian/agents",
            "body": {
                "name": "rogue-agent",
                "purpose": "Testing RBAC",
                "framework": "langgraph",
                "public_fingerprint": "fp-matrix-01",
            },
            "permitted": {Role.OWNER, Role.ADMIN, Role.OPERATOR},
        },
        # 5. Passport Configuration (OWNER, ADMIN, OPERATOR have passports:write)
        {
            "name": "issue_passport",
            "method": "POST",
            "path": "/v1/guardian/passports",
            "body": {
                "agent_id": str(uuid4()),
                "total_budget_minor": 10000,
                "per_tx_limit_minor": 2000,
                "daily_limit_minor": 5000,
                "human_approval_threshold_minor": 3000,
                "allowed_categories": ["SOFTWARE"],
            },
            "permitted": {Role.OWNER, Role.ADMIN, Role.OPERATOR},
        },
        # 6. Proposal Approval / Human Escalation (OWNER, ADMIN, OPERATOR have approvals:decide)
        {
            "name": "decide_approval",
            "method": "POST",
            "path": f"/v1/guardian/proposals/{uuid4()}/approve",
            "body": {"approver_id": "auditor-attempt", "approved": True},
            "permitted": {Role.OWNER, Role.ADMIN, Role.OPERATOR},
        },
        # 7. Webhook Configuration (OWNER, ADMIN have webhooks:manage)
        {
            "name": "create_webhook_endpoint",
            "method": "POST",
            "path": "/v1/webhooks/endpoints",
            "body": {"url": "https://example.com/webhook", "event_types": ["*"]},
            "permitted": {Role.OWNER, Role.ADMIN},
        },
        # 8. Dispute Approval (OWNER, ADMIN, OPERATOR have disputes:approve)
        {
            "name": "approve_dispute_case",
            "method": "POST",
            "path": f"/v1/disputeos/cases/{uuid4()}/approve",
            "body": {
                "approver_id": "test-approver",
                "draft_response_text": "Dispute response approved",
            },
            "permitted": {Role.OWNER, Role.ADMIN, Role.OPERATOR},
        },
    ]

    all_roles = [Role.OWNER, Role.ADMIN, Role.OPERATOR, Role.AUDITOR, Role.AGENT_SERVICE, Role.VIEWER]
    total_checks = 0
    forbidden_checks = 0

    for op in operations:
        for role in all_roles:
            total_checks += 1
            token = role_tokens[role]
            headers = {"Authorization": f"Bearer {token}"}

            if op["method"] == "POST":
                resp = client.post(op["path"], headers=headers, json=op["body"])
            elif op["method"] == "PATCH":
                resp = client.patch(op["path"], headers=headers, json=op["body"])
            elif op["method"] == "GET":
                resp = client.get(op["path"], headers=headers)
            elif op["method"] == "DELETE":
                resp = client.delete(op["path"], headers=headers)
            else:
                raise ValueError(f"Unsupported method {op['method']}")

            if role in op["permitted"]:
                # If permitted, it should NOT return 403 Forbidden
                assert resp.status_code != 403, (
                    f"Role {role.value} unexpectedly got 403 Forbidden for {op['name']}: {resp.text}"
                )
            else:
                # If NOT permitted, it MUST return 403 Forbidden fail-closed
                assert resp.status_code == 403, (
                    f"RBAC VIOLATION: Role {role.value} was NOT rejected with 403 for {op['name']}! "
                    f"Got HTTP {resp.status_code}: {resp.text}"
                )
                forbidden_checks += 1

    assert forbidden_checks > 0, "No negative tests were executed"
    assert total_checks == len(operations) * len(all_roles)


def test_privilege_escalation_admin_cannot_escalate_to_owner(platform_rbac_env):
    """Verify an ADMIN cannot escalate themselves or others to OWNER without OWNER credentials."""
    client: TestClient = platform_rbac_env["client"]
    admin_token = platform_rbac_env["role_tokens"][Role.ADMIN]
    admin_user_id = platform_rbac_env["role_user_ids"][Role.ADMIN]
    settings: NexusSettings = platform_rbac_env["settings"]
    org_id = platform_rbac_env["org_id"]

    # 1. ADMIN attempts to modify organization profile (requires org:manage) -> 403
    org_edit_attempt = client.patch(
        "/v1/orgs/current",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Hacked Matrix Corp"},
    )
    assert org_edit_attempt.status_code == 403
    assert "PERMISSION_DENIED" in org_edit_attempt.text or "403" in str(org_edit_attempt.status_code)

    # 2. Forged JWT token claiming Role.OWNER for the admin's user ID
    forged_token = create_access_token(
        user_id=admin_user_id,
        tenant_id=org_id,
        role=Role.OWNER,
        secret=settings.jwt_secret,
        email="admin@aegis-matrix.test",
    )
    forged_attempt = client.patch(
        "/v1/orgs/current",
        headers={"Authorization": f"Bearer {forged_token}"},
        json={"name": "Forged Owner Attempt"},
    )
    # Server verifies membership in database and rejects with 403 Forbidden
    assert forged_attempt.status_code == 403

    # 3. Cross-tenant escalation attempt: ADMIN tries to access another org by setting X-Org-Id
    other_org_id = uuid4()
    cross_org_attempt = client.get(
        "/v1/overview/metrics",
        headers={"Authorization": f"Bearer {admin_token}", "X-Org-Id": str(other_org_id)},
    )
    assert cross_org_attempt.status_code == 403


def test_agent_service_key_cannot_approve_spending_or_refund(platform_rbac_env):
    """Verify AGENT_SERVICE credentials cannot approve proposals or dispute refunds."""
    client: TestClient = platform_rbac_env["client"]
    agent_token = platform_rbac_env["role_tokens"][Role.AGENT_SERVICE]
    api_key = platform_rbac_env["raw_api_key"]

    fake_intent_id = uuid4()
    fake_case_id = uuid4()

    # Via Bearer Token
    bearer_approve = client.post(
        f"/v1/guardian/proposals/{fake_intent_id}/approve",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"approver_id": "rogue-agent-service", "approved": True},
    )
    assert bearer_approve.status_code == 403

    bearer_dispute = client.post(
        f"/v1/disputeos/cases/{fake_case_id}/approve",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"decision": "ACCEPT_AND_REFUND", "justification": "Self-refund"},
    )
    assert bearer_dispute.status_code == 403

    # Via X-API-Key header
    key_approve = client.post(
        f"/v1/guardian/proposals/{fake_intent_id}/approve",
        headers={"X-API-Key": api_key},
        json={"approver_id": "rogue-agent-service", "approved": True},
    )
    assert key_approve.status_code == 403

    key_dispute = client.post(
        f"/v1/disputeos/cases/{fake_case_id}/approve",
        headers={"X-API-Key": api_key},
        json={"decision": "ACCEPT_AND_REFUND", "justification": "Self-refund"},
    )
    assert key_dispute.status_code == 403
