"""Hardening & gap-closure tests for AgentPay Guardian and guardian_db router."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from aegis_api.app import create_app
from contracts import (
    ApprovalStatus,
    EvidenceSourceType,
    FinancialEventType,
    Merchant,
    PassportStatus,
    PaymentAttempt,
    PaymentIntent,
    PaymentState,
    PurchaseProposal,
    QuoteSnapshot,
    compute_quote_hash,
)
from contracts.fixtures import (
    AGENT_PROCUREMENT_ID,
    MERCHANT_SANDBOX_CLOUD_ID,
    MERCHANT_UNKNOWN_ID,
    PASSPORT_DEFAULT_ID,
    TENANT_ALPHA_ID,
    build_base_entities,
)
from database import LedgerRepository
from fastapi import FastAPI
from fastapi.testclient import TestClient
from paypal import (
    PayPalAPIError,
    PayPalCaptureResult,
    PayPalOrderCreationResult,
    PayPalSandboxClient,
    PayPalTimeoutError,
)
from security import NexusSettings, get_settings

from guardian.api.router import create_guardian_router
from guardian.domain.exceptions import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    DuplicateIntentError,
    InvalidStateTransitionError,
    PolicyDeniedError,
)
from guardian.domain.service import GuardianService
from tests.conftest import InMemoryLedgerRepository, MockPayPalClient, run_sync


class ExtendedInMemoryRepo(InMemoryLedgerRepository):
    """Test repo adding attempt-listing, agent-status, and intent pagination helpers."""

    def __init__(self) -> None:
        super().__init__()
        base = build_base_entities()
        self.upsert_tenant(base["tenant"])
        self.create_agent(base["agent"])
        self.create_merchant(base["approved_merchant"])
        self.create_merchant(base["unknown_merchant"])
        self.create_passport(base["passport"])

    def list_intents(
        self,
        tenant_id: UUID,
        *,
        state: PaymentState | None = None,
        agent_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentIntent]:
        rows = [
            row
            for row in super().list_intents(tenant_id)
            if (state is None or row.state == state)
            and (agent_id is None or row.agent_id == agent_id)
        ]
        return rows[offset : offset + limit]

    def list_attempts_for_intent(
        self, tenant_id: UUID, payment_intent_id: UUID
    ) -> list[PaymentAttempt]:
        return sorted(
            [
                row
                for row in self.attempts.values()
                if row.tenant_id == tenant_id and row.payment_intent_id == payment_intent_id
            ],
            key=lambda item: item.attempt_number,
        )

    def update_agent_status(self, tenant_id: UUID, agent_id: UUID, status: str) -> None:
        agent = self.agents[agent_id]
        assert agent.tenant_id == tenant_id
        self.agents[agent_id] = agent.model_copy(update={"status": status})


class ExtendedMockPayPalClient(MockPayPalClient):
    """Mock PayPal client adding capture, refund, and configurable failure hooks."""

    def __init__(self) -> None:
        super().__init__(mode="success")
        self.create_calls = 0
        self.capture_calls = 0
        self.refund_calls = 0
        self.fail_create_with: Exception | None = None

    async def create_order(
        self,
        *,
        amount_minor: int,
        currency: str,
        reference_id: str,
        description: str,
        request_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PayPalOrderCreationResult:
        self.create_calls += 1
        if self.fail_create_with is not None:
            raise self.fail_create_with
        return await super().create_order(
            amount_minor=amount_minor,
            currency=currency,
            reference_id=reference_id,
            description=description,
            request_id=request_id,
            return_url=return_url,
            cancel_url=cancel_url,
        )

    async def capture_order(
        self,
        *,
        paypal_order_id: str,
        expected_amount_minor: int,
        expected_currency: str,
        request_id: str | None = None,
    ) -> PayPalCaptureResult:
        self.capture_calls += 1
        return await super().capture_order(
            paypal_order_id=paypal_order_id,
            expected_amount_minor=expected_amount_minor,
            expected_currency=expected_currency,
            request_id=request_id,
        )

    async def refund_capture(
        self,
        capture_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        self.refund_calls += 1
        return {
            "id": f"PP-REF-{self.refund_calls:03d}",
            "status": "COMPLETED",
            "capture_id": capture_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "idempotency_key": idempotency_key,
            "note": note,
        }


def _make_proposal_and_quote(
    *,
    amount_minor: int = 3900,
    merchant_id: UUID = MERCHANT_SANDBOX_CLOUD_ID,
    passport_id: UUID = PASSPORT_DEFAULT_ID,
    currency: str = "USD",
    idempotency_key: str | None = None,
    quote_expires_delta: timedelta = timedelta(minutes=30),
) -> tuple[PurchaseProposal, QuoteSnapshot]:
    now = datetime.now(UTC)
    prop_id = uuid4()
    corr_id = uuid4()
    line_items = [{"name": "Credit", "qty": 1, "unit_minor": amount_minor}]
    q_hash = compute_quote_hash(
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency=currency,
        line_items=line_items,
    )
    quote = QuoteSnapshot(
        id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        proposal_id=prop_id,
        merchant_id=merchant_id,
        amount_minor=amount_minor,
        currency=currency,
        line_items=line_items,
        quote_hash=q_hash,
        expires_at=now + quote_expires_delta,
        created_at=now,
    )
    proposal = PurchaseProposal(
        id=prop_id,
        tenant_id=TENANT_ALPHA_ID,
        correlation_id=corr_id,
        agent_id=AGENT_PROCUREMENT_ID,
        passport_id=passport_id,
        merchant_id=merchant_id,
        merchant_name="Sandbox Cloud",
        merchant_category="CLOUD_INFRA",
        amount_minor=amount_minor,
        currency=currency,
        item_summary="GPU training credit",
        line_items=line_items,
        rationale="Hardening test purchase",
        idempotency_key=idempotency_key or f"idem-{uuid4().hex[:12]}",
    )
    return proposal, quote


def test_gap001_approval_rejection_fails_intent_releases_budget_and_blocks_checkout() -> None:
    repo = ExtendedInMemoryRepo()
    pp = ExtendedMockPayPalClient()
    svc = GuardianService(repo=repo, paypal_client=pp)

    # $75 > $50 approval threshold -> AWAITING_APPROVAL
    proposal, quote = _make_proposal_and_quote(amount_minor=7500)
    intent, _ = svc.submit_proposal(proposal=proposal, quote=quote)
    assert intent.state == PaymentState.AWAITING_APPROVAL
    assert intent.approval_record_id is not None

    rejected_intent, rejected_approval = svc.approve_and_consume(
        tenant_id=TENANT_ALPHA_ID,
        intent_id=intent.id,
        approval_id=intent.approval_record_id,
        approver_id="finance-reviewer@example.com",
        approved=False,
        comment="Out of quarterly scope",
    )
    assert rejected_approval.status == ApprovalStatus.REJECTED
    assert rejected_intent.state == PaymentState.FAILED
    assert repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID).reserved_minor == 0

    events = [e.event_type for e in repo.list_events(TENANT_ALPHA_ID, payment_intent_id=intent.id)]
    assert FinancialEventType.HUMAN_REJECTED in events
    assert FinancialEventType.PAYMENT_FAILED in events

    with pytest.raises(InvalidStateTransitionError):
        run_sync(
            svc.initiate_checkout(
                tenant_id=TENANT_ALPHA_ID,
                intent_id=intent.id,
                idempotency_key="checkout-after-reject",
            )
        )
    with pytest.raises(InvalidStateTransitionError):
        run_sync(
            svc.execute_capture(
                tenant_id=TENANT_ALPHA_ID,
                intent_id=intent.id,
                attempt_id=uuid4(),
            )
        )


def test_gap005_cross_intent_approval_replay_tampered_expired_quote_and_revoked_passport() -> None:
    repo = ExtendedInMemoryRepo()
    pp = ExtendedMockPayPalClient()
    svc = GuardianService(repo=repo, paypal_client=pp)

    p1, q1 = _make_proposal_and_quote(amount_minor=6000)
    intent1, _ = svc.submit_proposal(proposal=p1, quote=q1)

    p2, q2 = _make_proposal_and_quote(amount_minor=6000)
    # Give enough budget for both pending reservations
    passport = repo.passports[PASSPORT_DEFAULT_ID]
    repo.passports[PASSPORT_DEFAULT_ID] = passport.model_copy(
        update={"total_budget_minor": 30000, "daily_limit_minor": 30000}
    )
    intent2, _ = svc.submit_proposal(proposal=p2, quote=q2)
    assert intent1.approval_record_id is not None
    assert intent2.approval_record_id is not None

    # Cross-intent approval replay blocked
    with pytest.raises(ApprovalMismatchError):
        svc.approve_and_consume(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            approval_id=intent2.approval_record_id,
            approver_id="reviewer-1",
            approved=True,
        )

    # Quote tampered after approval creation is caught at consume time
    repo.quotes[q1.id] = q1.model_copy(update={"amount_minor": 6100})
    with pytest.raises(ApprovalMismatchError):
        svc.approve_and_consume(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            approval_id=intent1.approval_record_id,
            approver_id="reviewer-1",
            approved=True,
        )
    repo.quotes[q1.id] = q1  # restore quote
    repo.approvals[intent1.approval_record_id] = repo.approvals[
        intent1.approval_record_id
    ].model_copy(update={"status": ApprovalStatus.PENDING})

    # Expired quote caught at consume time
    repo.quotes[q1.id] = q1.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=5)})
    with pytest.raises(ApprovalExpiredError):
        svc.approve_and_consume(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            approval_id=intent1.approval_record_id,
            approver_id="reviewer-1",
            approved=True,
        )
    repo.quotes[q1.id] = q1  # restore valid quote
    repo.approvals[intent1.approval_record_id] = repo.approvals[
        intent1.approval_record_id
    ].model_copy(update={"status": ApprovalStatus.PENDING})

    # Revoked passport caught at consume time
    repo.passports[PASSPORT_DEFAULT_ID] = repo.passports[PASSPORT_DEFAULT_ID].model_copy(
        update={"status": PassportStatus.REVOKED}
    )
    with pytest.raises(PolicyDeniedError):
        svc.approve_and_consume(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            approval_id=intent1.approval_record_id,
            approver_id="reviewer-1",
            approved=True,
        )

    # Direct ApprovalService.consume_approval verifies quote_hash binding too
    repo.passports[PASSPORT_DEFAULT_ID] = repo.passports[PASSPORT_DEFAULT_ID].model_copy(
        update={"status": PassportStatus.ACTIVE}
    )
    approval2 = repo.approvals[intent2.approval_record_id]
    repo.approvals[approval2.id] = approval2.model_copy(
        update={
            "status": ApprovalStatus.APPROVED,
            "quote_hash": compute_quote_hash(
                merchant_id=q2.merchant_id,
                amount_minor=q2.amount_minor,
                currency=q2.currency,
                line_items=q2.line_items,
            ),
        }
    )
    with pytest.raises(ApprovalMismatchError):
        svc.approval_service.consume_approval(
            tenant_id=TENANT_ALPHA_ID,
            approval_id=approval2.id,
            payment_intent_id=intent1.id,
            current_merchant_id=q2.merchant_id,
            current_amount_minor=q2.amount_minor,
            current_currency=q2.currency,
            current_quote_hash=q2.quote_hash,
            quote=q2,
            passport=repo.passports[PASSPORT_DEFAULT_ID],
        )


def test_gap011_policy_v1_agent_status_daily_limit_and_strict_passport_allowlist() -> None:
    repo = ExtendedInMemoryRepo()
    pp = ExtendedMockPayPalClient()
    svc = GuardianService(repo=repo, paypal_client=pp)

    # 1. Suspended agent must be denied even if passport is active
    repo.update_agent_status(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID, "SUSPENDED")
    p_susp, q_susp = _make_proposal_and_quote(amount_minor=2000)
    with pytest.raises(PolicyDeniedError) as exc_susp:
        svc.submit_proposal(proposal=p_susp, quote=q_susp)
    assert "DENIED_AGENT_SUSPENDED" in [str(r) for r in exc_susp.value.reason_codes]

    repo.update_agent_status(TENANT_ALPHA_ID, AGENT_PROCUREMENT_ID, "ACTIVE")

    # 2. Strict passport allowlist: global is_allowlisted=True merchant NOT in passport.allowed_merchant_ids is denied
    global_only_merchant = Merchant(
        id=uuid4(),
        tenant_id=TENANT_ALPHA_ID,
        name="Global Allowlisted But Not On Passport",
        domain="global-only.example.com",
        category="CLOUD_INFRA",
        is_allowlisted=True,
        is_sandbox_verified=True,
    )
    repo.merchants[global_only_merchant.id] = global_only_merchant
    p_merch, q_merch = _make_proposal_and_quote(
        amount_minor=2000, merchant_id=global_only_merchant.id
    )
    with pytest.raises(PolicyDeniedError) as exc_merch:
        svc.submit_proposal(proposal=p_merch, quote=q_merch)
    assert "DENIED_MERCHANT_NOT_ALLOWLISTED" in [str(r) for r in exc_merch.value.reason_codes]

    # 3. Rolling daily_limit_minor enforced across same-day intents
    passport = repo.passports[PASSPORT_DEFAULT_ID]
    repo.passports[PASSPORT_DEFAULT_ID] = passport.model_copy(
        update={
            "total_budget_minor": 50000,
            "per_tx_limit_minor": 8000,
            "daily_limit_minor": 10000,
            "human_approval_threshold_minor": 9000,
        }
    )
    p_day1, q_day1 = _make_proposal_and_quote(amount_minor=6000)
    intent1, _ = svc.submit_proposal(proposal=p_day1, quote=q_day1)
    assert intent1.state == PaymentState.CHECKOUT_READY

    p_day2, q_day2 = _make_proposal_and_quote(amount_minor=4500)
    with pytest.raises(PolicyDeniedError) as exc_daily:
        svc.submit_proposal(proposal=p_day2, quote=q_day2)
    assert "DENIED_EXCEEDS_DAILY_LIMIT" in [str(r) for r in exc_daily.value.reason_codes]


def test_gap016_idempotency_payload_tampering_and_checkout_attempt_idempotency() -> None:
    repo = ExtendedInMemoryRepo()
    pp = ExtendedMockPayPalClient()
    svc = GuardianService(repo=repo, paypal_client=pp)

    idem = "idem-fixed-payload-check"
    p1, q1 = _make_proposal_and_quote(amount_minor=3900, idempotency_key=idem)
    intent1, _ = svc.submit_proposal(proposal=p1, quote=q1)

    # Identical payload returns the existing intent
    p_same, q_same = _make_proposal_and_quote(amount_minor=3900, idempotency_key=idem)
    intent_same, _ = svc.submit_proposal(proposal=p_same, quote=q_same)
    assert intent_same.id == intent1.id

    # Tampered amount / merchant / currency / passport raises DuplicateIntentError
    for kwargs in (
        {"amount_minor": 4000},
        {"merchant_id": MERCHANT_UNKNOWN_ID},
        {"currency": "EUR"},
        {"passport_id": uuid4()},
    ):
        p_bad, q_bad = _make_proposal_and_quote(
            amount_minor=kwargs.get("amount_minor", 3900),
            merchant_id=kwargs.get("merchant_id", MERCHANT_SANDBOX_CLOUD_ID),
            currency=kwargs.get("currency", "USD"),
            passport_id=kwargs.get("passport_id", PASSPORT_DEFAULT_ID),
            idempotency_key=idem,
        )
        with pytest.raises(DuplicateIntentError):
            svc.submit_proposal(proposal=p_bad, quote=q_bad)

    # Checkout attempt idempotency: same attempt_number + idempotency_key does not re-create PayPal order
    _, att1 = run_sync(
        svc.initiate_checkout(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            attempt_number=1,
            idempotency_key="att-key-001",
        )
    )
    _, att1_retry = run_sync(
        svc.initiate_checkout(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            attempt_number=1,
            idempotency_key="att-key-001",
        )
    )
    assert att1_retry.id == att1.id
    assert pp.create_calls == 1

    # Reusing attempt idempotency_key for a different attempt_number fails closed
    with pytest.raises(DuplicateIntentError):
        run_sync(
            svc.initiate_checkout(
                tenant_id=TENANT_ALPHA_ID,
                intent_id=intent1.id,
                attempt_number=2,
                idempotency_key="att-key-001",
            )
        )


def test_gap012_precapture_guard_checkout_failure_reconcile_evidence_and_refund() -> None:
    repo = ExtendedInMemoryRepo()
    pp = ExtendedMockPayPalClient()
    svc = GuardianService(repo=repo, paypal_client=pp)

    # 1. Pre-capture guard: intent not in CAPTURE_PENDING must fail BEFORE PayPal capture_order call
    p1, q1 = _make_proposal_and_quote(amount_minor=3000)
    intent1, _ = svc.submit_proposal(proposal=p1, quote=q1)
    _, att1 = run_sync(
        svc.initiate_checkout(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            idempotency_key="att-precapture-1",
        )
    )
    assert intent1.state == PaymentState.CHECKOUT_READY
    with pytest.raises(InvalidStateTransitionError):
        run_sync(
            svc.execute_capture(
                tenant_id=TENANT_ALPHA_ID,
                intent_id=intent1.id,
                attempt_id=att1.id,
            )
        )
    assert pp.capture_calls == 0

    # 2. Checkout failure releases reservation and marks intent FAILED
    pp_fail = ExtendedMockPayPalClient()
    pp_fail.fail_create_with = PayPalAPIError("sandbox 503", status_code=503)
    svc_fail = GuardianService(repo=repo, paypal_client=pp_fail)
    p2, q2 = _make_proposal_and_quote(amount_minor=2000)
    intent2, _ = svc_fail.submit_proposal(proposal=p2, quote=q2)
    reserved_before = repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID).reserved_minor
    assert reserved_before == 5000  # 3000 + 2000

    with pytest.raises(PayPalAPIError):
        run_sync(
            svc_fail.initiate_checkout(
                tenant_id=TENANT_ALPHA_ID,
                intent_id=intent2.id,
                idempotency_key="att-fail-2",
            )
        )
    assert repo.get_intent(TENANT_ALPHA_ID, intent2.id).state == PaymentState.FAILED
    assert repo.get_passport(TENANT_ALPHA_ID, PASSPORT_DEFAULT_ID).reserved_minor == 3000

    # 3. Reconcile PENDING_PROVIDER -> SUCCEEDED persists PAYPAL_CAPTURE EvidenceRecord, then refund -> REFUNDED
    pp.mode = "timeout"
    svc.handle_buyer_approved(
        tenant_id=TENANT_ALPHA_ID,
        intent_id=intent1.id,
        attempt_id=att1.id,
        payer_id="PAYER-1",
    )
    pending_intent, pending_att = run_sync(
        svc.execute_capture(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            attempt_id=att1.id,
        )
    )
    assert pending_intent.state == PaymentState.PENDING_PROVIDER

    pp.mode = "success"
    settled_intent, settled_att = run_sync(
        svc.reconcile_pending(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            attempt_id=pending_att.id,
        )
    )
    assert settled_intent.state == PaymentState.SUCCEEDED
    ev_sources = [
        ev.source_type for ev in repo.list_evidence(TENANT_ALPHA_ID, payment_intent_id=intent1.id)
    ]
    assert EvidenceSourceType.PAYPAL_CAPTURE in ev_sources

    refunded_intent, _, refund_payload = run_sync(
        svc.refund_payment(
            tenant_id=TENANT_ALPHA_ID,
            intent_id=intent1.id,
            attempt_id=settled_att.id,
            reason="Duplicate license purchase",
        )
    )
    assert refunded_intent.state == PaymentState.REFUNDED
    assert refund_payload["status"] == "COMPLETED"
    assert pp.refund_calls == 1
    events = [e.event_type for e in repo.list_events(TENANT_ALPHA_ID, payment_intent_id=intent1.id)]
    assert FinancialEventType.PAYMENT_REFUNDED in events


def test_guardian_standalone_router_auth_and_error_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = ExtendedInMemoryRepo()
    pp = ExtendedMockPayPalClient()
    svc = GuardianService(repo=repo, paypal_client=pp)

    # Unauthenticated X-Tenant-Id must be rejected in non-dev/test env when no tenant_resolver is supplied
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        unprotected_app = FastAPI()
        unprotected_app.include_router(create_guardian_router(svc))
        with TestClient(unprotected_app) as client:
            res_401 = client.get(
                f"/guardian/payments/{uuid4()}",
                headers={"X-Tenant-Id": str(TENANT_ALPHA_ID)},
            )
            assert res_401.status_code == 401
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        get_settings.cache_clear()
    app = FastAPI()
    app.include_router(create_guardian_router(svc, tenant_resolver=lambda: TENANT_ALPHA_ID))
    with TestClient(app) as client:
        # Checkout failure maps PayPalTimeoutError -> 504 and PayPalAPIError -> 502
        p_ok, q_ok = _make_proposal_and_quote(amount_minor=2500, idempotency_key="router-idem-1")
        prop_res = client.post(
            "/guardian/proposals",
            json={
                "tenant_id": str(TENANT_ALPHA_ID),
                "agent_id": str(AGENT_PROCUREMENT_ID),
                "passport_id": str(PASSPORT_DEFAULT_ID),
                "merchant_id": str(MERCHANT_SANDBOX_CLOUD_ID),
                "merchant_name": p_ok.merchant_name,
                "merchant_category": p_ok.merchant_category,
                "amount_minor": 2500,
                "currency": "USD",
                "item_summary": p_ok.item_summary,
                "line_items": p_ok.line_items,
                "rationale": p_ok.rationale,
                "idempotency_key": "router-idem-1",
            },
        )
        assert prop_res.status_code == 201
        intent_id = prop_res.json()["payment_intent"]["id"]

        # Tampered idempotency -> 409
        tamper_res = client.post(
            "/guardian/proposals",
            json={
                "tenant_id": str(TENANT_ALPHA_ID),
                "agent_id": str(AGENT_PROCUREMENT_ID),
                "passport_id": str(PASSPORT_DEFAULT_ID),
                "merchant_id": str(MERCHANT_SANDBOX_CLOUD_ID),
                "merchant_name": p_ok.merchant_name,
                "merchant_category": p_ok.merchant_category,
                "amount_minor": 2600,
                "currency": "USD",
                "item_summary": p_ok.item_summary,
                "line_items": p_ok.line_items,
                "rationale": p_ok.rationale,
                "idempotency_key": "router-idem-1",
            },
        )
        assert tamper_res.status_code == 409

        pp.fail_create_with = PayPalTimeoutError("timeout")
        assert (
            client.post(f"/guardian/payments/{intent_id}/checkout", json={}).status_code == 504
        )


def test_guardian_db_router_detachment_rejection_pagination_snapshots_and_refund(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "guardian_hardening.db"
    settings = NexusSettings(
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret-guardian-hardening-32",
        signing_secret="test-hmac-secret-guardian-hardening",
        evidence_storage_dir=str(tmp_path / "evidence"),
        rate_limit_rpm=5000,
        paypal_client_id="sandbox-client",
        paypal_client_secret="sandbox-secret",
        paypal_webhook_id="WH-HARDEN",
    )

    pool_checked_out_during_http: list[tuple[str, int]] = []
    app_ref: dict[str, FastAPI] = {}
    pp_state: dict[str, str] = {"order_status": "APPROVED"}

    def pp_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path != "/v1/oauth2/token" and "app" in app_ref:
            checked = app_ref["app"].state.engine.pool.checkedout()
            pool_checked_out_during_http.append((f"{request.method} {path}", checked))
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        if path == "/v2/checkout/orders" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "PP-ORD-HARDEN-1",
                    "status": "CREATED",
                    "links": [
                        {
                            "rel": "approve",
                            "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP-ORD-HARDEN-1",
                        }
                    ],
                },
            )
        if path.endswith("/capture") and request.method == "POST":
            pp_state["order_status"] = "COMPLETED"
            return httpx.Response(
                201,
                json={
                    "id": "PP-ORD-HARDEN-1",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": "PP-CAP-HARDEN-1",
                                        "status": "COMPLETED",
                                        "amount": {"currency_code": "USD", "value": "39.00"},
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if path.startswith("/v2/checkout/orders/") and request.method == "GET":
            if pp_state["order_status"] == "COMPLETED":
                return httpx.Response(
                    200,
                    json={
                        "id": "PP-ORD-HARDEN-1",
                        "status": "COMPLETED",
                        "purchase_units": [
                            {
                                "payments": {
                                    "captures": [
                                        {
                                            "id": "PP-CAP-HARDEN-1",
                                            "status": "COMPLETED",
                                            "amount": {"currency_code": "USD", "value": "39.00"},
                                        }
                                    ]
                                }
                            }
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={"id": "PP-ORD-HARDEN-1", "status": pp_state["order_status"]},
            )
        if path == "/v2/payments/captures/PP-CAP-HARDEN-1/refund" and request.method == "POST":
            return httpx.Response(201, json={"id": "PP-REF-HARDEN-1", "status": "COMPLETED"})
        return httpx.Response(404, json={"error": path})

    pp_http = httpx.AsyncClient(
        base_url="https://api-m.sandbox.paypal.com",
        transport=httpx.MockTransport(pp_handler),
    )
    paypal_client = PayPalSandboxClient(settings=settings, http_client=pp_http)
    app = create_app(settings=settings, paypal_client=paypal_client, create_tables=True)
    app_ref["app"] = app

    with TestClient(app) as client:
        reg = client.post(
            "/v1/auth/register",
            json={
                "email": "hardening-owner@example.com",
                "password": "StrongPassword!123",
                "full_name": "Hardening Owner",
                "organization_name": "Hardening Org",
                "organization_slug": "hardening-org",
            },
        )
        assert reg.status_code == 201
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create 2 agents & 2 merchants for pagination checks
        agent_ids = []
        for idx in range(2):
            ar = client.post(
                "/v1/guardian/agents",
                headers=headers,
                json={
                    "name": f"Agent-{idx}",
                    "purpose": "procurement",
                    "framework": "langgraph",
                    "public_fingerprint": f"fp-hardening-agent-{idx:02d}",
                },
            )
            assert ar.status_code == 201
            agent_ids.append(ar.json()["id"])

        merchant_ids = []
        for idx in range(2):
            mr = client.post(
                "/v1/guardian/merchants",
                headers=headers,
                json={
                    "name": f"Merchant-{idx}",
                    "domain": f"m{idx}.example.com",
                    "category": "SOFTWARE",
                },
            )
            assert mr.status_code == 201
            merchant_ids.append(mr.json()["id"])

        # Create passport + verify snapshot v1 -> patch v2 -> revoke v3 -> fresh active passport
        pr = client.post(
            "/v1/guardian/passports",
            headers=headers,
            json={
                "agent_id": agent_ids[0],
                "currency": "USD",
                "total_budget_minor": 30000,
                "per_tx_limit_minor": 10000,
                "daily_limit_minor": 30000,
                "human_approval_threshold_minor": 5000,
                "allowed_merchant_ids": [merchant_ids[0]],
                "allowed_categories": ["SOFTWARE"],
            },
        )
        assert pr.status_code == 201
        passport_to_revoke = pr.json()["id"]

        patch_r = client.patch(
            f"/v1/guardian/passports/{passport_to_revoke}",
            headers=headers,
            json={"daily_limit_minor": 25000},
        )
        assert patch_r.status_code == 200
        rev_r = client.post(
            f"/v1/guardian/passports/{passport_to_revoke}/revoke",
            headers=headers,
        )
        assert rev_r.status_code == 200

        with app.state.session_factory() as s:
            latest_snap = LedgerRepository(s).get_latest_passport_snapshot(
                UUID(reg.json()["active_tenant_id"]), UUID(passport_to_revoke)
            )
            assert latest_snap is not None
            assert latest_snap["version"] == 3

        # Active passport for payment flows
        pr2 = client.post(
            "/v1/guardian/passports",
            headers=headers,
            json={
                "agent_id": agent_ids[0],
                "currency": "USD",
                "total_budget_minor": 30000,
                "per_tx_limit_minor": 10000,
                "daily_limit_minor": 30000,
                "human_approval_threshold_minor": 5000,
                "allowed_merchant_ids": [merchant_ids[0]],
                "allowed_categories": ["SOFTWARE"],
            },
        )
        assert pr2.status_code == 201
        active_passport_id = pr2.json()["id"]

        # Pagination checks
        assert len(client.get("/v1/guardian/agents?limit=1&offset=1", headers=headers).json()) == 1
        assert len(client.get("/v1/guardian/merchants?limit=1&offset=1", headers=headers).json()) == 1
        assert len(client.get("/v1/guardian/passports?limit=1&offset=1", headers=headers).json()) == 1

        # Proposal requiring approval ($70 > $50) rejected via approved=false
        rej_prop = client.post(
            "/v1/guardian/proposals",
            headers=headers,
            json={
                "agent_id": agent_ids[0],
                "passport_id": active_passport_id,
                "merchant_id": merchant_ids[0],
                "merchant_name": "Merchant-0",
                "merchant_category": "SOFTWARE",
                "amount_minor": 7000,
                "currency": "USD",
                "item_summary": "Expensive seat",
                "rationale": "Test rejection",
                "idempotency_key": "db-reject-idem-001",
            },
        )
        assert rej_prop.status_code == 201
        rej_intent_id = rej_prop.json()["payment_intent"]["id"]

        # Tampered idempotency -> 409
        tamper_prop = client.post(
            "/v1/guardian/proposals",
            headers=headers,
            json={
                "agent_id": agent_ids[0],
                "passport_id": active_passport_id,
                "merchant_id": merchant_ids[0],
                "merchant_name": "Merchant-0",
                "merchant_category": "SOFTWARE",
                "amount_minor": 7100,
                "currency": "USD",
                "item_summary": "Expensive seat",
                "rationale": "Tampered",
                "idempotency_key": "db-reject-idem-001",
            },
        )
        assert tamper_prop.status_code == 409

        # Reject via approved=false -> FAILED, reserved_minor==0, subsequent capture/checkout -> 409
        dec_rej = client.post(
            f"/v1/guardian/proposals/{rej_intent_id}/approve",
            headers=headers,
            json={"approver_id": "owner", "approved": False, "comment": "Rejected"},
        )
        assert dec_rej.status_code == 200
        assert dec_rej.json()["payment_intent"]["state"] == "FAILED"
        assert dec_rej.json()["approval"]["status"] == "REJECTED"

        passports_after_reject = client.get("/v1/guardian/passports", headers=headers).json()
        p_active_obj = next(p for p in passports_after_reject if p["id"] == active_passport_id)
        assert p_active_obj["reserved_minor"] == 0

        assert (
            client.post(
                f"/v1/guardian/payments/{rej_intent_id}/capture",
                headers=headers,
                json={"attempt_id": str(uuid4())},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/v1/guardian/payments/{rej_intent_id}/checkout",
                headers=headers,
                json={},
            ).status_code
            == 409
        )

        # Full payment -> detached checkout -> buyer-approved -> detached capture -> detached refund
        ok_prop = client.post(
            "/v1/guardian/proposals",
            headers=headers,
            json={
                "agent_id": agent_ids[0],
                "passport_id": active_passport_id,
                "merchant_id": merchant_ids[0],
                "merchant_name": "Merchant-0",
                "merchant_category": "SOFTWARE",
                "amount_minor": 3900,
                "currency": "USD",
                "item_summary": "Standard seat",
                "rationale": "Test detached capture and refund",
                "idempotency_key": "db-ok-idem-001",
            },
        )
        assert ok_prop.status_code == 201
        ok_intent_id = ok_prop.json()["payment_intent"]["id"]

        chk = client.post(
            f"/v1/guardian/payments/{ok_intent_id}/checkout",
            headers=headers,
            json={"attempt_number": 1},
        )
        assert chk.status_code == 200
        attempt_id = chk.json()["attempt"]["id"]

        ba = client.post(
            f"/v1/guardian/payments/{ok_intent_id}/buyer-approved",
            headers=headers,
            json={"attempt_id": attempt_id, "payer_id": "PAYER-HARDEN"},
        )
        assert ba.status_code == 200

        cap = client.post(
            f"/v1/guardian/payments/{ok_intent_id}/capture",
            headers=headers,
            json={"attempt_id": attempt_id},
        )
        assert cap.status_code == 200
        assert cap.json()["payment_intent"]["state"] == "SUCCEEDED"

        ref = client.post(
            f"/v1/guardian/payments/{ok_intent_id}/refund",
            headers=headers,
            json={"attempt_id": attempt_id, "reason": "Customer requested refund"},
        )
        assert ref.status_code == 200
        assert ref.json()["payment_intent"]["state"] == "REFUNDED"
        assert ref.json()["refund"]["id"] == "PP-REF-HARDEN-1"

        detail = client.get(f"/v1/guardian/payments/{ok_intent_id}/detail", headers=headers).json()
        assert any(ev["event_type"] == "PAYMENT_REFUNDED" for ev in detail["events"])

        # Confirm zero DB connections were checked out while awaiting every PayPal HTTP call!
        assert len(pool_checked_out_during_http) >= 3
        assert all(checked == 0 for _, checked in pool_checked_out_during_http), (
            f"Expected 0 checked-out DB connections during PayPal HTTP I/O, got {pool_checked_out_during_http}"
        )
