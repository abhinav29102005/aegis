# 06 — Backend API, PostgreSQL & Background Worker Audit

**Scope:** `services/api/`, `services/worker/`, `packages/database/`

---

## 1. API Engineering Assessment (`services/api/`)

- **Versioning & Surface (`services/api/aegis_api/app.py`):** Clean `/v1/*` path versioning (`69` OpenAPI paths, `78` HTTP operations verified live via `create_app().openapi()`, plus `/health` and `/ready`). No deprecation policy or header (`Sunset`, `X-API-Version`) defined yet.
- **Correlation & Logging (`app.py:90-101`, `logging_config.py:10-34`):** Emits structured JSON logs carrying `X-Correlation-Id` (client-supplied header accepted unvalidated — should length/charset sanitize!).
- **Authentication & Authorization (`deps.py`, `auth_orgs.py`, `rate_limit.py`):**
  - **Positives:** Uniform `AuthContext` dependency on all routers in `services/api/aegis_api/routers/`; PBKDF2-SHA256 `600_000` iterations; HS256 JWT verified with `hmac.compare_digest`.
  - **Defects:**
    1. **[CRITICAL] GhostPay RBAC bypass (`app.py:152-155`):** Wired via `require_tenant_id` without checking `Permission.GHOSTPAY_READ` or `Permission.GHOSTPAY_SIMULATE`.
    2. **[HIGH] `ADMIN -> OWNER` privilege escalation & arbitrary member hijacking (`auth_orgs.py:340-400,483-523`).**
    3. **[HIGH] Env-var mismatch (`settings.py:32-52`):** `.env.example` / `docker-compose.yml` use `JWT_SECRET`, `JWT_ACCESS_TTL_MINUTES`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR`; `NexusSettings` reads `NEXUS_JWT_SECRET`, `AEGIS_SESSION_TTL_MINUTES`, `AEGIS_RATE_LIMIT_RPM`, `AEGIS_EVIDENCE_STORAGE_DIR` — silently ignoring configured `.env` values!
    4. **[HIGH] Global JWT rate-limiter bucket collision (`rate_limit.py:29-31`):** `tok:{auth[7:23]}` hashes the fixed HS256 header `eyJhbGciOiJIUzI1Ni`, locking ALL JWT users across ALL tenants into a single shared bucket (`240` rpm), while `_buckets` grows unboundedly in RAM (`REDIS_URL` unused).
    5. **[MEDIUM] Inactive principal bypass (`deps.py:113-143`, `platform_repo.py:252-262`):** `ApiKeyRow` lookup omits checking `UserRow.is_active` and `ServiceAccountRow.status`. No `/v1/auth/logout` or `jti` revocation.
- **Input Validation, Pagination, Idempotency & Errors:**
  - **Error handling gaps:** `/ready` (`app.py:149`), `TenantIsolationError` (`tenant.py:15-18`), and handlers in `webhooks.py:175`, `guardian_db.py`, `disputeos_db.py` leak `str(exc)` and victim `tenant_id` UUIDs. Furthermore, `guardian_db.py:495-575` fails to catch `PayPalTimeoutError`, `PayPalAPIError`, or `GuardianError` on `/buyer-approved`, `/capture`, `/buyer-declined`, `/reconcile` (exposing raw HTTP `500`!).
  - **Pagination gaps:** `/audit-events`, `/approvals`, `/payments`, `/worker/outbox`, `/investigations` have bounded `limit` (note `deliveries` & `outbox` lack `offset`), whereas `/orgs/members`, `/orgs/service-accounts`, `/orgs/api-keys`, `/guardian/agents`, `/guardian/merchants`, `/guardian/passports`, `/disputeos/cases`, `/webhooks/endpoints` return unbounded full lists.
  - **HTTP Idempotency:** `IdempotencyRecordRow` (`orm.py:342-355`) is **dead schema** — never read or written. Only `PaymentIntent` & `PaymentAttempt` enforce DB-level idempotency keys.
  - **PayPal Webhook Contracts (`webhooks.py:161-220`):** Verifies signature fail-closed via PayPal API, **but lacks PayPal `event.id` deduplication** and does not dispatch `CUSTOMER.DISPUTE.*` events.

---

## 2. PostgreSQL Integrity & Lifecycle (`packages/database/`)

- **Schema & Migrations (`orm.py`, `alembic/versions/`):** `27` SQLAlchemy ORM tables across `0001_initial_schema.py` and `0002_aegis_platform_extensions.py` (tested up/down/up on PG16 in CI).
  - **[LOW] Unfrozen initial migration:** `0001_initial_schema.py` runs `Base.metadata.create_all` dynamically against live `orm.py`, creating future migration drift risk if new models are added without updating `0001`.
  - **[LOW] Missing FKs:** `OutboxEventRow.tenant_id`, `IdempotencyRecordRow.tenant_id`, `WebhookDeliveryRow.outbox_event_id`, and `PaymentIntentRow`'s secondary link columns lack DB-level foreign key constraints.
- **Transaction Isolation, Locking & Concurrency:**
  - **Budget reservations (`repository.py:513-584`):** Uses atomic conditional `UPDATE ... WHERE (total_budget_minor - spent_minor - reserved_minor) >= :amt` on PG (safe row lock under `READ COMMITTED`), verified by 2-thread PG16 race test. *(Note: `THREAT_MODEL_AND_TRUST_ASSUMPTIONS.md:8` inaccurately describes this as `SELECT ... FOR UPDATE`.)*
  - **Outbox claiming (`platform_repo.py:598-599`):** Uses `WITH FOR UPDATE SKIP LOCKED` on PostgreSQL.
  - **[MEDIUM] Unprotected concurrency paths:** `append_financial_event` (`repository.py:722-735`) queries max `sequence_number` without `FOR UPDATE` (concurrent appends to the same `correlation_id` collide on `uq_financial_event_corr_seq`), and `transition_intent` (`repository.py:419-436`) does an unlocked read-check-write.
  - **Connection Pooling (`session.py:14-19`):** Uses `pool_pre_ping=True`, default SQLAlchemy queue pool (`pool_size=5, max_overflow=10`), **no explicit `pool_recycle` or `pool_timeout` or statement timeout**.
- **Audit Immutability, Retention, Backups & Recovery:**
  - **[MEDIUM] No DB-level immutability:** PostgreSQL users can execute `UPDATE`/`DELETE` on `financial_events` and `admin_audit_logs`; zero DB triggers or least-privilege DB role restrictions exist, and `admin_audit_logs` has no hash chain.
  - **[MEDIUM] Retention & Disaster Recovery Absent:** `DisputeCaseMetadataRow.retention_until` (+2555 days) is never queried or enforced; zero `pg_dump` / WAL-G / PITR scripts, zero restore drills, and zero row-level encryption / column encryption for `WebhookEndpointRow.signing_secret` (`orm.py:492`).

---

## 3. Background Worker Reliability (`services/worker/`)

| Worker Aspect | Current Implementation (`processor.py`, `main.py`, `platform_repo.py`) | Verdict & Risk |
| :--- | :--- | :--- |
| Outbox Atomicity | `append_financial_event(..., also_enqueue_outbox=True)` (`repository.py:763-776`) inserts `OutboxEventRow` in the same DB tx. | **VERIFIED IN CODE** |
| Competing Worker Outbox Claim | `claim_due_outbox_events` (`platform_repo.py:598-599`) uses `FOR UPDATE SKIP LOCKED` on PG; commits `status="PROCESSING"` (`processor.py:51`). | **VERIFIED IN CODE** |
| **Crash Recovery / Stuck Jobs** | **`PROCESSING` rows have NO `locked_at`/`lease_expires_at` and NO reaper.** Crash/OOM during HTTP POST strands rows in `PROCESSING` forever! | **MISSING (`HIGH`)** |
| **Competing Payment Reconciliation** | `list_pending_provider_attempts` (`platform_repo.py:668-679`) issues plain `SELECT` **without `SKIP LOCKED`**. Multiple workers concurrently reconcile the same payment & retry infinitely on config errors! | **BROKEN (`HIGH`)** |
| Retry / Exponential Backoff / DLQ | `mark_outbox_failed` (`platform_repo.py:616-640`): `min(300, 5 * 2**(attempts-1))`, transitions to `DEAD_LETTER` at `max_attempts=5` (no jitter). | **PARTIALLY IMPLEMENTED** |
| **DLQ Requeue Bug** | `requeue_dead_letter_outbox` (`platform_repo.py:656-666`) leaves `attempts >= 5`; next single error immediately re-dead-letters with 0 retries. | **BROKEN (`MEDIUM`)** |
| **Outbound Webhook SSRF** | `processor.py:57,92,105`: zero IP/CIDR/scheme restrictions + captures `resp.text[:250]` back to tenant API. | **MISSING (`CRITICAL`)** |
| Outbound Webhook Signature | Sends `X-AEGIS-Signature: sha256=<hex>` over sorted JSON (no timestamp `t=`, conflicting with docs `AEGIS-Signature: t=...,v1=...`). | **DRIFT (`MEDIUM`)** |
| Loop Exception Handling & Logs | `main.py:41` only catches `(OSError, RuntimeError, ValueError)` — `SQLAlchemyError` crashes daemon; uses `logging.basicConfig` instead of JSON logs; zero Prometheus metrics. | **PARTIALLY IMPLEMENTED (`MEDIUM`)** |
| Clock Skew Sensitivity | `next_retry_at <= ts` uses worker Python wall clock instead of PostgreSQL `NOW()`. | **PARTIALLY IMPLEMENTED (`LOW`)** |

