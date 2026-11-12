"""Focused tests for RBAC escalation guards, invitations, MFA/OIDC, anti-abuse, overview, billing, and GDPR erasure."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from aegis_api.app import create_app
from aegis_api.routers import billing as billing_router
from aegis_api.routers import erasure as erasure_router
from contracts import (
    DisputeCase,
    DisputeSourceType,
    DisputeStatus,
    FinancialEventType,
)
from database import (
    DisputeCaseRow,
    LedgerRepository,
    PlatformRepository,
    create_session_factory,
)
from fastapi.testclient import TestClient
from security import (
    NexusSettings,
    Role,
    generate_totp_code,
    verify_financial_event_chain,
)


def _mount_new_routers_if_needed(app) -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    if "/v1/billing/plans" not in paths:
        app.include_router(billing_router.router, prefix="/v1")
    if "/v1/privacy/export" not in paths:
        app.include_router(erasure_router.router, prefix="/v1")


@pytest.fixture()
def api_env(tmp_path: Path):
    db_path = tmp_path / "aegis_m1_test.db"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret-for-auth-billing-erasure-32b",
        signing_secret="test-signing-secret-for-auth-billing-erasure",
        evidence_storage_dir=str(tmp_path / "evidence"),
        rate_limit_rpm=5000,
        stripe_api_key="sk_test_mock_12345",
        stripe_webhook_secret="whsec_test_secret_12345",
    )
    app = create_app(settings=settings, create_tables=True)
    _mount_new_routers_if_needed(app)
    with TestClient(app) as client:
        yield client, app, settings


def _register_org(
    client: TestClient,
    *,
    email: str,
    slug: str,
    name: str = "Test Org",
    full_name: str = "Org Owner",
    password: str = "StrongPassword!123",
) -> dict:
    resp = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": full_name,
            "organization_name": name,
            "organization_slug": slug,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_hs256_jwt(claims: dict, secret: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def _sign_stripe_payload(payload_bytes: bytes, secret: str, *, ts: int | None = None) -> str:
    timestamp = int(time.time()) if ts is None else ts
    signed = f"{timestamp}.".encode() + payload_bytes
    sig = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def test_admin_cannot_assign_owner_on_any_role_granting_path(api_env) -> None:
    client, _, _ = api_env
    owner = _register_org(client, email="owner1@example.com", slug="rbac-org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}

    # Owner creates an ADMIN member
    add_admin = client.post(
        "/v1/orgs/members",
        headers=owner_headers,
        json={
            "email": "admin1@example.com",
            "full_name": "Org Admin",
            "password": "AdminPassword!123",
            "role": Role.ADMIN.value,
        },
    )
    assert add_admin.status_code == 201
    admin_login = client.post(
        "/v1/auth/login",
        json={"email": "admin1@example.com", "password": "AdminPassword!123"},
    )
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # Owner creates a regular operator target user
    add_op = client.post(
        "/v1/orgs/members",
        headers=owner_headers,
        json={
            "email": "op1@example.com",
            "full_name": "Org Operator",
            "password": "OpPassword!123",
            "role": Role.OPERATOR.value,
        },
    )
    assert add_op.status_code == 201
    op_user_id = add_op.json()["user_id"]

    # 1. add_org_member -> 403 PERMISSION_DENIED
    r1 = client.post(
        "/v1/orgs/members",
        headers=admin_headers,
        json={
            "email": "new-owner@example.com",
            "full_name": "Sneaky Owner",
            "password": "Password!123",
            "role": Role.OWNER.value,
        },
    )
    assert r1.status_code == 403
    assert r1.json()["error_code"] == "PERMISSION_DENIED"

    # 2. invite_org_member -> 403 PERMISSION_DENIED
    r2 = client.post(
        "/v1/orgs/invitations",
        headers=admin_headers,
        json={"email": "invitee@example.com", "role": Role.OWNER.value},
    )
    assert r2.status_code == 403
    assert r2.json()["error_code"] == "PERMISSION_DENIED"

    # 3. update_member_role -> 403 PERMISSION_DENIED
    r3 = client.patch(
        f"/v1/orgs/members/{op_user_id}/role",
        headers=admin_headers,
        json={"role": Role.OWNER.value},
    )
    assert r3.status_code == 403
    assert r3.json()["error_code"] == "PERMISSION_DENIED"

    # 4. create_service_account -> 403 PERMISSION_DENIED
    r4 = client.post(
        "/v1/orgs/service-accounts",
        headers=admin_headers,
        json={"name": "escalated-sa", "role": Role.OWNER.value},
    )
    assert r4.status_code == 403
    assert r4.json()["error_code"] == "PERMISSION_DENIED"

    # 5. issue_api_key -> 403 PERMISSION_DENIED
    r5 = client.post(
        "/v1/orgs/api-keys",
        headers=admin_headers,
        json={"name": "escalated-key", "role": Role.OWNER.value},
    )
    assert r5.status_code == 403
    assert r5.json()["error_code"] == "PERMISSION_DENIED"

    # ADMIN CAN assign ADMIN or lower roles
    ok_invite = client.post(
        "/v1/orgs/invitations",
        headers=admin_headers,
        json={"email": "operator-invite@example.com", "role": Role.OPERATOR.value},
    )
    assert ok_invite.status_code == 201


def test_cross_org_member_attachment_blocked_and_invitation_consent_flow(api_env) -> None:
    client, _, _ = api_env
    org_a = _register_org(client, email="alice@example.com", slug="org-a-inv")
    org_b = _register_org(client, email="bob@example.com", slug="org-b-inv")
    other = _register_org(client, email="carol@example.com", slug="org-c-inv")

    headers_a = {"Authorization": f"Bearer {org_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {org_b['access_token']}"}
    headers_c = {"Authorization": f"Bearer {other['access_token']}"}

    # Org A tries to silently attach Bob (who exists in Org B) via POST /orgs/members -> 409 INVITATION_REQUIRED
    silent_attach = client.post(
        "/v1/orgs/members",
        headers=headers_a,
        json={"email": "bob@example.com", "role": Role.OPERATOR.value},
    )
    assert silent_attach.status_code == 409
    assert silent_attach.json()["detail"]["error_code"] == "INVITATION_REQUIRED"

    # Org A sends invitation to Bob
    inv_resp = client.post(
        "/v1/orgs/invitations",
        headers=headers_a,
        json={"email": "bob@example.com", "role": Role.AUDITOR.value},
    )
    assert inv_resp.status_code == 201
    inv_data = inv_resp.json()
    inv_token = inv_data["token"]
    assert inv_token

    # Carol cannot accept Bob's invitation -> 403 INVITATION_EMAIL_MISMATCH
    wrong_accept = client.post(f"/v1/orgs/invitations/{inv_token}/accept", headers=headers_c)
    assert wrong_accept.status_code == 403
    assert wrong_accept.json()["detail"]["error_code"] == "INVITATION_EMAIL_MISMATCH"

    # Bob accepts consent -> becomes AUDITOR in Org A
    accept_resp = client.post(f"/v1/orgs/invitations/{inv_token}/accept", headers=headers_b)
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "ACCEPTED"
    assert accept_resp.json()["role"] == Role.AUDITOR.value

    # Bob can now access Org A via X-Org-Id
    me_a = client.get(
        "/v1/auth/me",
        headers={**headers_b, "X-Org-Id": org_a["active_tenant_id"]},
    )
    assert me_a.status_code == 200
    assert me_a.json()["role"] == Role.AUDITOR.value

    # Create another invite and revoke it
    inv2 = client.post(
        "/v1/orgs/invitations",
        headers=headers_a,
        json={"email": "revoke-me@example.com", "role": Role.VIEWER.value},
    ).json()
    del_resp = client.delete(f"/v1/orgs/invitations/{inv2['id']}", headers=headers_a)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "REVOKED"


def test_totp_mfa_enroll_verify_and_login_enforcement(api_env) -> None:
    client, _, _ = api_env
    reg = _register_org(client, email="mfa-user@example.com", slug="mfa-org")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    # Enroll TOTP MFA
    enroll = client.post("/v1/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    assert enroll.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert enroll.json()["mfa_enabled"] is False

    # Invalid code fails
    bad_verify = client.post("/v1/auth/mfa/verify", headers=headers, json={"code": "000000"})
    assert bad_verify.status_code == 401

    # Valid code enables MFA
    code = generate_totp_code(secret)
    ok_verify = client.post("/v1/auth/mfa/verify", headers=headers, json={"code": code})
    assert ok_verify.status_code == 200
    assert ok_verify.json()["mfa_enabled"] is True

    # Login without mfa_code fails 401 MFA_REQUIRED
    login_no_mfa = client.post(
        "/v1/auth/login",
        json={"email": "mfa-user@example.com", "password": "StrongPassword!123"},
    )
    assert login_no_mfa.status_code == 401
    assert login_no_mfa.json()["detail"]["error_code"] == "MFA_REQUIRED"

    # Login with valid mfa_code succeeds
    login_with_mfa = client.post(
        "/v1/auth/login",
        json={
            "email": "mfa-user@example.com",
            "password": "StrongPassword!123",
            "mfa_code": generate_totp_code(secret),
        },
    )
    assert login_with_mfa.status_code == 200
    assert login_with_mfa.json()["mfa_enabled"] is True


def test_email_verification_and_registration_anti_abuse(tmp_path: Path) -> None:
    db_path = tmp_path / "verify_email.db"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret-email-verify-32b",
        signing_secret="test-signing-secret-email-verify",
        rate_limit_rpm=5000,
        email_verification_required=True,
    )
    app = create_app(settings=settings, create_tables=True)
    app.state.registration_email_limit = 2
    app.state.registration_ip_limit = 5
    with TestClient(app) as client:
        # Disposable email domain rejected
        disposable = client.post(
            "/v1/auth/register",
            json={
                "email": "attacker@mailinator.com",
                "password": "StrongPassword!123",
                "full_name": "Throw Away",
                "organization_name": "Spam Org",
                "organization_slug": "spam-org",
            },
        )
        assert disposable.status_code == 400
        assert disposable.json()["detail"]["error_code"] == "DISPOSABLE_EMAIL_REJECTED"

        # Register legitimate user
        reg = _register_org(client, email="verify-me@example.com", slug="verify-org")
        assert reg["email_verified"] is False
        assert reg["verification_token"]

        # Unverified login blocked when email_verification_required=True
        blocked_login = client.post(
            "/v1/auth/login",
            json={"email": "verify-me@example.com", "password": "StrongPassword!123"},
        )
        assert blocked_login.status_code == 403
        assert blocked_login.json()["detail"]["error_code"] == "EMAIL_NOT_VERIFIED"

        # Resend verification issues a fresh token
        resend = client.post("/v1/auth/resend-verification", json={"email": "verify-me@example.com"})
        assert resend.status_code == 200
        fresh_token = resend.json()["verification_token"]
        assert fresh_token

        # Verify email with token
        ver = client.post("/v1/auth/verify-email", json={"token": fresh_token})
        assert ver.status_code == 200
        assert ver.json()["email_verified"] is True

        # Now login succeeds and /auth/me reflects email_verified=True
        ok_login = client.post(
            "/v1/auth/login",
            json={"email": "verify-me@example.com", "password": "StrongPassword!123"},
        )
        assert ok_login.status_code == 200
        assert ok_login.json()["email_verified"] is True

        # Per-email registration rate throttling (limit=2)
        for idx in range(2):
            client.post(
                "/v1/auth/register",
                json={
                    "email": "throttle@example.com",
                    "password": "StrongPassword!123",
                    "full_name": "Throttle Test",
                    "organization_name": f"Throttle Org {idx}",
                    "organization_slug": f"throttle-org-{idx}",
                },
            )
        throttled = client.post(
            "/v1/auth/register",
            json={
                "email": "throttle@example.com",
                "password": "StrongPassword!123",
                "full_name": "Throttle Test",
                "organization_name": "Throttle Org 3",
                "organization_slug": "throttle-org-3",
            },
        )
        assert throttled.status_code == 429
        assert throttled.json()["detail"]["error_code"] == "REGISTRATION_RATE_LIMITED"


def test_oidc_sso_exchange(api_env) -> None:
    client, app, _ = api_env
    reg = _register_org(client, email="sso-user@example.com", slug="sso-org")

    # Fails closed 503 when OIDC is not configured
    unconf = client.post("/v1/auth/sso/oidc/exchange", json={"id_token": "header.payload.signature"})
    assert unconf.status_code == 503

    oidc_secret = "oidc-shared-hs256-test-secret"
    app.state.oidc_issuer = "https://idp.example.com"
    app.state.oidc_audience = "aegis-web"
    app.state.oidc_hs256_secret = oidc_secret

    now_ts = int(time.time())
    valid_claims = {
        "iss": "https://idp.example.com",
        "aud": "aegis-web",
        "sub": "oidc-sub-123",
        "email": "sso-user@example.com",
        "email_verified": True,
        "nonce": "nonce-xyz",
        "iat": now_ts,
        "exp": now_ts + 300,
    }
    bad_sig_token = _sign_hs256_jwt(valid_claims, "wrong-secret")
    assert client.post("/v1/auth/sso/oidc/exchange", json={"id_token": bad_sig_token}).status_code == 401

    wrong_nonce_token = _sign_hs256_jwt(valid_claims, oidc_secret)
    assert (
        client.post(
            "/v1/auth/sso/oidc/exchange",
            json={"id_token": wrong_nonce_token, "nonce": "different-nonce"},
        ).status_code
        == 401
    )

    ok_resp = client.post(
        "/v1/auth/sso/oidc/exchange",
        json={"id_token": wrong_nonce_token, "nonce": "nonce-xyz"},
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["active_tenant_id"] == reg["active_tenant_id"]
    assert ok_resp.json()["access_token"]


def test_pagination_headers_and_overview_audit_export(api_env) -> None:
    client, _, _settings = api_env
    reg = _register_org(client, email="pag-owner@example.com", slug="pag-org")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    tenant_id = UUID(reg["active_tenant_id"])

    # Create 3 members total (1 owner + 2 added), 3 service accounts, 3 API keys, 3 invitations
    for idx in range(2):
        assert (
            client.post(
                "/v1/orgs/members",
                headers=headers,
                json={
                    "email": f"member{idx}@example.com",
                    "full_name": f"Member {idx}",
                    "password": "StrongPassword!123",
                    "role": Role.VIEWER.value,
                },
            ).status_code
            == 201
        )
    for idx in range(3):
        assert (
            client.post(
                "/v1/orgs/service-accounts",
                headers=headers,
                json={"name": f"sa-{idx}", "role": Role.AGENT_SERVICE.value},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/v1/orgs/api-keys",
                headers=headers,
                json={"name": f"key-{idx}", "role": Role.AGENT_SERVICE.value},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/v1/orgs/invitations",
                headers=headers,
                json={"email": f"invite{idx}@example.com", "role": Role.OPERATOR.value},
            ).status_code
            == 201
        )

    m_resp = client.get("/v1/orgs/members?limit=2&offset=1", headers=headers)
    assert m_resp.status_code == 200
    assert m_resp.headers["X-Total-Count"] == "3"
    assert len(m_resp.json()) == 2

    sa_resp = client.get("/v1/orgs/service-accounts?limit=2&offset=0", headers=headers)
    assert sa_resp.status_code == 200
    assert sa_resp.headers["X-Total-Count"] == "3"
    assert len(sa_resp.json()) == 2

    k_resp = client.get("/v1/orgs/api-keys?limit=1&offset=2", headers=headers)
    assert k_resp.status_code == 200
    assert k_resp.headers["X-Total-Count"] == "3"
    assert len(k_resp.json()) == 1

    inv_resp = client.get("/v1/orgs/invitations?limit=2&offset=1", headers=headers)
    assert inv_resp.status_code == 200
    assert inv_resp.headers["X-Total-Count"] == "3"
    assert len(inv_resp.json()) == 2

    # Seed an LLM invocation, an urgent dispute deadline, and financial events
    agent_id = client.post(
        "/v1/guardian/agents",
        headers=headers,
        json={"name": "TestBot", "public_fingerprint": "fp-test-ov-1"},
    ).json()["id"]
    merchant_id = client.post(
        "/v1/guardian/merchants",
        headers=headers,
        json={"name": "Acme SaaS", "domain": "acme.example.com", "category": "SOFTWARE", "is_allowlisted": True},
    ).json()["id"]
    passport_id = client.post(
        "/v1/guardian/passports",
        headers=headers,
        json={
            "agent_id": agent_id,
            "total_budget_minor": 10000,
            "per_tx_limit_minor": 5000,
            "daily_limit_minor": 8000,
            "human_approval_threshold_minor": 3000,
            "allowed_merchant_ids": [merchant_id],
            "allowed_categories": ["SOFTWARE"],
        },
    ).json()["id"]
    prop = client.post(
        "/v1/guardian/proposals",
        headers=headers,
        json={
            "agent_id": agent_id,
            "passport_id": passport_id,
            "merchant_id": merchant_id,
            "merchant_name": "Acme SaaS",
            "merchant_category": "SOFTWARE",
            "amount_minor": 1500,
            "currency": "USD",
            "item_summary": "Monthly license",
            "rationale": "needle-in-payload",
            "idempotency_key": "idemp-ov-1",
        },
    ).json()
    intent_id = UUID(prop["payment_intent"]["id"])
    corr_id = UUID(prop["payment_intent"]["correlation_id"])

    session_factory = create_session_factory(client.app.state.engine)
    with session_factory() as session:
        platform = PlatformRepository(session)
        ledger = LedgerRepository(session)
        platform.log_llm_invocation(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            module="disputeos",
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=120,
            completion_tokens=45,
            estimated_cost_usd_micros=350,
        )
        saved_case = ledger.save_dispute_case(
            DisputeCase(
                tenant_id=tenant_id,
                correlation_id=corr_id,
                payment_intent_id=intent_id,
                source_type=DisputeSourceType.SYNTHETIC_DEMO,
                is_synthetic=True,
                reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                buyer_claim="Not received",
                amount_minor=1500,
                currency="USD",
                status=DisputeStatus.OPEN,
            )
        )
        case_row = session.get(DisputeCaseRow, saved_case.id)
        assert case_row is not None
        case_row.response_due_by = datetime.now(UTC) + timedelta(hours=12)
        ledger.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            payment_intent_id=intent_id,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="AGENT",
            actor_id="agent-search-target",
            payload={"note": "needle-in-payload"},
        )
        session.commit()

    ov = client.get("/v1/overview/metrics", headers=headers).json()
    assert len(ov["dispute_deadlines"]) == 1
    assert ov["llm_usage"]["invocation_count"] == 1
    assert ov["llm_usage"]["total_tokens"] == 165
    assert ov["llm_usage"]["estimated_cost_usd_micros"] == 350

    audit_q = client.get("/v1/audit-events?q=needle-in-payload", headers=headers)
    assert audit_q.status_code == 200
    assert int(audit_q.headers["X-Total-Count"]) >= 1
    assert audit_q.json()["count"] >= 1

    csv_export = client.get("/v1/audit-events/export?format=csv", headers=headers)
    assert csv_export.status_code == 200
    assert "text/csv" in csv_export.headers["content-type"]
    assert "PROPOSAL_CREATED" in csv_export.text


def test_stripe_billing_checkout_portal_webhooks_and_quota(api_env) -> None:
    client, app, settings = api_env
    owner = _register_org(client, email="bill-owner@example.com", slug="bill-org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    tenant_id = UUID(owner["active_tenant_id"])

    plans = client.get("/v1/billing/plans")
    assert plans.status_code == 200
    plan_map = {p["id"]: p for p in plans.json()["plans"]}
    assert plan_map["FREE"]["monthly_tx_quota"] == 1000
    assert plan_map["PRO"]["monthly_tx_quota"] == 50000
    assert plan_map["ENTERPRISE"]["unlimited"] is True

    sub_default = client.get("/v1/billing/subscription", headers=headers).json()
    assert sub_default["plan"] == "FREE"
    assert sub_default["monthly_tx_quota"] == 1000

    # Mock Stripe HTTP transport
    def stripe_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/checkout/sessions":
            return httpx.Response(200, json={"id": "cs_test_123", "url": "https://checkout.stripe.com/pay/cs_test_123"})
        if request.url.path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"id": "bps_test_123", "url": "https://billing.stripe.com/session/bps_test_123"})
        return httpx.Response(404, json={})

    app.state.stripe_http_client = httpx.AsyncClient(
        base_url="https://api.stripe.com",
        transport=httpx.MockTransport(stripe_handler),
    )

    checkout = client.post(
        "/v1/billing/checkout",
        headers=headers,
        json={
            "plan": "PRO",
            "success_url": "https://app.example.com/billing?ok=1",
            "cancel_url": "https://app.example.com/billing?cancel=1",
        },
    )
    assert checkout.status_code == 200
    assert checkout.json()["session_id"] == "cs_test_123"

    # Portal fails 400 before customer ID exists
    no_cust_portal = client.post(
        "/v1/billing/portal",
        headers=headers,
        json={"return_url": "https://app.example.com/billing"},
    )
    assert no_cust_portal.status_code == 400

    # Bad Stripe webhook signature rejected 401
    wh_payload = json.dumps({
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_test_123",
                "subscription": "sub_test_123",
                "client_reference_id": str(tenant_id),
                "metadata": {"tenant_id": str(tenant_id), "plan": "PRO"},
            }
        },
    }).encode("utf-8")

    bad_wh = client.post(
        "/v1/billing/webhooks/stripe",
        content=wh_payload,
        headers={"Stripe-Signature": "t=12345,v1=deadbeef", "Content-Type": "application/json"},
    )
    assert bad_wh.status_code == 401

    good_sig = _sign_stripe_payload(wh_payload, settings.stripe_webhook_secret)
    good_wh = client.post(
        "/v1/billing/webhooks/stripe",
        content=wh_payload,
        headers={"Stripe-Signature": good_sig, "Content-Type": "application/json"},
    )
    assert good_wh.status_code == 200
    assert good_wh.json()["plan"] == "PRO"
    assert good_wh.json()["status"] == "ACTIVE"

    # Now portal works
    portal = client.post(
        "/v1/billing/portal",
        headers=headers,
        json={"return_url": "https://app.example.com/billing"},
    )
    assert portal.status_code == 200
    assert "billing.stripe.com" in portal.json()["portal_url"]

    # Quota enforcement helper check
    session_factory = create_session_factory(app.state.engine)
    with session_factory() as session:
        platform = PlatformRepository(session)
        ym = datetime.now(UTC).strftime("%Y-%m")
        platform.increment_usage_meter(tenant_id=tenant_id, period_ym=ym, metric="transactions", amount=50000)
        session.commit()

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            billing_router.enforce_monthly_tx_quota(platform, tenant_id)
        assert exc_info.value.status_code == 429

        # Past due returns 402
        platform.upsert_billing_subscription(
            tenant_id=tenant_id,
            plan="PRO",
            status="PAST_DUE",
            monthly_tx_quota=50000,
        )
        session.commit()
        with pytest.raises(HTTPException) as past_due_exc:
            billing_router.enforce_monthly_tx_quota(platform, tenant_id)
        assert past_due_exc.value.status_code == 402


def test_gdpr_export_and_erasure_preserves_financial_ledger(api_env) -> None:
    client, app, _settings = api_env
    owner = _register_org(client, email="priv-owner@example.com", slug="privacy-org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    tenant_id = UUID(owner["active_tenant_id"])

    # Add a subject user and issue them an API key + pending invitation
    member = client.post(
        "/v1/orgs/members",
        headers=owner_headers,
        json={
            "email": "subject-user@example.com",
            "full_name": "Jane Subject",
            "password": "SubjectPassword!123",
            "role": Role.OPERATOR.value,
        },
    ).json()
    subject_id = UUID(member["user_id"])

    subject_login = client.post(
        "/v1/auth/login",
        json={"email": "subject-user@example.com", "password": "SubjectPassword!123"},
    ).json()
    subject_headers = {"Authorization": f"Bearer {subject_login['access_token']}"}

    # Self-export works for authenticated user
    self_export = client.get("/v1/privacy/export", headers=subject_headers)
    assert self_export.status_code == 200
    assert self_export.json()["user"]["email"] == "subject-user@example.com"
    assert self_export.json()["erasure_status"] == "ACTIVE"

    # Append a hash-chained financial event tied to the subject user before erasure
    session_factory = create_session_factory(app.state.engine)
    corr_id = uuid4()
    with session_factory() as session:
        ledger = LedgerRepository(session)
        ledger.append_financial_event(
            tenant_id=tenant_id,
            correlation_id=corr_id,
            payment_intent_id=None,
            event_type=FinancialEventType.PROPOSAL_CREATED,
            actor_type="USER",
            actor_id=str(subject_id),
            payload={"amount_minor": 2500},
        )
        session.commit()

    # Execute GDPR erasure as owner
    erase_resp = client.post(
        "/v1/privacy/erasure-requests",
        headers=owner_headers,
        json={"user_id": str(subject_id), "reason": "USER_RIGHT_TO_ERASURE"},
    )
    assert erase_resp.status_code == 201
    erase_data = erase_resp.json()
    assert erase_data["status"] == "COMPLETED"
    assert erase_data["details"]["ledger_preserved"] is True
    assert "crypto_shred_marker" in erase_data["details"]

    # Subject can no longer log in and export shows pseudonymized email + ERASED status
    assert (
        client.post(
            "/v1/auth/login",
            json={"email": "subject-user@example.com", "password": "SubjectPassword!123"},
        ).status_code
        == 401
    )

    admin_export = client.get(f"/v1/privacy/export?user_id={subject_id}", headers=owner_headers)
    assert admin_export.status_code == 200
    assert admin_export.json()["erasure_status"] == "ERASED"
    assert admin_export.json()["user"]["email"].startswith("erased-")
    assert admin_export.json()["user"]["full_name"] == "ERASED_USER"

    # Erasure requests list supports pagination + X-Total-Count
    er_list = client.get("/v1/privacy/erasure-requests?limit=10&offset=0", headers=owner_headers)
    assert er_list.status_code == 200
    assert er_list.headers["X-Total-Count"] == "1"
    assert len(er_list.json()) == 1

    # Financial ledger hash chain remains completely intact!
    with session_factory() as session:
        events = LedgerRepository(session).list_events(tenant_id, correlation_id=corr_id)
        assert len(events) == 1
        valid, errors = verify_financial_event_chain(events)
        assert valid is True
        assert errors == []
