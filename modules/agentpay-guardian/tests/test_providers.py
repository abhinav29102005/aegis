"""Unit tests for Guardian multi-rail payment provider adapters (GAP-025)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from contracts import (
    PaymentProviderAdapter,
    PurchaseProposal,
    QuoteSnapshot,
    TAPTokenPayload,
    X402SettlementProof,
)
from security import sign_hmac_sha256

from guardian.providers import (
    AP2CheckoutMandate,
    AP2MandateAdapter,
    AP2PaymentMandate,
    DeflectionAlertAdapter,
    ProviderSignatureError,
    ProviderValidationError,
    StripeProviderAdapter,
    TAPProvenanceAdapter,
    X402SettlementAdapter,
)


def test_all_adapters_implement_payment_provider_protocol() -> None:
    adapters = [
        StripeProviderAdapter(api_key="sk_test_123", webhook_secret="whsec_123"),
        AP2MandateAdapter(signing_secret="ap2-secret"),
        TAPProvenanceAdapter(signing_secret="tap-secret"),
        X402SettlementAdapter(webhook_secret="x402-secret"),
        DeflectionAlertAdapter(webhook_secret="defl-secret"),
    ]
    for adapter in adapters:
        assert isinstance(adapter, PaymentProviderAdapter)


@pytest.mark.asyncio
async def test_stripe_payment_intent_spt_connect_refund_void_disputes_and_retry() -> None:
    calls = {"pi_attempts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/payment_intents" and request.method == "POST":
            calls["pi_attempts"] += 1
            if calls["pi_attempts"] == 1:
                return httpx.Response(503, text="upstream busy")
            form = parse_qs(request.content.decode("utf-8"))
            assert form["amount"] == ["4200"]
            assert form["currency"] == ["usd"]
            assert form["shared_payment_granted_token"] == ["spt_agent_123"]
            assert form["transfer_data[destination]"] == ["acct_connect_99"]
            assert request.headers.get("Stripe-Account") == "acct_platform_1"
            assert request.headers.get("Idempotency-Key") == "idem-stripe-1"
            return httpx.Response(
                200,
                json={"id": "pi_123", "status": "requires_capture", "amount": 4200, "currency": "usd"},
            )
        if request.url.path == "/v1/shared_payment/issued_tokens":
            return httpx.Response(200, json={"id": "spt_agent_123", "object": "shared_payment.issued_token"})
        if request.url.path == "/v1/transfers":
            return httpx.Response(200, json={"id": "tr_123", "amount": 4000, "currency": "usd"})
        if request.url.path == "/v1/payment_intents/pi_123/capture":
            return httpx.Response(200, json={"id": "pi_123", "latest_charge": "ch_123", "status": "succeeded", "amount_received": 4200, "currency": "usd"})
        if request.url.path == "/v1/refunds":
            form = parse_qs(request.content.decode("utf-8"))
            assert form["charge"] == ["ch_123"]
            assert form["reason"] == ["requested_by_customer"]
            return httpx.Response(200, json={"id": "re_123", "status": "succeeded", "amount": 4200, "currency": "usd"})
        if request.url.path == "/v1/issuing/authorizations/iauth_777/decline":
            return httpx.Response(200, json={"id": "iauth_777", "status": "closed"})
        if request.url.path == "/v1/disputes/dp_123":
            form = parse_qs(request.content.decode("utf-8"))
            assert form["submit"] == ["true"]
            assert form["evidence[shipping_tracking_number]"] == ["1Z999AA1"]
            return httpx.Response(200, json={"id": "dp_123", "status": "under_review"})
        if request.url.path == "/v1/disputes/dp_123/close":
            return httpx.Response(200, json={"id": "dp_123", "status": "lost"})
        return httpx.Response(404)

    async_client = httpx.AsyncClient(base_url="https://api.stripe.com", transport=httpx.MockTransport(handler))
    stripe = StripeProviderAdapter(
        api_key="sk_test_123",
        webhook_secret="whsec_test_123",
        http_client=async_client,
        retry_base_delay=0.0,
    )

    spt = await stripe.create_shared_payment_token(
        payment_method_id="pm_123",
        max_amount_minor=5000,
        currency="USD",
        expires_at_epoch=int(time.time()) + 600,
        idempotency_key="idem-spt-1",
    )
    assert spt["id"] == "spt_agent_123"

    order = await stripe.create_order(
        amount_minor=4200,
        currency="USD",
        idempotency_key="idem-stripe-1",
        metadata={
            "shared_payment_token": "spt_agent_123",
            "connect_destination": "acct_connect_99",
            "stripe_account": "acct_platform_1",
        },
    )
    assert calls["pi_attempts"] == 2
    assert order["order_id"] == "pi_123"

    transfer = await stripe.create_connect_transfer(
        amount_minor=4000,
        currency="USD",
        destination_account="acct_connect_99",
        idempotency_key="idem-tr-1",
    )
    assert transfer["id"] == "tr_123"

    captured = await stripe.capture_order(order_id="pi_123", idempotency_key="idem-cap-1", amount_minor=4200, currency="USD")
    assert captured["capture_id"] == "ch_123"

    refunded = await stripe.refund_capture(
        capture_id="ch_123",
        amount_minor=4200,
        currency="USD",
        idempotency_key="idem-ref-1",
        reason="requested_by_customer",
    )
    assert refunded["refund_id"] == "re_123"

    voided = await stripe.void_authorization(authorization_id="iauth_777", idempotency_key="idem-void-1")
    assert voided["status"] == "closed"

    dispute = await stripe.provide_dispute_evidence(
        dispute_id="dp_123",
        evidence_type="PROOF_OF_DELIVERY",
        notes="Delivered to billing zip",
        documents=[{"tracking_number": "1Z999AA1"}],
    )
    assert dispute["status"] == "under_review"

    closed = await stripe.accept_dispute_claim(dispute_id="dp_123", reason="Concede low value")
    assert closed["status"] == "lost"
    await async_client.aclose()


@pytest.mark.asyncio
async def test_stripe_issuing_webhook_verification_and_tamper_rejection() -> None:
    secret = "whsec_issuing_secret"
    stripe = StripeProviderAdapter(api_key="sk_test_123", webhook_secret=secret)
    tenant_id = uuid4()
    event_payload = {
        "id": "evt_iss_1",
        "type": "issuing_authorization.request",
        "api_version": "2025-01-27.acacia",
        "data": {
            "object": {
                "id": "iauth_999",
                "amount": 1999,
                "currency": "usd",
                "approved": True,
                "card": {"id": "ic_456"},
                "merchant_data": {"name": "CloudCompute", "category": "computer_software_stores"},
                "metadata": {"tenant_id": str(tenant_id)},
            }
        },
    }
    raw_body = json.dumps(event_payload).encode("utf-8")
    ts = int(time.time())
    sig = hmac.new(secret.encode("utf-8"), f"{ts}.{raw_body.decode('utf-8')}".encode(), hashlib.sha256).hexdigest()

    parsed = await stripe.parse_issuing_webhook(
        headers={"Stripe-Signature": f"t={ts},v1={sig}"},
        body=raw_body,
    )
    assert parsed["verified"] is True
    assert parsed["authorization_id"] == "iauth_999"
    assert parsed["card_id"] == "ic_456"
    assert parsed["amount_minor"] == 1999
    assert parsed["currency"] == "USD"

    with pytest.raises(ProviderSignatureError):
        await stripe.verify_webhook(
            headers={"Stripe-Signature": f"t={ts},v1=deadbeef"},
            body=raw_body,
        )


@pytest.mark.asyncio
async def test_ap2_mandate_verification_and_guardian_import() -> None:
    secret = "ap2-shared-hmac-secret"
    adapter = AP2MandateAdapter(signing_secret=secret)
    tenant_id = uuid4()
    agent_id = uuid4()
    passport_id = uuid4()
    merchant_id = uuid4()
    expires = datetime.now(UTC) + timedelta(minutes=30)

    payment_mandate_unsigned = AP2PaymentMandate(
        mandate_id="pm_ap2_001",
        tenant_id=tenant_id,
        agent_id=agent_id,
        passport_id=passport_id,
        merchant_id=merchant_id,
        max_amount_minor=10000,
        currency="USD",
        scope=["checkout", "software"],
        expires_at=expires,
        signature="placeholder",
    )
    payment_sig = sign_hmac_sha256(
        adapter.payment_mandate_signing_payload(payment_mandate_unsigned),
        secret,
    )
    payment_mandate = payment_mandate_unsigned.model_copy(update={"signature": payment_sig})

    checkout_unsigned = AP2CheckoutMandate(
        mandate_id="cm_ap2_001",
        merchant_name="CloudCompute API",
        merchant_category="SOFTWARE",
        amount_minor=3900,
        currency="USD",
        item_summary="API Compute Credits",
        line_items=[{"sku": "cc-100", "qty": 1, "amount_minor": 3900}],
        idempotency_key="ap2-idem-001",
        expires_at=expires,
        signature="placeholder",
        scope="checkout",
    )
    checkout_sig = sign_hmac_sha256(
        adapter.checkout_mandate_signing_payload(checkout_unsigned),
        secret,
    )
    checkout_mandate = checkout_unsigned.model_copy(update={"signature": checkout_sig})

    proposal, quote = adapter.import_checkout_mandate(
        checkout_mandate=checkout_mandate,
        payment_mandate=payment_mandate,
    )
    assert isinstance(proposal, PurchaseProposal)
    assert isinstance(quote, QuoteSnapshot)
    assert proposal.amount_minor == 3900
    assert proposal.proposed_by_model == "ap2-mandate-importer"
    assert quote.proposal_id == proposal.id
    assert quote.quote_hash

    # Exceeding ceiling fails closed
    over_limit = checkout_unsigned.model_copy(update={"amount_minor": 15000})
    over_sig = sign_hmac_sha256(adapter.checkout_mandate_signing_payload(over_limit), secret)
    with pytest.raises(ProviderValidationError):
        adapter.import_checkout_mandate(
            checkout_mandate=over_limit.model_copy(update={"signature": over_sig}),
            payment_mandate=payment_mandate,
        )

    # Tampered signature fails closed
    with pytest.raises(ProviderSignatureError):
        adapter.verify_payment_mandate(payment_mandate.model_copy(update={"signature": "tampered-sig"}))

    # PaymentProviderAdapter order & webhook verification
    order = await adapter.create_order(
        amount_minor=3900,
        currency="USD",
        idempotency_key="ap2-order-idem-1",
        metadata={"mandate_id": "pm_ap2_001"},
    )
    assert order["status"] == "MANDATE_AUTHORIZED"

    wh_body = json.dumps({"event": "ap2.mandate.settled", "mandate_id": "pm_ap2_001"}).encode("utf-8")
    wh_sig = hmac.new(secret.encode("utf-8"), wh_body, hashlib.sha256).hexdigest()
    verified_wh = await adapter.verify_webhook(headers={"X-AP2-Signature": wh_sig}, body=wh_body)
    assert verified_wh["verified"] is True


@pytest.mark.asyncio
async def test_tap_visa_and_mastercard_provenance_and_replay_protection() -> None:
    secret = "tap-hmac-secret"
    adapter = TAPProvenanceAdapter(signing_secret=secret)
    tenant_id = uuid4()
    agent_id = uuid4()
    expires = datetime.now(UTC) + timedelta(minutes=10)

    visa_token = TAPTokenPayload(
        token_id="tap-visa-1",
        tenant_id=tenant_id,
        agent_id=agent_id,
        merchant_domain="merchant.example",
        amount_minor=2500,
        currency="USD",
        nonce="nonce-visa-0001",
        expires_at=expires,
        signature="placeholder",
    )
    visa_sig = sign_hmac_sha256(
        adapter.token_signing_payload(visa_token, network="VISA_TAP"),
        secret,
    )
    visa_token = visa_token.model_copy(update={"signature": visa_sig})

    res_visa = await adapter.verify_token_provenance(
        visa_token,
        network="VISA_TAP",
        expected_merchant_domain="merchant.example",
        expected_amount_minor=2500,
        expected_currency="USD",
    )
    assert res_visa.verified is True
    assert res_visa.network == "VISA_TAP"

    # Replaying the exact same nonce must fail closed
    with pytest.raises(ProviderSignatureError):
        await adapter.verify_token_provenance(visa_token, network="VISA_TAP")

    # Mastercard Agent Pay via remote introspection MockTransport
    def introspect_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/introspect"
        body = json.loads(request.content)
        assert body["network"] == "MASTERCARD_AGENT_PAY"
        return httpx.Response(200, json={"active": True, "scheme": "mastercard_agent_pay"})

    mc_client = httpx.AsyncClient(base_url="https://tap.mastercard.test", transport=httpx.MockTransport(introspect_handler))
    mc_adapter = TAPProvenanceAdapter(
        introspection_url="https://tap.mastercard.test",
        default_network="MASTERCARD_AGENT_PAY",
        http_client=mc_client,
    )
    mc_result = await mc_adapter.verify_token_provenance(
        {
            "network": "MASTERCARD_AGENT_PAY",
            "token_id": "mc-agent-1",
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "merchant_domain": "shop.example",
            "amount_minor": 4900,
            "currency": "USD",
            "nonce": "nonce-mc-0001",
            "expires_at": expires.isoformat(),
            "signature": "jws-compact-sig-placeholder",
        },
        expected_merchant_domain="shop.example",
    )
    assert mc_result.verified is True
    assert mc_result.network == "MASTERCARD_AGENT_PAY"
    assert mc_result.introspection_claims == {"active": True, "scheme": "mastercard_agent_pay"}
    await mc_client.aclose()


@pytest.mark.asyncio
async def test_x402_settlement_proof_verification_and_payment_required_parsing() -> None:
    def facilitator_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/verify":
            body = json.loads(request.content)
            return httpx.Response(200, json={"isValid": True, "tx_hash": body["tx_hash"]})
        if request.url.path == "/settle":
            return httpx.Response(200, json={"capture_id": "x402_cap_1", "status": "SETTLED"})
        return httpx.Response(404)

    http_client = httpx.AsyncClient(base_url="https://x402.facilitator.test", transport=httpx.MockTransport(facilitator_handler))
    adapter = X402SettlementAdapter(
        facilitator_url="https://x402.facilitator.test",
        webhook_secret="x402-wh-secret",
        http_client=http_client,
    )

    challenge = {"network": "base-sepolia", "asset": "USDC", "amount_minor": 500, "payee": "0xPayeeABC"}
    encoded_header = base64.b64encode(json.dumps(challenge).encode("utf-8")).decode("utf-8")
    parsed = adapter.parse_payment_required_header(encoded_header)
    assert parsed["network"] == "base-sepolia"
    assert parsed["amount_minor"] == 500

    proof = X402SettlementProof(
        proof_id="x402-proof-1",
        tenant_id=uuid4(),
        network="base-sepolia",
        asset="USDC",
        amount_minor=500,
        tx_hash="0x1234567890abcdef1234",
        payer_address="0xPayer111",
        payee_address="0xPayeeABC",
    )
    verified = await adapter.verify_settlement_proof(
        proof,
        expected_amount_minor=500,
        expected_network="base-sepolia",
        expected_asset="USDC",
        expected_payee="0xpayeeabc",
    )
    assert verified.verified is True
    assert verified.facilitator_receipt is not None

    with pytest.raises(ProviderValidationError):
        await adapter.verify_settlement_proof(
            proof.model_copy(update={"payer_address": "0xPayeeABC"}),
            verify_with_facilitator=False,
        )

    settled = await adapter.capture_order(order_id="x402_ord_1", idempotency_key="x402-idem-1", amount_minor=500, currency="USD")
    assert settled["status"] == "SETTLED"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_deflection_verifi_ethoca_alert_ingestion_and_acknowledgment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/alerts/verifi-alert-1/acknowledge":
            body = json.loads(request.content)
            assert body["outcome"] == "EVIDENCE_PROVIDED:PROOF_OF_DELIVERY"
            return httpx.Response(200, json={"status": "ACKNOWLEDGED"})
        return httpx.Response(404)

    http_client = httpx.AsyncClient(base_url="https://deflection.test", transport=httpx.MockTransport(handler))
    secret = "defl-wh-secret"
    adapter = DeflectionAlertAdapter(
        api_base_url="https://deflection.test",
        api_key="defl-key",
        webhook_secret=secret,
        http_client=http_client,
    )

    ethoca_res = adapter.ingest_alert(
        {
            "source": "ETHOCA",
            "ethoca_alert_id": "eth-900",
            "reason_code": "10.4_FRAUD",
            "amount": "320.00",
            "currency": "USD",
            "arn": "ARN-12345",
        },
        tenant_id=uuid4(),
    )
    assert ethoca_res.source == "ETHOCA"
    assert ethoca_res.alert.severity == "CRITICAL"
    assert ethoca_res.auto_refund_executed is False
    assert ethoca_res.requires_human_approval is True

    ack = await adapter.provide_dispute_evidence(
        dispute_id="verifi-alert-1",
        evidence_type="PROOF_OF_DELIVERY",
        notes="Tracking provided",
    )
    assert ack["acknowledged"] is True
    assert ack["status"] == "ACKNOWLEDGED"

    wh_body = json.dumps({
        "source": "VERIFI",
        "verifi_alert_id": "verifi-alert-2",
        "reason_code": "ITEM_NOT_RECEIVED",
        "amount_minor": 4500,
    }).encode("utf-8")
    wh_sig = hmac.new(secret.encode("utf-8"), wh_body, hashlib.sha256).hexdigest()
    verified = await adapter.verify_webhook(headers={"X-Verifi-Signature": wh_sig}, body=wh_body)
    assert verified["verified"] is True
    assert verified["source"] == "VERIFI"
    assert verified["auto_refund_executed"] is False
    await http_client.aclose()
