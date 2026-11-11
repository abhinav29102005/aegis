# 18 — Audit Evidence Index & Verification Ledger

**Repository:** `/home/bigboyaks/Projects/agentpay-nexus` (`integration/nexus` @ `1be376e`)  
**Audit Date:** `2026-11-12` · **Mode:** Strictly Read-Only (zero repo mutations during audit)

---

## 1. Commands & Runtime Checks Executed Directly During Audit

| Check | Exact Command | Observed Result | Classification |
| :--- | :--- | :--- | :--- |
| Git Refs & Tree Status | `git branch -vv && git for-each-ref ... && git status --short` | Clean working tree on `integration/nexus` (`1be376e`); `main` at `0108f84`; `origin/feature/ghostpay` ahead at `2a243e1` vs local `ea3c73b` | **VERIFIED** |
| OpenAPI Route Enumeration | `uv run python -c "from aegis_api.app import create_app; ..."` | `PATHS=69`, `OPERATIONS=78` across `/health`, `/ready`, `/v1/*` | **VERIFIED** |
| Empty Dirs & Host Check | `ls -la packages/ui scripts tests tests/* && uname -m && free -h` | Empty `packages/ui`, `scripts`, `tests/{adversarial,concurrency,e2e,integration}`; host `x86_64`, `20` CPU, `15 GiB RAM` | **VERIFIED** |
| Python Unit/Integration Suite | `uv run pytest -q` (and `-v --tb=short`) | **`143 passed, 1 skipped in 3.16s`** (`test_postgres_integration.py` skipped without `AEGIS_TEST_POSTGRES_URL`) | **VERIFIED BY TEST** |
| Python Coverage Flag Check | `uv run pytest --cov=...` | `pytest-cov` not installed (`unrecognized arguments: --cov`) — % coverage unmeasured | **BLOCKED / MISSING TOOL** |
| Python Lint / TS SDK / Web Build *(prior turn on identical source `ea3c73b->1be376e`)* | `uv run ruff check packages modules services`; TS SDK `npm run typecheck && npm test`; Web `npm run typecheck && npm run lint && npm test && npm run build` | Ruff: `All checks passed!`; TS SDK: `3 passed`; Web: `0 ESLint warnings/errors`, `3 passed`, `14` routes built | **VERIFIED BY TEST** |
| PostgreSQL 16 Live Suite *(prior turn before doc edit in `1be376e`)* | `AEGIS_TEST_POSTGRES_URL=... uv run pytest -v` | **`144 passed, 3 warnings`** against ephemeral `postgres:16-alpine` (`NOT` re-run after `.md` edit during read-only audit) | **PREVIOUSLY VERIFIED (`1be376e` source unchanged)** |
| Live PayPal Sandbox Network Flows | N/A (read-only audit; empty `PAYPAL_CLIENT_ID`/`SECRET` in env) | Mocked via `httpx.MockTransport`; zero live calls to `api-m.sandbox.paypal.com` | **CLAIMED / NOT VERIFIED LIVE** |
| Live LLM Provider Flows | N/A (`LLM_PROVIDER=deterministic`; no OpenAI/Gemini client in `guardian`/`disputeos`) | Tested only via deterministic fallbacks & fake reviewer classes | **MISSING / NOT VERIFIED LIVE** |
| OPPO / Termux / PRoot Staging Host | Static search & lockfile inspection (`rg -ni "(android\|termux\|proot)"`) | Zero Android/Termux/PRoot scripts in repo; `uv.lock` includes ARM64 wheels; phone runtime unavailable on x86_64 audit host | **BLOCKED / NOT VERIFIED LIVE** |

---

## 2. Primary Code Evidence Reference Table (Quick Lookup)

