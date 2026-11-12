"""Unit tests for API gateway hardening, rate limiter, observability, and RBAC."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from aegis_api.app import create_app
from aegis_api.logging_config import JsonFormatter, correlation_id_var
from aegis_api.metrics import configure_opentelemetry
from aegis_api.rate_limit import SlidingWindowRateLimiterMiddleware
from database import PlatformRepository, ServiceAccountRow, create_db_engine
from database.storage import ObjectStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from security import (
    NexusSettings,
    Role,
    TenantIsolationError,
    create_access_token,
    hash_password,
)


def _make_settings(
    tmp_path: Path,
    *,
    rate_limit_rpm: int = 240,
    app_env: str = "development",
    redis_url: str = "",
) -> NexusSettings:
    db_path = tmp_path / f"gw_{uuid4().hex[:8]}.db"
    evidence_dir = tmp_path / "evidence"
    if app_env in {"staging", "production"}:
        return NexusSettings(
            app_env=app_env,
            database_url=f"sqlite:///{db_path}",
            jwt_secret="prod-jwt-secret-minimum-32-chars-ok",
            signing_secret="prod-signing-secret-min-32-chars!",
            api_key="prod-strong-api-key-123456",
            evidence_storage_dir=str(evidence_dir),
            rate_limit_rpm=rate_limit_rpm,
            redis_url=redis_url,
            paypal_base_url="https://api-m.sandbox.paypal.com",
        )
    return NexusSettings(
        app_env=app_env,
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret-for-gateway-tests-32b",
        signing_secret="test-signing-secret-for-gateway-tests",
        evidence_storage_dir=str(evidence_dir),
        rate_limit_rpm=rate_limit_rpm,
        redis_url=redis_url,
    )


def test_rate_limiter_isolates_distinct_hs256_jwts_with_same_header(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, rate_limit_rpm=2)
    app = create_app(settings=settings, create_tables=True)

    with TestClient(app) as client:
        reg_a = client.post(
            "/v1/auth/register",
            json={
                "email": "rate-a@example.com",
                "password": "StrongPassword!123",
                "full_name": "Rate A",
                "organization_name": "Rate Org A",
                "organization_slug": "rate-org-a",
            },
        )
        assert reg_a.status_code == 201
        token_a = reg_a.json()["access_token"]

        reg_b = client.post(
            "/v1/auth/register",
            json={
                "email": "rate-b@example.com",
                "password": "StrongPassword!123",
                "full_name": "Rate B",
                "organization_name": "Rate Org B",
                "organization_slug": "rate-org-b",
            },
        )
        assert reg_b.status_code == 201
        token_b = reg_b.json()["access_token"]

        # Both HS256 JWTs share the exact same header prefix (eyJhbGciOiJIUzI1Ni...)
        assert token_a[:24] == token_b[:24]

        # Wait: registration already used anonymous IP bucket, not token bucket.
        # Exhaust Tenant A's token bucket (rpm=2)
        assert (
            client.get("/v1/overview/metrics", headers={"Authorization": f"Bearer {token_a}"}).status_code
            == 200
        )
        assert (
            client.get("/v1/overview/metrics", headers={"Authorization": f"Bearer {token_a}"}).status_code
            == 200
        )
        blocked_a = client.get("/v1/overview/metrics", headers={"Authorization": f"Bearer {token_a}"})
        assert blocked_a.status_code == 429

        # Tenant B must NOT be blocked when Tenant A hits 429
        ok_b = client.get("/v1/overview/metrics", headers={"Authorization": f"Bearer {token_b}"})
        assert ok_b.status_code == 200


def test_rate_limiter_isolates_api_keys_sharing_prefix() -> None:
    mini_app = FastAPI()

    @mini_app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "1"}

    mini_app.add_middleware(SlidingWindowRateLimiterMiddleware, requests_per_minute=1)

    with TestClient(mini_app) as client:
        key_a = "aegis_live_sameprefix_aaaaaaaaaaaa"
        key_b = "aegis_live_sameprefix_bbbbbbbbbbbb"
        assert key_a[:16] == key_b[:16]

        assert client.get("/ping", headers={"X-API-Key": key_a}).status_code == 200
        assert client.get("/ping", headers={"X-API-Key": key_a}).status_code == 429
        assert client.get("/ping", headers={"X-API-Key": key_b}).status_code == 200


def test_rate_limiter_in_memory_bucket_eviction_and_exempt_paths() -> None:
    mini_app = FastAPI()

    @mini_app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "1"}

    @mini_app.get("/metrics")
    def metrics_route() -> dict[str, str]:
        return {"metrics": "ok"}

    middleware = SlidingWindowRateLimiterMiddleware(mini_app, requests_per_minute=2, max_buckets=3)
    mini_app.add_middleware(
        SlidingWindowRateLimiterMiddleware,
        requests_per_minute=2,
        max_buckets=3,
    )

    # Verify direct eviction bounding on middleware instance
    for idx in range(25):
        allowed, _ = middleware._check_in_memory(f"tok:user-{idx}")
        assert allowed is True
    assert len(middleware._buckets) <= 3

    # /metrics is exempt from rate limiting
    with TestClient(mini_app) as client:
        for _ in range(5):
            assert client.get("/metrics").status_code == 200


class _FakeRedisSortedSetClient:
    """In-memory fake implementing Redis sorted set commands for rate-limiter tests."""

    def __init__(self) -> None:
        self.sets: dict[str, dict[str, float]] = {}
        self.calls: list[str] = []

    def zremrangebyscore(self, key: str, min_score: str | float, max_score: float) -> int:
        self.calls.append("ZREMRANGEBYSCORE")
        bucket = self.sets.get(key, {})
        low = float("-inf") if min_score == "-inf" else float(min_score)
        to_del = [member for member, score in bucket.items() if low <= score <= float(max_score)]
        for member in to_del:
            del bucket[member]
        return len(to_del)

    def zcard(self, key: str) -> int:
        self.calls.append("ZCARD")
        return len(self.sets.get(key, {}))

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.calls.append("ZADD")
        bucket = self.sets.setdefault(key, {})
        bucket.update(mapping)
        return len(mapping)

    def expire(self, key: str, seconds: int) -> bool:
        self.calls.append("EXPIRE")
        return key in self.sets and seconds > 0


class _BrokenRedisClient:
    def zremrangebyscore(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis connection refused")


def test_rate_limiter_redis_sorted_set_and_graceful_fallback() -> None:
    fake_redis = _FakeRedisSortedSetClient()
    app_redis = FastAPI()

    @app_redis.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "1"}

    app_redis.add_middleware(
        SlidingWindowRateLimiterMiddleware,
        requests_per_minute=2,
        redis_client=fake_redis,
    )

    with TestClient(app_redis) as client:
        headers = {"Authorization": "Bearer token-redis-1"}
        r1 = client.get("/ping", headers=headers)
        r2 = client.get("/ping", headers=headers)
        r3 = client.get("/ping", headers=headers)
        assert r1.status_code == 200
        assert r1.headers["X-RateLimit-Remaining"] == "1"
        assert r2.status_code == 200
        assert r2.headers["X-RateLimit-Remaining"] == "0"
        assert r3.status_code == 429
        assert {"ZREMRANGEBYSCORE", "ZCARD", "ZADD", "EXPIRE"}.issubset(set(fake_redis.calls))

    # Broken Redis must gracefully fall back to in-memory sliding window
    app_fallback = FastAPI()

    @app_fallback.get("/ping")
    def ping_fb() -> dict[str, str]:
        return {"ok": "1"}

    app_fallback.add_middleware(
        SlidingWindowRateLimiterMiddleware,
        requests_per_minute=1,
        redis_client=_BrokenRedisClient(),
    )

    with TestClient(app_fallback) as client:
        assert client.get("/ping", headers={"X-API-Key": "fallback-key"}).status_code == 200
        assert client.get("/ping", headers={"X-API-Key": "fallback-key"}).status_code == 429


def test_api_key_rejects_inactive_user_membership_and_service_account(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    app = create_app(settings=settings, create_tables=True)

    with app.state.session_factory() as session:
        platform = PlatformRepository(session)
        org = platform.create_organization(name="Sec Org", slug="sec-org")
        user = platform.create_user(
            email="keyuser@example.com",
            full_name="Key User",
            password_hash=hash_password("StrongPass!123", iterations=10_000),
        )
        membership = platform.add_membership(tenant_id=org.id, user_id=user.id, role=Role.OPERATOR)
        _, user_api_key = platform.create_api_key(
            tenant_id=org.id,
            name="user-key",
            pepper=settings.signing_secret,
            user_id=user.id,
            role=Role.OPERATOR,
        )

        sa = platform.create_service_account(
            tenant_id=org.id,
            name="bot-acct",
            role=Role.AGENT_SERVICE,
        )
        _, sa_api_key = platform.create_api_key(
            tenant_id=org.id,
            name="sa-key",
            pepper=settings.signing_secret,
            service_account_id=sa.id,
            role=Role.AGENT_SERVICE,
        )
        user_id = user.id
        membership_id = membership.id
        sa_id = sa.id
        session.commit()

    with TestClient(app) as client:
        # Both keys work while active
        assert client.get("/v1/guardian/agents", headers={"X-API-Key": user_api_key}).status_code == 200
        assert client.get("/v1/guardian/agents", headers={"X-API-Key": sa_api_key}).status_code == 200

        # Suspend membership -> user API key rejected 401
        with app.state.session_factory() as session:
            m = session.get(type(membership), membership_id)
            assert m is not None
            m.status = "SUSPENDED"
            session.commit()
        resp_m = client.get("/v1/guardian/agents", headers={"X-API-Key": user_api_key})
        assert resp_m.status_code == 401
        assert resp_m.json()["detail"]["error_code"] == "MEMBERSHIP_INACTIVE"

        # Restore membership, deactivate user -> user API key rejected 401 USER_INACTIVE
        with app.state.session_factory() as session:
            m = session.get(type(membership), membership_id)
            u = session.get(type(user), user_id)
            assert m is not None and u is not None
            m.status = "ACTIVE"
            u.is_active = False
            session.commit()
        resp_u = client.get("/v1/guardian/agents", headers={"X-API-Key": user_api_key})
        assert resp_u.status_code == 401
        assert resp_u.json()["detail"]["error_code"] == "USER_INACTIVE"

        # Suspend service account -> service account API key rejected 401 SERVICE_ACCOUNT_INACTIVE
        with app.state.session_factory() as session:
            sa_row = session.get(ServiceAccountRow, sa_id)
            assert sa_row is not None
            sa_row.status = "SUSPENDED"
            session.commit()
        resp_sa = client.get("/v1/guardian/agents", headers={"X-API-Key": sa_api_key})
        assert resp_sa.status_code == 401
        assert resp_sa.json()["detail"]["error_code"] == "SERVICE_ACCOUNT_INACTIVE"


def test_error_sanitization_ready_500_and_tenant_isolation(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    app = create_app(settings=settings, create_tables=True)
    victim_tenant = uuid4()

    @app.get("/_test/tenant-leak")
    def trigger_tenant_error() -> None:
        raise TenantIsolationError(
            f"denied access to {victim_tenant}",
            resource=f"payment_intent {victim_tenant}",
            expected_tenant_id=victim_tenant,
            actual_tenant_id=uuid4(),
        )

    @app.get("/_test/boom")
    def trigger_boom() -> None:
        raise RuntimeError("secret-db-dsn=postgresql://admin:topsecret@internal:5432/db")

    # 1. /ready DB failure must not leak raw str(exc)
    bad_engine = create_db_engine(settings.database_url)
    app_bad_db = create_app(settings=settings, engine=bad_engine, create_tables=True)

    def _failing_connect() -> Any:
        raise RuntimeError("FATAL: password authentication failed for user secret_pg_user")

    with TestClient(app_bad_db) as bad_client:
        bad_engine.connect = _failing_connect  # type: ignore[method-assign]
        ready_resp = bad_client.get("/ready")
        assert ready_resp.status_code == 503
        body = ready_resp.json()
        assert body["detail"]["error_code"] == "DB_UNAVAILABLE"
        assert body["detail"]["message"] == "Database readiness check failed."
        assert "secret_pg_user" not in ready_resp.text
        assert "FATAL" not in ready_resp.text
    bad_engine.dispose()

    with TestClient(app, raise_server_exceptions=False) as client:
        # 2. TenantIsolationError never leaks victim tenant UUID
        iso_resp = client.get("/_test/tenant-leak")
        assert iso_resp.status_code == 403
        assert iso_resp.json()["error_code"] == "TENANT_ISOLATION_VIOLATION"
        assert str(victim_tenant) not in iso_resp.text

        # 3. Unhandled 500 never leaks raw exception message
        boom_resp = client.get("/_test/boom")
        assert boom_resp.status_code == 500
        assert boom_resp.json()["error_code"] == "INTERNAL_SERVER_ERROR"
        assert "topsecret" not in boom_resp.text
        assert "secret-db-dsn" not in boom_resp.text


def test_security_headers_metrics_and_repeated_create_app(tmp_path: Path) -> None:
    dev_settings = _make_settings(tmp_path, app_env="development")
    prod_settings = _make_settings(tmp_path, app_env="production")

    app1 = create_app(settings=dev_settings, create_tables=True)
    app2 = create_app(settings=prod_settings, create_tables=True)
    assert isinstance(app1.state.object_storage, ObjectStorage)
    assert configure_opentelemetry(app1, settings=dev_settings, enabled=True) is True
    assert configure_opentelemetry(app2, settings=prod_settings, enabled=True) is True

    with TestClient(app1) as dev_client:
        health_resp = dev_client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.headers["X-Content-Type-Options"] == "nosniff"
        assert health_resp.headers["X-Frame-Options"] == "DENY"
        assert health_resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert health_resp.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
        assert "Strict-Transport-Security" not in health_resp.headers

        metrics_resp = dev_client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "text/plain; version=0.0.4" in metrics_resp.headers["content-type"]
        assert "aegis_http_requests_total" in metrics_resp.text
        assert "aegis_http_request_duration_seconds" in metrics_resp.text

    with TestClient(app2) as prod_client:
        prod_health = prod_client.get("/health")
        assert prod_health.status_code == 200
        assert "max-age=" in prod_health.headers["Strict-Transport-Security"]


def test_json_formatter_injects_otel_trace_and_span_ids() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer("aegis.test")
    formatter = JsonFormatter()
    token = correlation_id_var.set("corr-otel-123")
    try:
        with tracer.start_as_current_span("test-span") as span:
            ctx = span.get_span_context()
            record = logging.LogRecord(
                name="aegis.test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="hello structured log",
                args=(),
                exc_info=None,
            )
            formatted = json.loads(formatter.format(record))
            assert formatted["correlation_id"] == "corr-otel-123"
            assert formatted["trace_id"] == format(ctx.trace_id, "032x")
            assert formatted["span_id"] == format(ctx.span_id, "016x")
    finally:
        correlation_id_var.reset(token)


def test_ghostpay_rbac_blocks_unauthenticated_and_agent_service(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    app = create_app(settings=settings, create_tables=True)

    with app.state.session_factory() as session:
        platform = PlatformRepository(session)
        org = platform.create_organization(name="Ghost Org", slug="ghost-org")
        owner = platform.create_user(
            email="ghost-owner@example.com",
            full_name="Ghost Owner",
            password_hash=hash_password("StrongPass!123", iterations=10_000),
        )
        platform.add_membership(tenant_id=org.id, user_id=owner.id, role=Role.OWNER)
        sa = platform.create_service_account(
            tenant_id=org.id,
            name="agent-svc",
            role=Role.AGENT_SERVICE,
        )
        _, agent_key = platform.create_api_key(
            tenant_id=org.id,
            name="agent-key",
            pepper=settings.signing_secret,
            service_account_id=sa.id,
            role=Role.AGENT_SERVICE,
        )
        owner_token = create_access_token(
            user_id=owner.id,
            tenant_id=org.id,
            role=Role.OWNER,
            secret=settings.jwt_secret,
            email=owner.email,
        )
        session.commit()

    with TestClient(app) as client:
        # Unauthenticated caller -> 401
        assert client.get("/v1/ghostpay/investigations").status_code == 401

        # AGENT_SERVICE lacks ghostpay:read -> 403
        denied = client.get("/v1/ghostpay/investigations", headers={"X-API-Key": agent_key})
        assert denied.status_code == 403
        assert denied.json()["error_code"] == "PERMISSION_DENIED"

        # OWNER has ghostpay:read -> 200
        allowed = client.get(
            "/v1/ghostpay/investigations",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert allowed.status_code == 200
