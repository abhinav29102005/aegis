# 19 — Three-Computer Parallel Execution Plan & Copy-Pasteable Master Prompts

**Baseline Commit:** `integration/nexus` @ `1be376e` (`main` untouched at `0108f84`)  
**Total Scope:** **ALL** identified production-readiness gaps (`GAP-001` through `GAP-026` + Horizons 1–5) — no gaps omitted.  
**Team Split:** 3 Engineers on 3 Separate Computers running **simultaneously**, each coordinating **8 specialized subagents** with strictly disjoint file ownership.

---

## 1. Cross-Computer Disjoint File Ownership Matrix (Zero Merge Conflicts)

| Write Scope (Paths) | Machine 1 (`work/m1-platform-security-infra`) | Machine 2 (`work/m2-financial-forensics-ai`) | Machine 3 (`work/m3-web-sdks-qa`) |
| :--- | :--- | :--- | :--- |
| `packages/security/**` | **OWNER** | Forbidden | Forbidden |
| `packages/database/**` | **OWNER** | Forbidden | Forbidden |
| `services/worker/**` | **OWNER** | Forbidden | Forbidden |
| `services/api/aegis_api/{app.py,deps.py,rate_limit.py,logging_config.py,metrics.py}` | **OWNER** | Forbidden | Forbidden |
| `services/api/aegis_api/routers/{auth_orgs,overview,webhooks,billing,erasure}.py` | **OWNER** | Forbidden | Forbidden |
| `services/*/Dockerfile`, `docker-compose.yml`, `.env.example`, `.github/**`, `Makefile`, `pyproject.toml`, `uv.lock`, `deploy/**`, `scripts/**` | **OWNER** | Forbidden | Forbidden |
| `packages/contracts/**` | Forbidden | **OWNER** | Forbidden |
| `packages/paypal/**` | Forbidden | **OWNER** | Forbidden |
| `modules/agentpay-guardian/**` | Forbidden | **OWNER** | Forbidden |
| `modules/ghostpay/**` | Forbidden | **OWNER** | Forbidden |
| `modules/disputeos/**` | Forbidden | **OWNER** | Forbidden |
| `services/api/aegis_api/adapters.py`, `routers/{guardian_db,disputeos_db}.py` | Forbidden | **OWNER** | Forbidden |
| `apps/web/**` | Forbidden | Forbidden | **OWNER** |
| `packages/sdk-python/**` | Forbidden | Forbidden | **OWNER** |
| `packages/sdk-typescript/**` | Forbidden | Forbidden | **OWNER** |
| `docs/**`, `README.md`, `packages/ui/` | Forbidden | Forbidden | **OWNER** |
| `tests/{adversarial,concurrency,e2e,integration}/**` | Forbidden *(own `packages/{security,database}/tests` & `services/*/tests`)* | Forbidden *(own `packages/{contracts,paypal}/tests` & `modules/*/tests`)* | **OWNER** *(+ `apps/web/tests/`)* |

---

## 2. Frozen Day-0 Interface Contract (Shared Across All 3 Computers)

Every computer codes directly against these frozen names and signatures so all three branches compile and merge without interface drift:

1. **Canonical Roles (`6` exact strings in `packages/security/security/auth.py`):**
   `OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`.
   *(Remove `DEVELOPER`, `AGENT_RUNTIME`, `FINANCE_ADMIN`, `RISK_ANALYST`, `DISPUTE_OPERATOR` everywhere.)*
2. **Canonical Permissions:**
   - Merchant/Passport management uses `"passports:write"` (never `"merchants:write"`).
   - GhostPay uses `Permission.GHOSTPAY_READ` (`"ghostpay:read"`) and `Permission.GHOSTPAY_SIMULATE` (`"ghostpay:simulate"`).
3. **Canonical `PaymentState` (`11` states):**
   `CREATED`, `POLICY_CHECK`, `AWAITING_APPROVAL`, `APPROVED`, `CHECKOUT_CREATED`, `CAPTURE_PENDING`, `CAPTURED`, `FAILED`, `CANCELLED`, `EXPIRED`, `REFUNDED` (plus optional `PARTIALLY_REFUNDED`).
   *(Capture action is ONLY valid/enabled in `CAPTURE_PENDING`. Approval endpoint `POST /v1/guardian/payments/{intent_id}/approve` accepts `{"approved": bool, "approver_id": str | null, "comment": str | null}`.)*
4. **Canonical `DisputeStatus` (`6` states, strictly forward monotonic):**
   `OPEN -> UNDER_INVESTIGATION -> DRAFT_READY -> APPROVED_FOR_SUBMISSION -> SUBMITTED -> RESOLVED` (with `APPROVED_FOR_SUBMISSION` allowed to transition forward to `SUBMITTED` **only** after HTTP 2xx PSP submission; `POST /v1/disputeos/cases/{case_id}/resolve` transitions to `RESOLVED`).
5. **Canonical API Payload Field Names:**
   - `DisputeAnalysis`: `grounded_summary`, `generated_with_llm`, `citations`, `contradictions: list[str]`, `missing_evidence: list[str]`, `recommended_actions: list[str]`, `llm_provider`, `llm_model`.
   - `DisputeCase`: includes `response_due_by: datetime | null`, `resolved_at: datetime | null`, `resolution_outcome: str | null`, `external_status: str | null`.
   - `ReplayTimelineEntry`: `occurred_at`, `actor_type`, `actor_id`, `event_type`, `sequence_number`, `event_hash`, `previous_event_hash`.
   - `PaymentAttempt` / `Approval`: `attempt.state`, `attempt.verified_capture.paypal_capture_id`, `attempt.paypal_approval_url`, `approval.decided_at`.
   - List endpoints across Guardian, GhostPay, DisputeOS, Audit, Auth/Orgs, Webhooks support `limit: int = 50` and `offset: int = 0` returning pagination metadata (`items`/`total`/`limit`/`offset` or preserving list body with `X-Total-Count` + query params — keep backward-compatible list/envelope per existing route and document consistently in OpenAPI).
6. **Canonical Env Vars (`NexusSettings` supports both legacy `.env.example` names and `AEGIS_`/`NEXUS_` aliases):**
   `JWT_SECRET` (`NEXUS_JWT_SECRET`), `JWT_ACCESS_TTL_MINUTES` (`AEGIS_SESSION_TTL_MINUTES`), `RATE_LIMIT_RPM` (`AEGIS_RATE_LIMIT_RPM`), `EVIDENCE_STORAGE_DIR` (`AEGIS_EVIDENCE_STORAGE_DIR`), `AEGIS_STORAGE_BACKEND` (`local|s3`), `AEGIS_S3_BUCKET`, `AEGIS_S3_ENDPOINT_URL`, `REDIS_URL`, `LLM_PROVIDER`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `WEBHOOK_LEGACY_SIGNATURE_FALLBACK`.
7. **Canonical Webhook Signature Format (`GAP-014`):**
   - Header: `AEGIS-Signature: t=<unix_seconds>,v1=<hex_hmac_sha256>`
   - Signed message: `f"{timestamp}.{raw_body_utf8}"` with SHA-256 HMAC and `300`s replay window.
8. **Cross-Module Hooks (Computer 1 <-> Computer 2):**
   - `LedgerRepository` / `PlatformRepository` (Computer 1 implements; Computer 2 uses defensively via `getattr`/Protocol):
     - `save_passport_snapshot(tenant_id, passport_id, version, policy_version, snapshot_json, created_by)` & `get_passport_snapshot_for_decision(tenant_id, decision_id)`
     - `save_ghostpay_trace(tenant_id, trace_id, agent_id, payload_json, recorded_decision_json)` & `list_ghostpay_traces(tenant_id, agent_id=None, limit=50, offset=0)` & `get_ghostpay_trace(tenant_id, trace_id)`
     - `save_agent_dna_profile(tenant_id, agent_id, profile_json)` & `get_agent_dna_profile(tenant_id, agent_id)`
     - `log_llm_invocation(tenant_id, correlation_id, module, provider, model, prompt_tokens, completion_tokens, estimated_cost_usd_micros)`
   - PayPal dispute webhook hook (Computer 2 implements; Computer 1 calls lazily inside `webhooks.py`):
     - `disputeos.paypal.webhook_handler.handle_paypal_dispute_webhook(repo, event_type, resource, event_id) -> dict[str, Any]`
