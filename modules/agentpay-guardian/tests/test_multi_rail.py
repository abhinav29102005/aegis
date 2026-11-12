"""Tests for Multi-Rail payment adapters and protocol verifiers."""

from __future__ import annotations

import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from contracts.models import (
    AP2CheckoutMandate,
    AP2PaymentMandate,
    X402SettlementProof,
)

from guardian.providers.deflection import (
    DeflectionAction,
    DeflectionHandler,
    DeflectionInquiry,
    DeflectionNetwork,
)
from guardian.providers.google_ap2 import GoogleAP2MandateVerifier
from guardian.providers.stripe import StripeProviderAdapter
from guardian.providers.token_provenance import TokenProvenanceVerifier
from guardian.providers.x402 import X402SettlementVerifier


class ImmediateAwaitable:
    """Awaitable helper that resolves synchronously without event loop sockets."""

    def __init__(self, value: Any) -> None:
        self.value = value

    def __await__(self):
        if False:
            yield
        return self.value


def run_sync(coro):
    """Run an async coroutine synchronously to completion."""
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value


class MockHttpResponse:

    def __init__(self, status_code: int, json_data: dict[str, Any]) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = str(json_data)

    def json(self) -> dict[str, Any]:
        return self._json_data


class MockHttpClient:

    def request(self, method: str, url: str, **kwargs: Any):
        if method.upper() == "POST":
            return self.post(url, **kwargs)
        return self.get(url, **kwargs)

    def post(self, url: str, data: dict[str, Any] | None = None, **kwargs: Any):
        if "capture" in url:
            return ImmediateAwaitable(
                MockHttpResponse(200, {"id": "pi_123", "status": "succeeded", "charges": {"data": [{"id": "ch_123"}]}})
            )
        if "cancel" in url:
            return ImmediateAwaitable(MockHttpResponse(200, {"id": "pi_123", "status": "canceled"}))
        if "/refunds" in url:
            return ImmediateAwaitable(MockHttpResponse(200, {"id": "re_123", "status": "succeeded", "amount": 5000}))
        return ImmediateAwaitable(
            MockHttpResponse(200, {"id": "pi_123", "status": "requires_capture", "client_secret": "sec_123"})
        )

    def get(self, url: str, **kwargs: Any):
        return ImmediateAwaitable(
            MockHttpResponse(200, {"id": "pi_123", "status": "requires_capture", "amount": 5000, "currency": "usd"})
        )


def test_stripe_provider_adapter_lifecycle():
    tenant_id = uuid4()
    mock_client = MockHttpClient()

    adapter = StripeProviderAdapter(
        api_key="sk_test_123",
        webhook_secret="whsec_test_secret",
        http_client=mock_client,  # type: ignore[arg-type]
    )

    # 1. Create order
    created = run_sync(
        adapter.create_order(
            amount_minor=5000,
            currency="USD",
            reference_id=str(tenant_id),
        )
    )
    assert created["order_id"] == "pi_123"
    assert created["status"] == "requires_capture"

    # 2. Get status
    status = run_sync(adapter.get_order_status(order_id="pi_123"))
    assert status["status"] == "requires_capture"
    assert status["currency"] == "USD"

    # 3. Capture order
    captured = run_sync(adapter.capture_order(order_id="pi_123", amount_minor=5000))
    assert captured["status"] == "succeeded"
    assert captured["capture_id"] == "ch_123"

    # 4. Refund
    refunded = run_sync(adapter.refund_capture(capture_id="pi_123", amount_minor=5000))
    assert refunded["status"] == "succeeded"

    # 5. Void
    voided = run_sync(adapter.void_authorization(authorization_id="pi_123"))
    assert voided["status"] == "canceled"

    # 6. Webhook verification
    payload = b'{"id":"evt_test"}'
    ts = int(time.time())
    sig_raw = f"{ts}.{payload.decode('utf-8')}"
    expected_hmac = hmac.new(b"whsec_test_secret", sig_raw.encode("utf-8"), "sha256").hexdigest()
    sig_header = f"t={ts},v1={expected_hmac}"

    assert adapter.verify_webhook_signature(payload, sig_header) is True
    assert adapter.verify_webhook_signature(payload, "t=1,v1=bad_sig") is False


