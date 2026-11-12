# 06 — Backend API, PostgreSQL & Background Worker Audit

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **M1 HARDENING COMPLETE & VERIFIED AGAINST PG16 + LIVE REDIS/COMPOSE; M2 ROUTERS (`guardian_db`, `disputeos_db`, `adapters`) STILL AWAIT PUSH.**  
**Scope:** `services/api/`, `services/worker/`, `packages/database/`

---

## 1. API Engineering Assessment (`services/api/`)

- **Expanded Versioned Surface (`app.py`):** Expanded from `69` paths / `78` ops to **`85` OpenAPI paths / `96` HTTP operations** across `/health`, `/ready`, `/metrics`, `/v1/auth/*`, `/v1/orgs/*`, `/v1/guardian/*`, `/v1/ghostpay/*`, `/v1/disputeos/*`, `/v1/webhooks/*`, `/v1/paypal/*`, `/v1/audit-events*`, `/v1/overview/*`, `/v1/billing/*`, and `/v1/privacy/*`.
- **Resolved in M1:**
  1. **GhostPay RBAC (`app.py`):** Router-level `require_permission(Permission.GHOSTPAY_READ)` closes anonymous/low-role GhostPay access (`test_rbac_negative_matrix.py` + `test_gateway_and_rate_limit.py` PASS). *(Method-level `GHOSTPAY_SIMULATE` inside `ghostpay/api/router.py` awaits M2.)*
  2. **`ADMIN -> OWNER` Blocked + Invite Consent (`auth_orgs.py`):** Non-`OWNER` cannot grant `OWNER` role or issue `OWNER` keys; cross-org add replaced by invitations (`POST /v1/orgs/invitations/{token}/accept`); `/register` email verification tokens & per-IP throttling; TOTP MFA + OIDC SSO exchange routes added; `limit`/`offset` pagination added on org members/keys/service accounts/overview/webhooks.
  3. **Rate Limiter (`rate_limit.py`):** Fixed HS256 prefix collision via `sha256(token)[:16]`, bounded bucket eviction, & live Redis sorted-set backend (`x-ratelimit-remaining` verified in live Compose).
  4. **Error Sanitization & Active Principals (`deps.py`, `app.py`, `tenant.py`, `webhooks.py`):** `TenantIsolationError` omits victim UUIDs, `/ready` & webhook routes sanitize exceptions, and `deps.py` enforces `UserRow.is_active` & `ServiceAccountRow.status`.
  5. **Prometheus `/metrics` & OTel (`metrics.py`, `logging_config.py`):** Live `/metrics` endpoint + trace/span ID log injection + security response headers.
  6. **Commercial & Privacy Routers (`billing.py`, `erasure.py`):** Stripe subscription plans/checkout/portal/webhooks/metering + GDPR/DPDPA export & crypto-shredding erasure routes.
- **Remaining Open Items (Awaiting M2):** `guardian_db.py:495-575` & `disputeos_db.py` still lack `PayPalTimeoutError`/`PayPalAPIError` error mapping, session detachment around outbound PayPal `await` calls, `/disputeos/cases/{id}/resolve`, and `limit`/`offset` pagination on M2 list routes. `IdempotencyRecordRow` remains unused.

---

## 2. PostgreSQL Integrity & Lifecycle (`packages/database/`)

- **Schema & Migrations:** **`37` SQLAlchemy 2.0 ORM tables** (`3` Alembic revisions: `0001`, `0002`, `0003_production_hardening_and_extensions`), verified `upgrade head && downgrade base && upgrade head` on PostgreSQL 16.
- **Resolved in M1:**
  1. **DB-Level Audit Immutability (`0003`):** Trigger `trg_aegis_prevent_financial_event_mutation` (`BEFORE UPDATE OR DELETE ON financial_events`) raises exception on tamper (verified in PG16 integration tests and `restore_verify.sh`).
  2. **Sequence Locking & Dispute Update Fixes (`repository.py`):** `append_financial_event` locks correlation sequence via `FOR UPDATE`; `save_dispute_case` & `save_evidence` persist all updatable fields cleanly; `save_passport_snapshot` & `get_passport_snapshot_for_decision` auto-record immutable passport snapshots.
  3. **M2 Bridge & Production Tables (`orm.py`, `platform_repo.py`):** `spending_passport_snapshots`, `ghostpay_traces`, `ghostpay_agent_dna_profiles`, `llm_invocation_logs`, `paypal_webhook_events`, `org_invitations`, `email_verifications`, `billing_subscriptions`, `usage_meters`, `erasure_requests` created & unit-tested.
  4. **Object Storage (`storage.py`):** Added `S3ObjectStorage` (S3/R2 + Governance/Compliance WORM Object Lock), streaming 10MB size-capped writes, and GDPR erasure/retention sweep helpers alongside `LocalObjectStorage`.
  5. **Connection Pooling (`session.py`):** Added `pool_recycle`, `pool_timeout`, & PostgreSQL statement timeouts.

---

## 3. Background Worker Reliability (`services/worker/`)

| Worker Aspect | Current Status (`498043e`) | Observed Evidence |
| :--- | :--- | :--- |
| Crash Recovery (`locked_at` / `lease_expires_at`) | **FIXED & VERIFIED (`M1`)** | `platform_repo.py` sets lease columns + auto-reclaims expired `PROCESSING` rows (`test_platform_repo.py` & `test_worker.py` PASS). |
| Multi-Worker Payment Reconciliation | **FIXED IN PG16 (`M1`)** | `list_pending_capture_attempts` uses `FOR UPDATE SKIP LOCKED` on PostgreSQL (`test_platform_repo.py`, `test_worker.py`). |
| Outbox Concurrency Note (`SQLite` vs `PG16`) | **IMPORTANT TEST FINDING (`M3` Harness)** | `tests/concurrency/test_concurrency_harness.py::test_outbox_lease_claim_concurrency` **FAILED (`60` claimed vs `20` unique)** because the test fixture hardcoded SQLite WAL instead of `AEGIS_TEST_POSTGRES_URL` (SQLite lacks `SKIP LOCKED`). |
| DLQ Requeue Reset & Backoff | **FIXED & VERIFIED (`M1`)** | `requeue_dead_letter_outbox` resets `attempts = 0`; exponential jitter backoff capped + loop resilience (`main.py`) verified. |
| Outbound Webhook SSRF + Signature | **FIXED & VERIFIED (`M1`)** | `processor.py` validates DNS/IPv4/IPv6 at delivery, disables redirects (`follow_redirects=False`), redacts errors (`HTTP <status>`), & signs `AEGIS-Signature: t=<unix>,v1=<hex>`. |
| Concurrent Dispatch & Worker Healthcheck | **FIXED & VERIFIED LIVE (`M1`)** | `asyncio.Semaphore` bounded dispatch + `python -m aegis_worker.main --healthcheck` verified live in Docker Compose (`worker_healthcheck=OK`). |