| Domain | Critical Finding | Exact File & Line Reference | Status |
| :--- | :--- | :--- | :--- |
| Guardian | `approve_proposal` ignores `request.approved` | `services/api/aegis_api/routers/guardian_db.py:433`, `modules/agentpay-guardian/guardian/api/router.py:94`, `guardian/domain/service.py:290` | `VERIFIED IN CODE` |
| Guardian | Missing `payment_intent_id` check on `consume_approval` | `modules/agentpay-guardian/guardian/approvals/service.py:188-205` | `VERIFIED IN CODE` |
| Guardian | Missing agent status & `daily_limit_minor`; allowlist OR bypass | `modules/agentpay-guardian/guardian/policies/engine.py:35-130` | `VERIFIED IN CODE` |
| Guardian | Idempotency TOCTOU & missing `DuplicateIntentError` | `modules/agentpay-guardian/guardian/domain/service.py:87-110` | `VERIFIED IN CODE` |
| Contracts | Caller-supplied `quote_hash` skips verification | `packages/contracts/contracts/models.py:182-191` | `VERIFIED IN CODE` |
| PayPal | 2-decimal currency math breaks JPY/KWD | `packages/paypal/paypal/client.py:39-45,195,453` | `VERIFIED IN CODE` |
| PayPal | `capture_order` runs HTTP capture before checking `CAPTURE_PENDING` | `modules/agentpay-guardian/guardian/payments/coordinator.py:225-260,361` | `VERIFIED IN CODE` |
| PayPal | Refunds, voids, partial capture & dispute submission unimplemented | `packages/paypal/paypal/client.py:270-333,406-474` | `VERIFIED IN CODE` |
| GhostPay | No RBAC on `/v1/ghostpay/*` routes in platform API | `services/api/aegis_api/app.py:152-155`, `deps.py:159-160` | `VERIFIED IN CODE` |
| GhostPay | Split engines + Guardian/GhostPay `"policy-v1"` divergence | `ghostpay/replay/engine.py:55-108`, `ghostpay/timemachine/replay.py:184-305`, `guardian/policies/engine.py:73-130` | `VERIFIED IN CODE` |
| GhostPay | Split RAM vs PostgreSQL storage (`POST` vs `GET /investigations`, `/traces/*`, `/agents/*`) | `modules/ghostpay/ghostpay/api/router.py:201-504` | `VERIFIED IN CODE` |
| GhostPay | In-place passport overwrite & lossy balance rollback | `packages/database/database/repository.py:228-260`, `services/api/aegis_api/adapters.py:89-104` | `VERIFIED IN CODE` |
| DisputeOS | No-op submission marked `DisputeStatus.SUBMITTED` | `modules/disputeos/disputeos/paypal/adapter.py:47-83`, `services/api/aegis_api/routers/disputeos_db.py:510` | `VERIFIED IN CODE` |
| DisputeOS | Missing state guard, deadlines, `/resolve`, case-artifact binding, & real LLM | `disputeos/cases/service.py:236,358`, `disputeos_db.py:267-362`, `disputeos/analysis/citations.py:70-75`, `normalizer.py:23-35` | `VERIFIED IN CODE` |
| Security | Outbound webhook SSRF & 250-char response reflection | `services/api/aegis_api/routers/webhooks.py:25`, `services/worker/aegis_worker/processor.py:92,105` | `VERIFIED IN CODE` |
| Security | `ADMIN` can grant `OWNER` role & cross-org add user | `services/api/aegis_api/routers/auth_orgs.py:340-400,483-523` | `VERIFIED IN CODE` |
| Security | Env-var mismatch (`JWT_SECRET`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR` ignored) | `packages/security/security/settings.py:32-52`, `.env.example:24-27`, `docker-compose.yml:51-53,89` | `VERIFIED IN CODE` |
| Security | Global JWT rate-limit prefix collision (`tok:eyJhbGciOiJIUzI1Ni`) | `services/api/aegis_api/rate_limit.py:29-31` | `VERIFIED IN CODE` |
| Security | Victim `tenant_id` UUID echoed on 403; `/ready` leaks `str(exc)` | `packages/security/security/tenant.py:15-18`, `services/api/aegis_api/app.py:125-150` | `VERIFIED IN CODE` |
| Worker | Permanent `PROCESSING` hang on crash; non-locked reconciliation; DLQ `attempts` not reset | `services/worker/aegis_worker/processor.py:47-52,156-185`, `packages/database/database/platform_repo.py:587-679` | `VERIFIED IN CODE` |
| Frontend | Capture unreachable (`BUYER_APPROVED`), hidden Merchant (`merchants:write`), `422` roles, broken Dispute & GhostPay render | `apps/web/src/app/payments/[id]/page.tsx:235`, `agents/page.tsx:208,363`, `developer/page.tsx:47`, `settings/page.tsx:20`, `disputes/[id]/page.tsx:327-357`, `ghostpay/replay/[id]/page.tsx:234-244` | `VERIFIED IN CODE` |
| SDKs & Docs | `12.8%`/`25.6%` coverage, broken TS `detail` parser, `AEGIS-Signature` doc/SDK crash | `packages/sdk-python/aegis_sdk/client.py:23-28`, `packages/sdk-typescript/src/index.ts:71-83,156-160`, `docs/sdk/INTEGRATION_GUIDE.md:103-122` | `VERIFIED IN CODE` |
| Infra | Root Python containers, unpinned tags, no worker healthcheck, no PITR/triggers | `services/api/Dockerfile`, `services/worker/Dockerfile`, `docker-compose.yml`, `packages/database/database/orm.py` | `VERIFIED IN CODE` |

---

## 3. External Research Sources Consulted (`search_web` 2026-11-12)
- Stripe Agentic Commerce Protocol (ACP), Shared Payment Tokens (SPTs), Agent Toolkit, Restricted API Keys, Connect, Radar, Issuing, Financial Connections, Billing & Smart Disputes official documentation & pricing references.
- PayPal Orders API v2, Payments v2, Customer Disputes API v1, Webhook signature verification (`POST /v1/notifications/verify-webhook-signature`), PayPal Complete Payments, Braintree chargebacks & `@paypal/agent-toolkit` official developer documentation.
- Emerging Agentic Standards: Google Agent Payments Protocol (AP2), Coinbase `x402`, Visa Intelligent Commerce / Trusted Agent Protocol (TAP), Mastercard Agent Pay / AP4M, and Skyfire KYA.
- Security & Regulatory Frameworks: OWASP API Security Top 10 (2023), PCI DSS v4.0.1 (SAQ A Reqs 6.4.3 / 11.6.1 & TPSP RoC), US FinCEN MSB / State MTL processor exemption, India RBI Payment Aggregator guidelines & DPDPA 2023.

