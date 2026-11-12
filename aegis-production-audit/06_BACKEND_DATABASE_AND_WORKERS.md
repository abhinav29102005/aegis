# 06 — Backend API, PostgreSQL & Background Worker Audit

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):** **API SURFACE (`88` PATHS / `99` OPS), POSTGRESQL 16 (`37` TABLES + TRIGGERS + SNAPSHOTS/TRACES), AND HARDENED WORKER ALL INTEGRATED & VERIFIED IN PG16 TESTS AND LIVE DOCKER COMPOSE.**  
**Scope:** `services/api/`, `services/worker/`, `packages/database/`

---

## 1. API Engineering Assessment (`services/api/`)

- **Expanded Versioned Surface (`app.py`):** **`88` OpenAPI paths / `99` HTTP operations** across `/health`, `/ready`, `/metrics`, `/v1/auth/*`, `/v1/orgs/*`, `/v1/guardian/*` (including `/refund` & `/v1/guardian/mcp`), `/v1/ghostpay/*`, `/v1/disputeos/*` (including `/resolve` & artifact upload/download), `/v1/webhooks/*`, `/v1/paypal/*`, `/v1/audit-events*`, `/v1/overview/*`, `/v1/billing/*`, and `/v1/privacy/*`.
- **Resolved Across M1 + M2 Integration:**
  1. **GhostPay RBAC (`app.py` + `ghostpay/api/router.py`):** Both gateway router-mount (`Permission.GHOSTPAY_READ`) and method-level (`GHOSTPAY_READ`/`GHOSTPAY_SIMULATE`) enforced cleanly.
  2. **Guardian & DisputeOS DB Routers (`guardian_db.py`, `disputeos_db.py`):** Structured `GuardianError` / `PayPalTimeoutError` / `PayPalAPIError` error mapping, session detach before PayPal `await` (`guardian_db.py:728` `_detach_session`), `POST /payments/{id}/refund`, `POST /cases/{id}/resolve`, and `SEC-06` artifact case-ID check (`disputeos_db.py:464-477`).
  3. **DB-Backed GhostPay & Evidence Hash (`adapters.py`):** Replaced volatile RAM/naive balance logic with `spending_passport_snapshots`, `ghostpay_traces`, and `ghostpay_agent_dna_profiles`; unified canonical evidence hash (`adapters.py:761`).
  4. **Auth, Orgs, Rate Limit, Billing, Privacy, Observability (`M1`):** `ADMIN->OWNER` block + invite consent, `/register` verification/throttling, TOTP MFA & OIDC SSO, SHA-256 Redis sorted-set rate limiter (`rate_limit.py`), `/metrics` + OTel (`metrics.py`, `logging_config.py`), Stripe `/v1/billing/*`, and GDPR `/v1/privacy/*`.
- **Minor Remaining Notes:** Standalone `modules/disputeos/disputeos/api/router.py` remains an unmounted module-level adapter for isolated unit tests (`aegis_api` mounts `disputeos_db`); live external webhook certs (`PayPal` / `Stripe`) remain `NOT VERIFIED`.

---

## 2. PostgreSQL Integrity & Lifecycle (`packages/database/`)

- **Schema & Migrations:** **`37` SQLAlchemy 2.0 ORM tables** (`3` Alembic revisions: `0001_initial_schema.py`, `0002_aegis_platform_extensions.py`, `0003_production_hardening_and_extensions.py`), verified `upgrade head && downgrade base && upgrade head` on SQLite & PostgreSQL 16 + live Compose `migrate` container (`exit 0`).
- **Integrated Controls Verified on PG16:**
  1. **DB-Level Audit Immutability (`0003`):** `trg_aegis_prevent_financial_event_mutation` (`BEFORE UPDATE OR DELETE ON financial_events`) raises exception on mutation.
  2. **Sequence Locking & M2 Bridge Tables:** `append_financial_event` uses `FOR UPDATE`; `spending_passport_snapshots`, `ghostpay_traces`, `ghostpay_agent_dna_profiles`, `llm_invocation_logs`, `paypal_webhook_events`, `org_invitations`, `email_verifications`, `billing_subscriptions`, `usage_meters`, & `erasure_requests` all actively wired and tested (`90%` pytest coverage across repo).
  3. **Dual-Dialect Outbox Claim (`platform_repo.py:656-703`):** Uses `FOR UPDATE SKIP LOCKED` on PostgreSQL and atomic compare-and-set `UPDATE ... WHERE id == cid AND due_condition` (`synchronize_session=False`) on SQLite/non-PG backends — `test_outbox_lease_claim_concurrency` now passes (`3/3` in `test_concurrency_harness.py`) alongside PG16 worker tests!
  4. **Object Storage & Connection Pooling (`storage.py`, `session.py`):** Streaming 10MB cap, `S3ObjectStorage` (S3/R2 WORM), `pool_recycle`, `pool_timeout`, and PG statement timeouts.

---

## 3. Background Worker Reliability (`services/worker/`)

| Worker Aspect | Current Status (`2026-11-12` Integrated) | Verified Evidence |
| :--- | :--- | :--- |
| Crash Recovery (`locked_at` / `lease_expires_at`) | **CLOSED & VERIFIED** | Lease claim + auto-reclaim of expired `PROCESSING` rows verified in `test_platform_repo.py`, `test_worker.py`, & `test_outbox_lease_claim_concurrency`. |
| Multi-Worker Payment Reconciliation | **CLOSED & VERIFIED** | `list_pending_capture_attempts` (`SKIP LOCKED`) + `reconcile_pending` writes `PAYPAL_CAPTURE` `EvidenceRecord` cleanly (`95%` coverage on `processor.py` & `main.py`). |
| DLQ Requeue Reset & Backoff | **CLOSED & VERIFIED** | `requeue_dead_letter_outbox` resets `attempts = 0`; jittered exponential backoff + resilient poll loop (`main.py`). |
| Outbound Webhook SSRF + Signature | **CLOSED & VERIFIED** | Runtime DNS/IPv4/IPv6 check, `follow_redirects=False`, HTTP status-only redacted errors, `AEGIS-Signature: t=<unix>,v1=<hex>`. |
| Concurrent Dispatch & Worker Healthcheck | **CLOSED & VERIFIED LIVE** | `asyncio.Semaphore` bounded HTTP dispatch; `docker compose exec -T worker python -m aegis_worker.main --healthcheck` verified **`exit 0` live post-merge** (`make compose-smoke`). |
