"""Tests for nexus-security primitives."""

from uuid import uuid4
import pytest

from contracts.fixtures import build_authorized_39_purchase_fixture
from security import (
    TenantIsolationError,
    assert_same_tenant,
    sign_hmac_sha256,
    verify_financial_event_chain,
    verify_hmac_sha256,
)


def test_hmac_sign_and_verify() -> None:
    secret = "test-secret-key"
    payload = {"intent_id": str(uuid4()), "amount_minor": 3900}
    sig = sign_hmac_sha256(payload, secret)
    assert verify_hmac_sha256(payload, sig, secret)
    assert not verify_hmac_sha256({"intent_id": payload["intent_id"], "amount_minor": 4000}, sig, secret)


def test_tenant_isolation_guard() -> None:
    t1 = uuid4()
    t2 = uuid4()
    assert_same_tenant(t1, t1, "payment_intent")
    with pytest.raises(TenantIsolationError):
        assert_same_tenant(t1, t2, "payment_intent")


def test_financial_event_chain_verification_and_tamper_detection() -> None:
    fx = build_authorized_39_purchase_fixture()
    ok, errors = verify_financial_event_chain(fx["events"])
    assert ok and errors == []

    # Tamper with an event payload without updating hash
    tampered = fx["events"][1].model_copy(update={"payload": {"outcome": "DENY"}})
    ok_bad, bad_errors = verify_financial_event_chain([fx["events"][0], tampered, fx["events"][2]])
    assert not ok_bad
    assert len(bad_errors) >= 1