def test_google_ap2_mandate_verifier():
    tenant_id = uuid4()
    agent_id = uuid4()
    merchant_id = uuid4()
    now = datetime.now(UTC)

    mandate = AP2CheckoutMandate(
        tenant_id=tenant_id,
        correlation_id=uuid4(),
        agent_id=agent_id,
        merchant_id=merchant_id,
        amount_minor=4200,
        currency="USD",
        line_items=[{"sku": "SKU-1", "amount_minor": 4200, "qty": 1}],
        signature="sig-ap2-mocked-test",
        expires_at=now + timedelta(hours=1),
    )

    valid, reason = GoogleAP2MandateVerifier.verify_checkout_mandate(mandate, "secret-key", now=now)
    assert valid is True
    assert reason is None

    # Test expired
    valid_expired, reason_expired = GoogleAP2MandateVerifier.verify_checkout_mandate(
        mandate, "secret-key", now=now + timedelta(hours=2)
    )
    assert valid_expired is False
    assert "expired" in str(reason_expired)

    # Test payment mandate
    pay_mandate = AP2PaymentMandate(
        checkout_mandate_id=mandate.mandate_id,
        tenant_id=tenant_id,
        correlation_id=mandate.correlation_id,
        payment_intent_id=uuid4(),
        amount_minor=4200,
        currency="USD",
        signature="sig-pay-mocked-test",
    )
    p_valid, p_reason = GoogleAP2MandateVerifier.verify_payment_mandate(pay_mandate, mandate, "secret-key")
    assert p_valid is True
    assert p_reason is None

    # Amount mismatch
    pay_mandate_bad = pay_mandate.model_copy(update={"amount_minor": 9999})
    bad_valid, bad_reason = GoogleAP2MandateVerifier.verify_payment_mandate(pay_mandate_bad, mandate, "secret-key")
    assert bad_valid is False
    assert "amount mismatch" in str(bad_reason).lower()


def test_token_provenance_verifier():
    tenant_id = uuid4()
    secret = "tap-secret-key-42"

    proof = TokenProvenanceVerifier.create_provenance_proof(
        tenant_id=tenant_id,
        network="VISA_TAP",
        token_reference="tok_ref_visa_98765",
        agent_fingerprint="agent-fp-xyz-001",
        device_fingerprint="device-fp-abc-999",
        secret=secret,
        assurance_level="HIGH",
    )

    valid, reason = TokenProvenanceVerifier.verify_token_provenance(proof, secret)
    assert valid is True
    assert reason is None

    # Test invalid secret
    bad_valid, bad_reason = TokenProvenanceVerifier.verify_token_provenance(proof, "wrong-secret")
    assert bad_valid is False
    assert "signature" in str(bad_reason).lower()

    # Test low assurance
    proof_low = proof.model_copy(update={"assurance_level": "LOW"})
    low_valid, low_reason = TokenProvenanceVerifier.verify_token_provenance(proof_low, secret)
    assert low_valid is False
    assert "assurance level" in str(low_reason).lower()


def test_x402_settlement_verifier():
    tenant_id = uuid4()
    recipient = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    payer = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

    proof = X402SettlementProof(
        tenant_id=tenant_id,
        correlation_id=uuid4(),
        chain_id=8453,  # Base
        transaction_hash="0x" + "a" * 64,
        token_address="0x" + "b" * 40,
        amount_units="1000000",
        payer_address=payer,
        recipient_address=recipient,
        block_number=1928374,
        settled_at=datetime.now(UTC),
    )

    valid, reason = X402SettlementVerifier.verify_settlement_proof(
        proof,
        expected_recipient=recipient,
        min_amount_units=500000,
    )
    assert valid is True
    assert reason is None

    # Test recipient mismatch
    bad_valid, bad_reason = X402SettlementVerifier.verify_settlement_proof(
        proof,
        expected_recipient="0x0000000000000000000000000000000000000000",
    )
    assert bad_valid is False
    assert "recipient address mismatch" in str(bad_reason).lower()


def test_deflection_handler():
    tenant_id = uuid4()
    now = datetime.now(UTC)

    # Fraud alert under threshold -> auto-refund
    fraud_inquiry = DeflectionInquiry(
        inquiry_id="inq-123",
        tenant_id=tenant_id,
        network=DeflectionNetwork.VISA_VERIFI,
        transaction_reference="tx-987",
        amount_minor=4500,  # $45.00
        currency="USD",
        reason_code="10.4",
        alert_timestamp=now,
        sla_expires_at=now + timedelta(hours=24),
    )
    res1 = DeflectionHandler.evaluate_inquiry(fraud_inquiry, auto_refund_limit_minor=10000, now=now)
    assert res1.action == DeflectionAction.AUTO_REFUND
    assert res1.refund_reference is not None

    # High amount fraud alert -> provide info
    large_inquiry = fraud_inquiry.model_copy(update={"amount_minor": 50000})
    res2 = DeflectionHandler.evaluate_inquiry(large_inquiry, auto_refund_limit_minor=10000, now=now)
    assert res2.action == DeflectionAction.PROVIDE_INFO

    # Expired SLA -> reject
    expired_res = DeflectionHandler.evaluate_inquiry(
        fraud_inquiry,
        now=now + timedelta(hours=48),
    )
    assert expired_res.action == DeflectionAction.REJECT