9. **Web BFF Cookie Auth (`apps/web/src/app/api/*`):**
   - Next.js sets `HttpOnly; SameSite=Lax; Path=/` cookie `aegis_session` via `/api/auth/*` and forwards `Authorization: Bearer <jwt>` via `/api/proxy/[...path]`, removing `localStorage` JWTs with zero FastAPI auth coupling.

---

## 3. Master Prompt — COMPUTER 1 (Platform, Security, Database, Worker, Infra & Commercial Backend)

```markdown
# AEGIS PRODUCTION LAUNCH — COMPUTER 1 MASTER EXECUTION PROMPT
## Role: Platform, Security, Database, Worker, Infra & Commercial Backend Lead (8 Subagents)

You are running on **Computer 1** in `/home/bigboyaks/Projects/agentpay-nexus`.
Machines 2 and 3 are working **simultaneously** on other branches (`work/m2-financial-forensics-ai`, `work/m3-web-sdks-qa`).
Your job is to resolve ALL Platform, Security, Database, Worker, Infrastructure, CI, Billing, and GDPR/DPDPA gaps cleanly with **ZERO merge conflicts** against Machines 2 and 3.

### Git & Safety Rules (NON-NEGOTIABLE)
1. Start from `integration/nexus` (`1be376e`):
   `git fetch origin && git checkout -b work/m1-platform-security-infra integration/nexus`
   Never edit `main`, never force-push, never commit secrets.
2. **STRICT WRITE BOUNDARY — Edit ONLY these paths:**
   - `packages/security/**`
   - `packages/database/**`
   - `services/worker/**`
   - `services/api/aegis_api/{app.py,deps.py,rate_limit.py,logging_config.py,metrics.py}`
   - `services/api/aegis_api/routers/{auth_orgs.py,overview.py,webhooks.py,billing.py,erasure.py}`
   - `services/api/Dockerfile`, `services/worker/Dockerfile`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`, `Makefile`, `pyproject.toml`, `uv.lock`, `deploy/**`, `scripts/**`
   - Tests in `packages/security/tests/**`, `packages/database/tests/**`, `services/api/tests/**`, `services/worker/tests/**`
   **NEVER edit:** `packages/contracts/`, `packages/paypal/`, `modules/`, `services/api/aegis_api/adapters.py`, `services/api/aegis_api/routers/{guardian_db,disputeos_db}.py`, `apps/web/`, `packages/sdk-*`, `docs/`, `tests/{adversarial,concurrency,e2e,integration}/`.
3. Follow `AGENTS.md`: never bypass deterministic controls with LLMs, never fabricate tests/evidence, report unrun external checks as `NOT VERIFIED`.
4. **Important:** You own root `pyproject.toml` and `uv.lock`. Add any needed dependencies (`pytest-cov`, `pip-audit`, `redis`, `boto3`, `prometheus-client`, `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`) cleanly here so CI and all 3 machines benefit. Note: Machine 2 uses `httpx` REST adapters for LLMs/Stripe so Machine 2 needs no `pyproject.toml` edits.

### Exact Gaps Owned by Computer 1
- `GAP-002` (API gateway RBAC for GhostPay routes in `app.py`)
- `GAP-003` (Outbound webhook SSRF validation + response body redaction in `webhooks.py` & `processor.py`)
- `GAP-006` (`NexusSettings` env-var alignment + production security posture validation)
- `GAP-007` (Rate limiter JWT `sha256` bucket fix, bounded eviction, Redis backend)
- `GAP-008` (Block `ADMIN -> OWNER` escalation, invite consent token flow, `/register` verification & abuse throttling)
- `GAP-010` (Outbox `locked_at` lease/reaper, `FOR UPDATE SKIP LOCKED` reconciliation, retry cap/backoff, DLQ `attempts=0` reset, worker resilience)
- `GAP-014` (Worker webhook signing in `AEGIS-Signature: t=<unix>,v1=<hex>` format + transition compat flag)
- `GAP-017` (Webhook router hook dispatching PayPal `CUSTOMER.DISPUTE.*` events idempotently to `disputeos.paypal.webhook_handler`)
- `GAP-018` (Sanitize `TenantIsolationError` victim UUID leak, `/ready` & webhook `str(exc)` leakage, enforce `UserRow.is_active` & `ServiceAccountRow.status`, MFA/OIDC/KMS envelope foundations)
- `GAP-020` (PG `financial_events` `BEFORE UPDATE OR DELETE` immutability triggers, `FOR UPDATE` sequence allocation, Alembic additive migrations for all M1+M2 schema needs, fix `save_dispute_case`/`save_evidence` dropped fields, `pg_dump`/PITR scripts)
- `GAP-021` (Non-root Dockerfiles with pinned digests + worker healthcheck, close `0.0.0.0:5432` host bind, Prometheus `/metrics` + OTel + Grafana alerts, Compose CI smoke test, Linux VPS / Managed PG deploy manifests retiring Android staging)
- `GAP-022` (S3/R2 + WORM Object Lock storage backend alongside `LocalObjectStorage`, streaming size-checked uploads, bounded worker HTTP semaphore, `limit`/`offset` pagination on `auth_orgs`/`webhooks`/`overview`)
- `GAP-023` (GitHub Action SHA pinning, `pytest-cov`, `pip-audit`, `gitleaks`, `trivy`, multi-region/residency config profiles)
- `GAP-024` (Stripe SaaS Billing, metering, plan quotas, GDPR/DPDPA crypto-shredding erasure & data export endpoints)

### Launch 8 Parallel Subagents (Coordinate in Parallel Waves — Zero Same-File Edits)

Spawn **8 subagents** using `invoke_subagent` with `EnableWriteTools=true` (keep Subagent 8 strictly read-only + test execution until implementation subagents finish, then run cross-check):

1. **Subagent 1 — Security, Crypto, SSRF & Erasure Architect**
   - Own: `packages/security/security/{settings.py,auth.py,tenant.py,hashing.py,ssrf.py,kms.py,erasure.py}`, `packages/security/tests/**`
   - Tasks:
     - `settings.py`: Map `.env.example`/`docker-compose.yml` names (`JWT_SECRET`, `JWT_ACCESS_TTL_MINUTES`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR`, `REDIS_URL`, `AEGIS_STORAGE_BACKEND`, `AEGIS_S3_BUCKET`, `AEGIS_S3_ENDPOINT_URL`, `AEGIS_S3_REGION`, `LLM_PROVIDER`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `WEBHOOK_LEGACY_SIGNATURE_FALLBACK`, data-residency zone) alongside `NEXUS_`/`AEGIS_` aliases. Update `validate_security_posture()` to forbid insecure `api_key`, `jwt_secret == signing_secret`, weak DB passwords (`"aegis"`), and wildcard CORS `"*"` in `staging`/`production`.
     - `auth.py`: Enforce exact 6 `Role` values (`OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`), add `Permission.GHOSTPAY_READ` (`"ghostpay:read"`), `Permission.GHOSTPAY_SIMULATE` (`"ghostpay:simulate"`), `Permission.BILLING_MANAGE`, `Permission.PRIVACY_MANAGE`, add helper rejecting `ADMIN -> OWNER` assignment, TOTP MFA secret/verify helper & OIDC claim verification helper.
     - `tenant.py`: Stop echoing foreign `tenant_id` UUID in `TenantIsolationError` HTTP error details; log internally only.
     - `ssrf.py`: Strict URL & DNS resolution validator blocking `http://` in production, private/loopback/link-local/reserved/multicast/CGNAT IPv4 & IPv6 addresses (`127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254.169.254`, `::1`, `fc00::/7`, `fe80::/10`), and unsafe schemes.
     - `hashing.py`, `kms.py`, `erasure.py`: Webhook signing `AEGIS-Signature: t=<unix>,v1=<hex>` generator & verifier (300s tolerance), envelope KMS key-wrapping interface (local AES-GCM / AWS KMS compatible), and PII crypto-shredding helpers.

2. **Subagent 2 — Database Schema, PG Triggers & Repositories Engineer**
   - Own: `packages/database/database/{orm.py,alembic/**,repository.py,platform_repo.py,session.py}`, `packages/database/tests/**`
   - Tasks:
     - Keep `0001` untouched (`GAP-020`). Create additive Alembic revision(s) (`0002_*`, `0003_*`) for:
       1. `financial_events`: PostgreSQL trigger `BEFORE UPDATE OR DELETE ON financial_events FOR EACH ROW` raising exception on mutation.
       2. `outbox_events`: `locked_at`, `lease_expires_at`, `locked_by` columns + index.
       3. `spending_passport_snapshots`: immutable snapshot table `(id, tenant_id, passport_id, version, policy_version, snapshot_json, created_at, created_by)` + nullable `passport_snapshot_id` on `authorization_decisions`.
       4. `dispute_cases`: `response_due_by`, `resolved_at`, `resolution_outcome`, `external_status`.
       5. `ghostpay_traces` (unique `(tenant_id, trace_id)`), `ghostpay_agent_dna_profiles` (unique `(tenant_id, agent_id)`), `llm_invocation_logs`.
       6. `paypal_webhook_events` (unique `event_id` idempotent deduplication), `org_invitations`, `email_verifications`, `billing_subscriptions`, `usage_meters`, `erasure_requests`.
     - `repository.py`: Lock next `sequence_number` in `append_financial_event` with `SELECT ... FOR UPDATE`; fix `save_dispute_case` and `save_evidence` so updates persist `paypal_dispute_id`, `reason`, `buyer_claim`, `amount_minor`, `is_synthetic`, `source_type`, `response_due_by`, `resolved_at`, `resolution_outcome`, `external_status`; implement `save_passport_snapshot` & `get_passport_snapshot_for_decision` (and auto-record immutable snapshot whenever passports are created/updated/revoked).
     - `platform_repo.py`: Reclaim expired `PROCESSING` outbox leases (`lease_expires_at < now`); reset `attempts = 0` on `requeue_dead_letter_outbox`; use `FOR UPDATE SKIP LOCKED` in `list_pending_capture_attempts` / reconciliation queries; implement `save_ghostpay_trace`, `list_ghostpay_traces`, `get_ghostpay_trace`, `save_agent_dna_profile`, `get_agent_dna_profile`, `log_llm_invocation`, `record_paypal_webhook_once`, billing/usage/erasure/invitation repo methods.

3. **Subagent 3 — Storage Backend & PITR Backup Engineer**
   - Own: `packages/database/database/storage.py`, `scripts/backup_pitr.sh`, `scripts/restore_verify.sh`, storage tests in `packages/database/tests/test_storage.py`
   - Tasks:
     - Implement `ObjectStorage` protocol + `LocalObjectStorage` (preserving SHA-256 verification) + `S3ObjectStorage` (S3/R2 compatible with optional Object Lock WORM retention mode for audit exports) selected via settings.
     - Add streaming size-capped write support (`max_bytes=10*1024*1024`) so oversized uploads do not buffer unbounded memory; add deletion/retention sweep hooks for GDPR/DPDPA erasure (`hold` vs `expired`).
     - Write automated `pg_dump` + WAL/PITR backup script & automated restore-to-ephemeral-DB verification script (`scripts/backup_pitr.sh`, `scripts/restore_verify.sh`).

4. **Subagent 4 — API Gateway, Rate Limiter & Observability Engineer**
   - Own: `services/api/aegis_api/{app.py,deps.py,rate_limit.py,logging_config.py,metrics.py}`, API gateway tests
   - Tasks:
     - `app.py`: Wire GhostPay router dependency to enforce `Permission.GHOSTPAY_READ` (`GAP-002`); sanitize `/ready` & unhandled errors (never expose `str(exc)`); mount `/v1/billing`, `/v1/erasure`, and `/metrics`; wire OpenTelemetry + security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
     - `deps.py`: Enforce `UserRow.is_active` AND `ServiceAccountRow.status == "ACTIVE"` AND org membership active status on every JWT and API key lookup (`GAP-018`).
     - `rate_limit.py`: Hash full Bearer token (`sha256(tok)[:16]`), add bounded bucket TTL eviction (`MAX_BUCKETS` / periodic sweep), and implement Redis sliding-window rate limiter backend when `REDIS_URL` is configured (`GAP-007`).
     - `metrics.py` & `logging_config.py`: Prometheus counters/histograms (requests, latency, policy denies, PayPal calls, worker outbox depth/DLQ, LLM tokens/cost) + trace/correlation ID log injection.

5. **Subagent 5 — Orgs, Invitations, SSO/MFA, Billing & Privacy Endpoints Engineer**
   - Own: `services/api/aegis_api/routers/{auth_orgs.py,overview.py,billing.py,erasure.py}`, router tests
   - Tasks:
     - `auth_orgs.py`: Forbid non-`OWNER` users from assigning `OWNER` role to members, invitations, or API keys (`403`, `GAP-008`). Replace silent cross-org user attachment with secure invitation creation + explicit user acceptance flow (`POST /v1/orgs/invitations/{token}/accept`). Add email verification tokens + per-IP anti-abuse throttling on `/v1/auth/register` (`GAP-023`). Add TOTP MFA setup/verify + OIDC SSO exchange endpoints (`Horizon 4`). Add `limit`/`offset` pagination to org members/keys/service accounts lists (`GAP-022`).
     - `billing.py`: Stripe SaaS billing plans (`FREE`, `PRO`, `ENTERPRISE`), checkout/portal session links (via `httpx` Stripe API), metering counters, quota enforcement dependency, Stripe billing webhook handler (`GAP-024`).
     - `erasure.py`: GDPR/DPDPA data export (`GET /v1/privacy/export`) & right-to-erasure request + crypto-shredding execution (`POST /v1/privacy/erasure-requests`, `GAP-024`).
     - `overview.py`: Add audit/dispute deadline & LLM usage summary metrics + clean pagination on audit list (`GAP-022`).

6. **Subagent 6 — Webhooks & Worker Reliability Engineer**
   - Own: `services/api/aegis_api/routers/webhooks.py`, `services/worker/aegis_worker/{processor.py,main.py}`, `services/worker/tests/**`
   - Tasks:
     - `webhooks.py`: Enforce `ssrf.validate_webhook_url` on webhook registration & update; mask secrets; add `limit`/`offset` pagination on webhook endpoints/deliveries; in `/v1/paypal/webhook` deduplicate via `record_paypal_webhook_once`, sanitize HTTP error messages (`no str(exc)`), and dispatch `CUSTOMER.DISPUTE.*` events cleanly to `disputeos.paypal.webhook_handler.handle_paypal_dispute_webhook` (with graceful `ImportError` guard until Machine 2 merges).
     - `processor.py` & `main.py`: Re-validate SSRF + resolved IP at HTTP delivery time, disable HTTP redirects (`follow_redirects=False`), redact delivery response errors (`HTTP {status}` only, zero body reflection, `GAP-003`). Emit `AEGIS-Signature: t=<unix>,v1=<hex>` header (plus optional `X-AEGIS-Signature` only if `WEBHOOK_LEGACY_SIGNATURE_FALLBACK` is enabled, `GAP-014`). Implement outbox lease claim + stale lease reaper + jittered exponential backoff + max attempt dead-lettering + bounded `asyncio.Semaphore` concurrent HTTP dispatch + `FOR UPDATE SKIP LOCKED` payment reconciliation + graceful signal handling (`main.py` catching explicit transient exceptions cleanly without bare drops, `GAP-010`).

7. **Subagent 7 — Containers, Linux Staging, Observability Stack & CI Security Engineer**
   - Own: `services/api/Dockerfile`, `services/worker/Dockerfile`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`, `Makefile`, `pyproject.toml`, `uv.lock`, `deploy/**`
   - Tasks:
     - Update Dockerfiles to run as non-root `USER aegis`, pin base image tags/digests, add worker healthcheck (`python -m aegis_worker.healthcheck` checking DB connectivity + heartbeat file), keep clean multi-stage slim images.
     - `docker-compose.yml` & `.env.example`: Bind Postgres `5432` to `127.0.0.1:5432` (never `0.0.0.0`), add optional `redis`, Prometheus + Grafana alert definitions in `deploy/observability/`, Terraform/systemd/Nginx Linux VPS + Managed PG deployment manifests in `deploy/linux-staging/` (explicitly retiring Android OPPO phone staging, `GAP-021`), multi-region residency env templates (`EU`/`IN`/`US`, `Horizon 5`).
     - `.github/workflows/ci.yml` & `pyproject.toml`: Pin all GitHub Actions by commit SHA, add `pytest-cov` (`--cov-fail-under`), `pip-audit`, `gitleaks`, `trivy` scan, and end-to-end Docker Compose smoke check (`migrate + api /ready + worker heartbeat`). Run `uv lock` cleanly.

8. **Subagent 8 — Machine 1 Integration & Verification Reviewer**
   - Own: Read-only audit + running `packages/security`, `packages/database`, `services/api`, `services/worker` test suites against both SQLite and real PostgreSQL 16 (via Docker `postgres:16-alpine` or `AEGIS_TEST_POSTGRES_URL`).
   - Verify: PG triggers reject `UPDATE`/`DELETE` on `financial_events`; concurrent 2-worker batch tests produce zero duplicate outbox/reconciliation claims; crashed worker leases get reaped; `ADMIN` gets `403` attempting `OWNER`; SSRF blocks `169.254.169.254`/`127.0.0.1`/IPv6 loopback; rate limiter isolates Tenant A vs Tenant B JWTs; `ruff` and `pytest` pass cleanly. Report exact pass/skip/fail output without fabricating any external live check.

### Machine 1 Completion Report Format
When all 8 subagents finish, report:
1. Changed files list (confirming ZERO edits outside Machine 1 scope).
2. Exact output of `uv run ruff check packages/security packages/database services` and `uv run pytest packages/security packages/database services/api services/worker -v` (with PG16 integration results).
3. Any schema/contract migration notes for final merge onto `integration/nexus`.
```

---

## 4. Master Prompt — COMPUTER 2 (Financial Core, Guardian, PayPal, Multi-Rail, GhostPay, DisputeOS & AI)

```markdown
# AEGIS PRODUCTION LAUNCH — COMPUTER 2 MASTER EXECUTION PROMPT
## Role: Financial Core, Guardian, PayPal, Multi-Rail, GhostPay, DisputeOS & AI Lead (8 Subagents)

You are running on **Computer 2** in `/home/bigboyaks/Projects/agentpay-nexus`.
Machines 1 and 3 are working **simultaneously** on other branches (`work/m1-platform-security-infra`, `work/m3-web-sdks-qa`).
Your job is to resolve ALL Financial Core, Guardian, PayPal, Multi-Rail (Stripe/AP2/TAP/x402/MCP), GhostPay, DisputeOS, and AI Systems gaps cleanly with **ZERO merge conflicts** against Machines 1 and 3.

### Git & Safety Rules (NON-NEGOTIABLE)
1. Start from `integration/nexus` (`1be376e`):
   `git fetch origin && git checkout -b work/m2-financial-forensics-ai integration/nexus`
   Also inspect `git log -p ea3c73b..origin/feature/ghostpay` read-only first to confirm any `modules/ghostpay` diffs (`GAP-026`) are cleanly folded in. Never edit `main`, never force-push, never commit secrets.
2. **STRICT WRITE BOUNDARY — Edit ONLY these paths:**
   - `packages/contracts/**`
   - `packages/paypal/**`
   - `modules/agentpay-guardian/**`
   - `modules/ghostpay/**`
   - `modules/disputeos/**`
   - `services/api/aegis_api/adapters.py`
   - `services/api/aegis_api/routers/{guardian_db.py,disputeos_db.py}`
   - Tests in `packages/contracts/tests/**`, `packages/paypal/tests/**`, `modules/*/tests/**`
   **NEVER edit:** `packages/security/`, `packages/database/`, `services/worker/`, `services/api/aegis_api/{app.py,deps.py,rate_limit.py,logging_config.py,routers/auth_orgs.py,routers/webhooks.py,routers/overview.py}`, `pyproject.toml`, `uv.lock`, `apps/web/`, `packages/sdk-*`, `docs/`, `tests/{adversarial,concurrency,e2e,integration}/`.
3. **Zero New Dependencies:** Use existing packages (`httpx`, `pydantic`, `fastapi`, `sqlalchemy`, stdlib) for Stripe/OpenAI/Gemini/Anthropic/MCP JSON-RPC HTTP adapters — never edit root `pyproject.toml` or `uv.lock` (Machine 1 owns dependency lockfiles).
4. **Database Bridge:** Machine 1 adds new tables/columns (`spending_passport_snapshots`, `ghostpay_traces`, `ghostpay_agent_dna_profiles`, `llm_invocation_logs`, `dispute_cases.response_due_by`/`resolved_at`) in `packages/database`. In `adapters.py`, `guardian_db.py`, `disputeos_db.py`, and services, call the frozen repo methods defensively via `getattr`/`hasattr` + Protocol typing so your tests pass standalone BEFORE merging Machine 1's branch AND automatically activate durable PG storage once merged!
5. Follow `AGENTS.md`: AI/LLM nodes can NEVER bypass deterministic policy checks, approve budgets, or trigger PayPal capture directly. Never fabricate sandbox/LLM evidence.

### Exact Gaps Owned by Computer 2
- `GAP-001` (`POST /approve` `request.approved=False` propagation, decline state transition, budget release)
- `GAP-002` (Enforce `Permission.GHOSTPAY_READ` & `Permission.GHOSTPAY_SIMULATE` directly inside `modules/ghostpay/ghostpay/api/router.py`)
- `GAP-005` (`approval.payment_intent_id == intent.id` binding + unconditional `QuoteSnapshot` hash verification & expiry check)
- `GAP-009` (Real PayPal `POST /v1/customer/disputes/{id}/provide-evidence` + `accept-claim`; guarantee `DisputeStatus.SUBMITTED` ONLY after HTTP 2xx + `paypal_dispute_id`)
- `GAP-011` (Single canonical shared `"policy-v1"` evaluator in `packages/contracts/contracts/policy_v1.py` used by BOTH Guardian & GhostPay: `AgentIdentity.status`, rolling daily/monthly spend, expiry/currency, strict passport allowlists, exact threshold operator)
- `GAP-012` (ISO 4217 currency exponents `JPY=0`/`KWD=3`, PayPal retry/backoff, pre-capture `CAPTURE_PENDING` guard, Refunds/Voids/Partial capture, `list_disputes` timeout safety, map `PayPalTimeoutError`/`PayPalAPIError`/`GuardianError` to `502`/`504`/`409`, detach sync DB sessions around outbound PayPal `await` calls, Live Sandbox verification script)
- `GAP-013` (Delete `ghostpay/timemachine/replay.py` & `ghostpay/forensics/*` duplicate engines, persist traces/Agent DNA/investigations via PG repo bridge, replay from immutable `spending_passport_snapshots`/`policy_inputs`, tighten `provenance/verifier.py` removing 2-field cascade, fail-closed `PaymentTrace.to_replay_request`, fix `anomalies/detector.py` false positives on `DENY`, fix `agentdna/profiles.py` trace dedup & cutoff window)
- `GAP-016` (Transactional idempotency check + `DuplicateIntentError` `409 Conflict` on mismatched payload hash + `create_checkout` idempotency lookup)
- `GAP-017` (Monotonic `DisputeStatus` state guard, `POST /v1/disputeos/cases/{id}/resolve`, complete `FinancialEvent`s on attach/submit/resolve, `response_due_by` deadlines, `disputeos.paypal.webhook_handler.handle_paypal_dispute_webhook` for `CUSTOMER.DISPUTE.*`, artifact-to-case IDOR fix in `disputeos_db.py`, full-context `content_hash`, causal `evidence/graph.py` & expanded `detector.py` heuristics)
- `GAP-019` (Real provider-abstracted OpenAI/Gemini/Anthropic `httpx` clients + deterministic fallback in `PurchasingCopilot` & `DisputeAnalyzer`, prompt-injection sanitization, semantic claim-to-excerpt `CitationValidator` & `llm_summary` alignment, token/cost logging hook, AI eval suite)
- `GAP-022` (Sync DB session detachment around PayPal HTTP awaits + `limit`/`offset` pagination on Guardian/GhostPay/DisputeOS list endpoints)
- `GAP-025` & Horizon 4–5 (Provider-neutral `PaymentProviderAdapter` + Stripe `PaymentIntents`/`SPT`/`Connect`/`Issuing`/`Smart Disputes` REST adapter, Google AP2 `CheckoutMandate`/`PaymentMandate` importer, Visa TAP / Mastercard Agent Pay token verifier, `x402` settlement verifier, Verifi/Ethoca pre-dispute deflection interface, and AEGIS MCP Server)
- `GAP-026` (Complete `contracts/export_schemas.py` JSON schema exports + reconcile `origin/feature/ghostpay` trailing diffs)

### Launch 8 Parallel Subagents (Coordinate in Parallel Waves — Zero Same-File Edits)

1. **Subagent 1 — Contracts & Unified `"policy-v1"` Architect**
   - Own: `packages/contracts/contracts/{enums.py,models.py,hashing.py,policy_v1.py,providers.py,export_schemas.py}`, `packages/contracts/tests/**`
   - Tasks:
     - `enums.py` & `models.py`: Ensure canonical `PaymentState` (`CAPTURE_PENDING`, `REFUNDED`, `PARTIALLY_REFUNDED`), `DisputeStatus` (`OPEN`, `UNDER_INVESTIGATION`, `DRAFT_READY`, `APPROVED_FOR_SUBMISSION`, `SUBMITTED`, `RESOLVED`), exact `DisputeAnalysis` (`grounded_summary`, `generated_with_llm`, `citations`, `contradictions`, `missing_evidence`, `recommended_actions`, `llm_provider`, `llm_model`), `DisputeCase` (`response_due_by`, `resolved_at`, `resolution_outcome`, `external_status`), `ReplayTimelineEntry` (`occurred_at`, `actor_type`, `actor_id`, `event_type`, `sequence_number`, `event_hash`, `previous_event_hash`), and AP2/TAP/x402/Stripe normalized models.
     - `models.py` (`QuoteSnapshot`): ALWAYS verify `quote_hash == compute_quote_hash(...)` even when caller passes `quote_hash` (`GAP-005`).
     - `hashing.py` & `policy_v1.py`: Implement single pure deterministic `evaluate_policy_v1(...)` evaluator enforcing `AgentIdentity.status`, `passport` status & expiry, rolling `daily_limit_minor` & monthly budget, quote expiry & currency match, strict merchant allowlist/category intersection (no global `merchant.is_allowlisted` bypass), and exact `amount_minor > threshold` approval threshold. Implement ISO 4217 `minor_to_decimal_str` / `decimal_str_to_minor` (`JPY=0`, `KWD=3`, `BHD=3`, etc.).
     - `providers.py`: Define `PaymentProviderAdapter` protocol for multi-rail adapters.
     - `export_schemas.py`: Export ALL canonical models (fix omissions, `GAP-026`).

2. **Subagent 2 — PayPal Client & Multi-Rail Protocol Engineer**
   - Own: `packages/paypal/**`, `modules/agentpay-guardian/guardian/providers/**` (Stripe, AP2, TAP/Mastercard, x402, pre-dispute deflection), multi-rail tests
   - Tasks:
     - `packages/paypal/paypal/client.py`: Use ISO 4217 currency exponents everywhere (`GAP-012`), add transient exponential backoff retries on 429/5xx/timeouts, add `refund_capture`, `void_authorization`, `provide_evidence(dispute_id, evidence_payload, files=...)`, `accept_claim(dispute_id, note)`, tighten `list_disputes` with strict timeouts & pagination (`GAP-009`, `GAP-012`). Add mocked + optional credential-gated live PayPal Sandbox E2E verification script (`packages/paypal/tests/test_live_sandbox_optional.py`).
     - `modules/agentpay-guardian/guardian/providers/`: Implement Stripe REST adapter via `httpx` (PaymentIntents, Shared Payment Tokens, Connect, Issuing webhooks, Smart Disputes), Google AP2 `CheckoutMandate`/`PaymentMandate` importer & verifier, Visa TAP / Mastercard Agent Pay token provenance verifier, `x402` settlement proof verifier, and Verifi/Ethoca deflection alert handler (`GAP-025`).

3. **Subagent 3 — Guardian Core, Approvals, Checkout & DB Router Engineer**
   - Own: `modules/agentpay-guardian/guardian/{approvals,budgets,domain,payments,policies,api}/**`, `services/api/aegis_api/routers/guardian_db.py`, Guardian tests
   - Tasks:
     - Propagate `approved=request.approved` across `guardian_db.py`, `guardian/api/router.py`, and `guardian/domain/service.py` — when `False`, decline cleanly, release budget hold, emit `FinancialEvent`, return declined state (`GAP-001`).
     - `approvals/service.py`: Verify `approval.payment_intent_id == intent.id`, verify `quote_hash`, re-check expiry & state (`GAP-005`).
     - `policies/engine.py`: Delegate `"policy-v1"` strictly to `contracts.policy_v1.evaluate_policy_v1` + track rolling daily spend (`GAP-011`).
     - `domain/service.py`: Enclose idempotency lookup in transaction + compute canonical proposal hash -> raise `DuplicateIntentError` (`409`) on payload mismatch (`GAP-016`).
     - `payments/coordinator.py`: Check `intent.state == PaymentState.CAPTURE_PENDING` BEFORE HTTP `capture_order`! Wire `create_checkout` attempt idempotency. Wire multi-rail refund/void endpoints (`GAP-012`).
     - `guardian_db.py`: Detach synchronous SQLAlchemy work BEFORE PayPal HTTP `await` calls (`GAP-022`), handle `PayPalTimeoutError -> 504`, `PayPalAPIError -> 502`, `GuardianError -> 409`, add `limit`/`offset` pagination to list endpoints (`GAP-022`), and record immutable `spending_passport_snapshots` when creating/updating/revoking passports.

4. **Subagent 4 — GhostPay Forensics Engine & Provenance Hardening Engineer**
   - Own: `modules/ghostpay/ghostpay/{replay,provenance,timelines,anomalies,agentdna,ingestion,domain}/**`, GhostPay unit tests
   - Tasks:
     - Inspect & clean `origin/feature/ghostpay` (`2a243e1`) diffs; DELETE legacy duplicate modules `timemachine/replay.py` and `forensics/{provenance,timeline,anomalies}.py` (preserving clean exports cleanly mapped to hardened engine, `GAP-013`).
     - `replay/engine.py`: Delegate `"policy-v1"` strictly to `contracts.policy_v1.evaluate_policy_v1` (100% parity with Guardian, `GAP-011`), enforce strict override validator + fail-closed version registry.
     - `provenance/verifier.py`: Remove weak 2-field partial digest cascade; require full canonical hash verification, `correlation_id` binding, and cross-checks against `PaymentAttempt`/`VerifiedPayPalCapture`/`BudgetReservation` (`GAP-013`).
     - `domain/models.py`: Fix `PaymentTrace.to_replay_request` to fail closed with `InsufficientEvidenceError` instead of fabricating synthetic `PurchaseProposal`/`PaymentIntent` (`GAP-013`).
     - `anomalies/detector.py` & recommendations: Harmonize anomaly codes, ignore legitimately `DENY`ed policy blocks (`no false positives`).
     - `agentdna/profiles.py` & `ingestion/validation.py`: Deduplicate repeated `trace_id`s, exclude future leakage relative to replay timestamp, enforce strict cross-entity `tenant_id` checks.

5. **Subagent 5 — GhostPay API, RBAC & Snapshot Adapter Engineer**
   - Own: `modules/ghostpay/ghostpay/api/router.py`, `services/api/aegis_api/adapters.py`, GhostPay API/adapter tests
   - Tasks:
     - `ghostpay/api/router.py`: Enforce `Permission.GHOSTPAY_READ` on all read routes and `Permission.GHOSTPAY_SIMULATE` on simulate/counterfactual/ingest/investigation-create routes (`GAP-002`); retire legacy `PolicyTimeMachine` endpoints onto hardened `ReplayEngine`; replace process-RAM trace/Agent DNA/investigation storage with repository adapter protocol persisted in PG (`GAP-013`); add `limit`/`offset` pagination.
     - `adapters.py`: Reconstruct historical replays from immutable `spending_passport_snapshots` & `AuthorizationDecision.policy_inputs` (never guess balances via naive subtraction!), expose trace & Agent DNA PG repo methods defensively via `getattr`/`hasattr` so work integrates cleanly with Machine 1.

6. **Subagent 6 — DisputeOS Cases, Deadlines, Evidence & PayPal Adapter Engineer**
   - Own: `modules/disputeos/disputeos/{cases,ingestion,evidence,paypal}/**`, `services/api/aegis_api/routers/disputeos_db.py`, DisputeOS tests
   - Tasks:
     - `cases/service.py` & `disputeos_db.py`: Enforce strict monotonic forward `DisputeStatus` state machine (`409` on invalid backward transition once `APPROVED_FOR_SUBMISSION`/`SUBMITTED`/`RESOLVED`), add `POST /v1/disputeos/cases/{case_id}/resolve` (`GAP-017`), emit hash-chained `FinancialEvent`s on `attach_evidence`, `mark_submitted`, and `mark_resolved`, store & surface `response_due_by` SLA countdowns + `limit`/`offset` pagination, enforce artifact-to-case IDOR validation in `download_evidence_artifact`.
     - `ingestion/normalizer.py`: Hash full evidence context (`tenant_id`, `dispute_case_id`, `correlation_id`, `is_synthetic`, `collected_at`, `source_type`, `source_ref`, `title`, `content`), reject mismatched caller-supplied hashes, re-verify digests downstream.
     - `evidence/graph.py` & `detector.py`: Replace naive stage Cartesian product with causal linkage (`payment_intent_id`, `correlation_id`, chronological causality); expand heuristics beyond 4 substrings to card AVS/CVV/3DS, IP/device telemetry, subscription cancellation proofs, and `SIGNIFICANTLY_NOT_AS_DESCRIBED` packets.
     - `paypal/adapter.py` & new `paypal/webhook_handler.py` & `disputeos_db.py`: Wire real `PayPalSandboxClient.provide_evidence` + `accept_claim`; require `case.paypal_dispute_id` + HTTP 2xx BEFORE transitioning to `DisputeStatus.SUBMITTED` (`GAP-009`, never fake submit); implement `handle_paypal_dispute_webhook(repo, event_type, resource, event_id)` parsing `CUSTOMER.DISPUTE.CREATED/UPDATED/RESOLVED` and setting `response_due_by` (`GAP-017`).

7. **Subagent 7 — AI Intelligence, Prompt Safety & AEGIS MCP Server Engineer**
   - Own: `modules/disputeos/disputeos/analysis/**`, `modules/agentpay-guardian/guardian/{copilot,mcp_server}.py`, AI eval & MCP tests
   - Tasks:
     - Build provider-abstracted async `httpx` LLM client supporting OpenAI, Google Gemini, and Anthropic (plus clean deterministic fallback when `LLM_PROVIDER=deterministic`), logging tokens, model, correlation ID, and estimated cost via repo hook `log_llm_invocation` (`GAP-019`).
     - Upgrade `CitationValidator` from naive substring matching to semantic claim-to-excerpt alignment & verify `llm_summary` claims against cited excerpts; add prompt-injection delimiter isolation & sanitization on buyer/merchant free-text inputs before prompting LLMs; ensure `PurchasingCopilot` stays strictly read-only/advisory (deterministic policy & human approval boundaries unchanged).
     - Build the **AEGIS MCP Server** (`guardian/mcp_server.py`) exposing standard Model Context Protocol JSON-RPC tools (`check_policy`, `propose_payment`, `get_passport_budget`, `list_audit_timeline`) with strict auth context (`Horizon 4`).
     - Add an automated offline AI eval & prompt-injection regression test suite under `modules/disputeos/tests/` and `modules/agentpay-guardian/tests/`.

8. **Subagent 8 — Machine 2 Property, Parity & Financial Verification Reviewer**
   - Own: Read-only audit + running `packages/contracts`, `packages/paypal`, `modules/agentpay-guardian`, `modules/ghostpay`, `modules/disputeos`, and Machine-2 router tests.
   - Verify: 1,000-case randomized property test confirming 100% Guardian <-> GhostPay `"policy-v1"` parity (`GAP-011`); `approved=False` returns declined with `reserved_minor == 0` & capture `409`; approval-replay & caller-supplied tampered `quote_hash` return `422`/`409`; `JPY` (0 decimals) and `KWD` (3 decimals) PayPal payload formatting; DisputeOS failed submission stays `APPROVED_FOR_SUBMISSION`; GhostPay routes enforce `GHOSTPAY_READ`/`GHOSTPAY_SIMULATE`; AI prompt-injection tests pass; live external LLM/PayPal calls clearly marked `NOT VERIFIED` if credentials are absent.
```

---

## 5. Master Prompt — COMPUTER 3 (Next.js Console, Python/TS SDKs, Docs, Legal & QA Harness)

```markdown
# AEGIS PRODUCTION LAUNCH — COMPUTER 3 MASTER EXECUTION PROMPT
## Role: Next.js Console, SDKs, Docs, Legal/Onboarding & Full QA Harness Lead (8 Subagents)

You are running on **Computer 3** in `/home/bigboyaks/Projects/agentpay-nexus`.
Machines 1 and 2 are working **simultaneously** on other branches (`work/m1-platform-security-infra`, `work/m2-financial-forensics-ai`).
Your job is to fix ALL Next.js Frontend contract/UX/auth bugs, bring Python & TypeScript SDKs to production parity (`>=85%` coverage + middlewares), update all Docs + Legal/Compliance templates, clean dead dirs (`packages/ui/`), and build the complete Playwright, RBAC (`6x78`), Adversarial, Concurrency, and SDK Integration QA harness with **ZERO merge conflicts** against Machines 1 and 2.

### Git & Safety Rules (NON-NEGOTIABLE)
1. Start from `integration/nexus` (`1be376e`):
   `git fetch origin && git checkout -b work/m3-web-sdks-qa integration/nexus`
   Never edit `main`, never force-push, never commit secrets.
2. **STRICT WRITE BOUNDARY — Edit ONLY these paths:**
   - `apps/web/**`
   - `packages/sdk-python/**`
   - `packages/sdk-typescript/**`
   - `docs/**`, `README.md`
   - Remove empty `packages/ui/` (`GAP-026`)
   - `tests/{adversarial,concurrency,e2e,integration}/**`
   **NEVER edit:** `packages/security/`, `packages/database/`, `packages/contracts/`, `packages/paypal/`, `modules/`, `services/`, root `pyproject.toml`, `uv.lock`, `docker-compose.yml`, `.github/workflows/ci.yml`.
3. **Code Against Frozen Day-0 Contracts:**
   - Roles (`6` ONLY): `OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`.
   - Merchant write permission: `"passports:write"` (never `"merchants:write"`).
   - `PaymentState` (`11`+): `CREATED`, `POLICY_CHECK`, `AWAITING_APPROVAL`, `APPROVED`, `CHECKOUT_CREATED`, `CAPTURE_PENDING`, `CAPTURED`, `FAILED`, `CANCELLED`, `EXPIRED`, `REFUNDED` (`Capture` runs ONLY in `CAPTURE_PENDING`).
   - `PaymentAttempt` / `Approval`: `attempt.state`, `attempt.verified_capture?.paypal_capture_id`, `attempt.paypal_approval_url`, `approval.decided_at`.
   - `DisputeAnalysis`: `grounded_summary`, `generated_with_llm`, `citations`, `contradictions: string[]`, `missing_evidence: string[]`, `recommended_actions: string[]`.
   - `ReplayTimelineEntry`: `occurred_at`, `actor_type`, `actor_id`, `event_type`, `sequence_number`, `event_hash`, `previous_event_hash`.
   - Webhook header: `AEGIS-Signature: t=<unix_seconds>,v1=<hex_hmac_sha256>` over `f"{t}.{raw_body}"` (300s window).
   - Pagination query params: `limit`, `offset`, `q` (search) across list routes.
   - New endpoints added by Machine 1/2: `POST /v1/disputeos/cases/{id}/resolve`, `/v1/billing/*`, `/v1/privacy/*`, `/v1/orgs/invitations/{token}/accept`.
4. **Web Auth Architecture (Zero FastAPI Coupling):**
   Implement `apps/web` BFF Route Handlers (`/api/auth/login`, `/api/auth/signup`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/switch-org`, `/api/proxy/[...path]`) storing the JWT ONLY in an `HttpOnly; SameSite=Lax` cookie (`aegis_session`), never in `window.localStorage`!

### Exact Gaps Owned by Computer 3
- `GAP-004` (Fix all UI contract mismatches across all 14 Next.js routes: `CAPTURE_PENDING`, `passports:write`, 6 valid `Role`s, `DisputeAnalysis`, `ReplayTimelineEntry`, `previous_event_hash`)
- `GAP-014` (Sync Python SDK, TypeScript SDK, & `INTEGRATION_GUIDE.md` verbatim on `AEGIS-Signature: t=...,v1=...`)
- `GAP-015` (Expand Python & TS SDKs to `>=85%` OpenAPI parity, fix TS `detail.message` error parser, add `AsyncAegisClient`, WebCrypto edge compat, retries/timeouts, pagination, LangGraph/OpenAI/Vercel AI 3-line middleware helpers, `py.typed`/`.d.ts`, SDK `README.md`s)
- `GAP-018` (`HttpOnly` cookie session BFF, `/me` load validation, `401` auto-eviction, `AbortController` timeouts, CSP/HSTS/security headers in `next.config.ts` & `middleware.ts`)
- `GAP-022` (Pagination & search across all UI tables, accessibility `<th scope="col">` & `role="alert"`, surface `PATCH /passports`, `allow_unknown_merchants`, service accounts, webhook deliveries/delete, worker outbox DLQ viewer/requeue, org creator/invite accept, `POST /disputeos/cases`, `POST /ghostpay/investigations`, Agent DNA UI)
- `GAP-023` (Complete Playwright E2E suite, `6 roles x 78 ops` RBAC negative matrix, SSRF/tamper/injection adversarial tests, PG contention test harness, SDK-vs-OpenAPI contract parity tests)
- `GAP-024` (Org onboarding wizard, Stripe billing/quotas UI, Privacy/GDPR erasure & export UI, published Legal pages ToS/Privacy/DPA, Status page)
- `GAP-026` (Remove empty `packages/ui/`, delete stale `docs/TEAM_HANDOFF.md`, update `README.md`, `INTEGRATION_GUIDE.md`, `AEGIS_PLATFORM_BUILD_REPORT.md`, add operational runbooks & compliance memo)

### Launch 8 Parallel Subagents (Coordinate in Parallel Waves — Zero Same-File Edits)

1. **Subagent 1 — Web Auth BFF, Client Core & Browser Security Engineer**
   - Own: `apps/web/src/app/api/**`, `apps/web/src/lib/{auth-context.tsx,api.ts,types.ts}`, `apps/web/next.config.ts`, `apps/web/src/middleware.ts`
   - Tasks:
     - Build Next.js Route Handlers `/api/auth/{login,signup,logout,me,switch-org}` & `/api/proxy/[...path]` using `HttpOnly`, `SameSite=Lax`, `Secure` (prod) cookie `aegis_session`. Remove ALL `window.localStorage` JWT usage (`GAP-018`).
     - Validate session via `GET /api/auth/me` on mount; auto-evict on HTTP `401` and redirect cleanly to `/login`; add `AbortController` request timeouts + surface error banners (`AppShell.tsx` switch-org errors).
     - Fix all TypeScript interfaces in `api.ts`/`types.ts` to match frozen canonical contracts (`PaymentState`, `Role`, `PaymentAttempt`, `DisputeAnalysis`, `ReplayTimelineEntry`, `previous_event_hash`, `limit`/`offset`/`q`).
     - Configure strict CSP, `Strict-Transport-Security`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` headers in `next.config.ts`/`middleware.ts`.

2. **Subagent 2 — Web Guardian & Merchant Payments Operations Engineer**
   - Own: `apps/web/src/app/{agents,passports,payments,payments/[id]}/**`
   - Tasks:
     - `/agents`: Fix `"merchants:write"` -> `"passports:write"` so merchant creation & allowlist controls render for authorized users (`GAP-004`), add search + pagination.
     - `/passports`: Expose `allow_unknown_merchants` toggle, add inline `PATCH` policy limit editor modal, fix `useCallback` dependency re-fetch loop, add search + pagination.
     - `/payments` & `/payments/[id]`: Align state filter chips with canonical `PaymentState` (`CAPTURE_PENDING`, `CREATED`, `POLICY_CHECK`, `AWAITING_APPROVAL`, `CAPTURED`, `FAILED`, `CANCELLED`, `EXPIRED`, `REFUNDED`). Render Capture button on `CAPTURE_PENDING`; fix `attempt.state`, `attempt.verified_capture?.paypal_capture_id`, `approval.decided_at`; render `paypal_approval_url` link; implement **Decline / Reject** (`approved: false`), **Buyer Declined**, and **Refund** controls + accessible `.table-wrapper` + `<th scope="col">`.

3. **Subagent 3 — Web GhostPay, DisputeOS & Audit Experience Engineer**
   - Own: `apps/web/src/app/{ghostpay,ghostpay/replay/[id],disputes,disputes/[id],audit}/**`
   - Tasks:
     - `/ghostpay` & `/ghostpay/replay/[id]`: Fix `ReplayTimelineEntry` fields (`occurred_at`, `actor_type`, `actor_id`), add `POST /v1/ghostpay/investigations` form, add **Agent DNA Profile** inspector panel, add pagination & search.
     - `/disputes` & `/disputes/[id]`: Fix `DisputeAnalysis` rendering (`grounded_summary`, `generated_with_llm`, `citations`, `contradictions: string[]`, `missing_evidence`, `recommended_actions`); render `response_due_by` SLA countdown badges; add non-synthetic `POST /v1/disputeos/cases` form, `source_type` selector, JSON `/evidence` attach form, `/resolve` modal, `/report` export button; ensure `<th scope="col">`.
     - `/audit`: Fix `previous_event_hash`, add `event_type` & `correlation_id` filters + pagination.

4. **Subagent 4 — Web Developer, Settings, Billing, Onboarding & Legal UI Engineer**
   - Own: `apps/web/src/app/{login,dashboard,developer,settings,onboarding,legal,status}/**`, `apps/web/src/components/**`
   - Tasks:
     - `/login`: Use `role="alert"` on error banners; add email verification prompt & invitation accept link handling.
     - `/developer` & `/settings`: Replace invalid roles (`DEVELOPER`, `AGENT_RUNTIME`, `FINANCE_ADMIN`, `RISK_ANALYST`, `DISPUTE_OPERATOR`) with canonical 6 roles (`OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`) (`GAP-004`). Add Service Accounts CRUD, Webhook Enable/Disable/Delete + Delivery Log viewer, Worker Outbox Dead-Letter Viewer & Requeue actions, and Organization Creation + Switcher error toasts (`GAP-022`).
     - `/dashboard`, `/onboarding`, `/settings` Billing & Privacy tabs, `/legal/{terms,privacy,dpa}`, `/status`: Build guided Onboarding Wizard, Stripe Plan/Usage/Quota panel + GDPR/DPDPA Data Export & Erasure UI (`GAP-024`), public Legal & System Status pages.

5. **Subagent 5 — Python SDK & Agent Framework Middleware Engineer**
   - Own: `packages/sdk-python/**`
   - Tasks:
     - Expand `AegisClient` and add full `AsyncAegisClient` covering `>=85%` of all `78+` OpenAPI endpoints (Auth/Orgs, Passports `PATCH`, Approvals with `approved: bool`, Capture, Refund, GhostPay Replay/Counterfactual/Traces/Agent DNA/Investigations, DisputeOS Cases/Evidence/Analyze/Approve/Submit/Resolve/Report, Webhooks, Worker Outbox, Overview, Billing, Privacy) (`GAP-015`).
     - Implement configurable timeouts, transient retry/backoff, pagination iterators, typed exceptions (`AegisAPIError` parsing FastAPI `detail`), `py.typed` marker, and canonical `verify_aegis_signature(raw_body, signature_header, secret, tolerance_seconds=300)` matching `AEGIS-Signature: t=...,v1=...` (`GAP-014`).
     - Add lightweight framework adapter helpers (`aegis_sdk/integrations/langchain.py`, `aegis_sdk/integrations/openai_agents.py`) & complete `packages/sdk-python/README.md`.

6. **Subagent 6 — TypeScript SDK, Edge WebCrypto & Middleware Engineer**
   - Own: `packages/sdk-typescript/**`
   - Tasks:
     - Fix FastAPI error extraction bug (`typeof detail === "string"`, Pydantic validation error array, and `detail.message` object, `GAP-015`).
     - Expand `AegisClient` to `>=85%` OpenAPI coverage with strict exported `.d.ts` types, `AbortController` timeouts, retries, pagination helpers, `approved: boolean` on approvals, plus Vercel AI SDK middleware helper (`src/integrations/vercel-ai.ts`).
     - Implement `verifyAegisSignature` supporting BOTH Node `crypto` and WebCrypto (`crypto.subtle` for Edge/Cloudflare/Next.js runtimes) against `AEGIS-Signature: t=<unix>,v1=<hex>` (`GAP-014`). Write comprehensive `packages/sdk-typescript/README.md` + npm package metadata + Vitest unit suite.

7. **Subagent 7 — Documentation, Legal Templates, Runbooks & Repo Hygiene Engineer**
   - Own: `README.md`, `docs/**`, delete empty `packages/ui/`
   - Tasks:
     - Delete empty `packages/ui/` and stale `docs/TEAM_HANDOFF.md` (`GAP-026`).
     - Rewrite `docs/sdk/INTEGRATION_GUIDE.md` so every code snippet (`AEGIS-Signature: t=,v1=`, 6 `Role`s, `PaymentState`, SDK methods) runs verbatim (`GAP-014`).
     - Update `README.md` & `docs/AEGIS_PLATFORM_BUILD_REPORT.md` honestly removing unverified Android staging claims and keeping implemented reality accurate.
     - Author production docs: `docs/legal/{TERMS_OF_SERVICE,PRIVACY_POLICY,DATA_PROCESSING_ADDENDUM}.md`, `docs/compliance/NON_CUSTODIAL_PERIMETER.md`, `docs/runbooks/{INCIDENT_RESPONSE,PG_PITR_RECOVERY,WEBHOOK_DLQ}.md`, `docs/status/STATUS_PAGE.md`.

8. **Subagent 8 — Playwright E2E, RBAC Matrix, Adversarial & Concurrency QA Engineer**
   - Own: `apps/web/tests/**`, `tests/{adversarial,concurrency,e2e,integration}/**`
   - Tasks:
     - `apps/web/tests/`: Install/use Playwright test harness exercising all 14+ Next.js routes end-to-end (login -> create merchant -> passport -> proposal -> approve/reject -> capture/refund -> GhostPay replay/counterfactual -> DisputeOS case/evidence/analyze/resolve -> billing/erasure/onboarding, `GAP-004`).
     - `tests/adversarial/`: Automated `6 roles x all OpenAPI operations` RBAC matrix asserting exact `2xx`/`403` boundaries; SSRF payload matrix (IPv4/IPv6/decimal/redirect); `ADMIN -> OWNER` escalation test; quote-hash tamper & cross-intent approval replay tests; prompt-injection test suite (`GAP-023`).
     - `tests/concurrency/`: 20-worker PostgreSQL contention tests for atomic budget reservation, outbox lease claim/reap, payment reconciliation `SKIP LOCKED`, and parallel proposal idempotency (`GAP-010`, `GAP-016`, `GAP-023`).
     - `tests/integration/`: OpenAPI coverage gate proving Python & TS SDKs cover `>=85%` of FastAPI operations, plus verbatim `INTEGRATION_GUIDE.md` webhook quickstart execution test (`GAP-014`, `GAP-015`).

### Machine 3 Completion Report Format
When all 8 subagents finish, report:
1. Changed files list (confirming ZERO edits outside Machine 3 scope).
2. Exact results of:
   - `cd apps/web && npm run typecheck && npm run lint && npm test && npm run build` (plus Playwright E2E summary)
   - `cd packages/sdk-typescript && npm run typecheck && npm test`
   - `uv run pytest packages/sdk-python tests/ -v` (explicitly noting which tests require Machine 1/2 merge to pass live vs passing mocked standalone).
```

---

## 6. Deterministic Merge & Final Release Gate Choreography

Once all 3 computers finish and push their branches (`work/m1-platform-security-infra`, `work/m2-financial-forensics-ai`, `work/m3-web-sdks-qa`), one Lead merges them into `integration/nexus` in this exact order:

1. **Step 1 — Merge Computer 1 first (`work/m1-platform-security-infra -> integration/nexus`)**
   - Brings in `pyproject.toml`/`uv.lock`, Alembic additive migrations (`0002+`), PG triggers, SSRF guards, settings aliases, worker leases, and billing/privacy routers.
   - Verify: `uv sync`, `alembic upgrade head` against ephemeral PG16, `uv run ruff check .`.
2. **Step 2 — Merge Computer 2 second (`work/m2-financial-forensics-ai -> integration/nexus`)**
   - Brings in unified `contracts.policy_v1`, `PayPalSandboxClient` currency/disputes/refunds, Guardian fixes, cleaned GhostPay (`timemachine`/`forensics` retired, PG snapshots active), DisputeOS deadlines/webhook handler/real submission, multi-rail adapters, MCP server, and AI clients.
   - Verify: Full combined Python unit + PG16 suite (`uv run pytest -v`), 1,000-case Guardian <-> GhostPay parity property test, OpenAPI generation check.
3. **Step 3 — Merge Computer 3 last (`work/m3-web-sdks-qa -> integration/nexus`)**
   - Brings in fixed Next.js console (`HttpOnly` BFF, zero `localStorage` JWT), >=85% Python/TS SDKs, synced docs/legal templates, and the complete cross-system QA harness (`tests/{adversarial,concurrency,e2e,integration}`, `apps/web/tests`).
   - Verify **ALL** gates cleanly end-to-end against live PostgreSQL 16 + FastAPI + Next.js:
     - `uv run ruff check .`
     - `AEGIS_TEST_POSTGRES_URL=... uv run pytest --cov -v` (unit + PG16 + `6x78` RBAC matrix + SSRF + 20-worker contention + SDK OpenAPI parity)
     - `cd packages/sdk-typescript && npm run typecheck && npm test && npm run build`
     - `cd apps/web && npm run typecheck && npm run lint && npm test && npm run build && npx playwright test`
     - `docker compose up --build -d` -> verify `/ready` `200`, worker healthcheck green, and Compose smoke check passes cleanly.
4. **Live External Gate (Credential-Gated Before Customer Traffic):**
   - Supply real PayPal Sandbox credentials & execute `test_live_sandbox_optional.py` (`create -> approve -> capture -> refund -> dispute provide-evidence -> webhook`).
   - Supply live LLM & Stripe test-mode keys & run live AI eval + Stripe billing checkout test.
   - Publish `docs/legal/*` after legal counsel sign-off and run external web/API penetration test before tagging Production `v1.0.0`.

