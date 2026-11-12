# 18 — Audit Evidence Index & Verification Ledger (`2026-11-12` Final Post-Integration)

**Repository:** `/home/bigboyaks/Projects/agentpay-nexus` (`integration/nexus`, Post-M1 `d9ab7b8` + M3 `4b5d52f` + M2 `3bbaeb6` + post-merge sync fixes)  
**Baseline Audited Commit:** `integration/nexus` @ `1be376e` / `7829095`

---

## 1. Commands & Runtime Checks Executed Directly on Final Integrated Code

| Check | Exact Command | Observed Final Post-Edit Result | Classification |
| :--- | :--- | :--- | :--- |
| Branch Sync State | `git log --oneline -n 6 integration/nexus` & branch merges | `work/m1-platform-security-infra` (`d9ab7b8`), `work/m3-web-sdks-qa` (`4b5d52f`), & `work/m2-financial-forensics-ai` (`3bbaeb6`) all pushed to `origin` and merged cleanly (`0` conflicts; `245` files changed `+47,751 / -4,209` vs `1be376e`) | **VERIFIED** |
| OpenAPI & ORM Inventory | `create_app().openapi()` + `Base.metadata.tables` | `OPENAPI_PATHS=88`, `OPENAPI_OPS=99`, `ORM_TABLES=37`, `3` Alembic revisions (`0001`–`0003`), `19` Next.js pages, `6` BFF routes | **VERIFIED** |
| Python Lint (`ruff`) | `uv run ruff check .` | **`All checks passed!`** (`0` errors repo-wide, down from `79`) | **VERIFIED (`PASS`)** |
| Full Python + QA PG16 Suite + Coverage | `AEGIS_TEST_POSTGRES_URL=... uv run pytest -q --cov=packages --cov=modules --cov=services --cov-report=term-missing:skip-covered` | **`313 passed, 1 skipped` (`test_live_paypal_sandbox_oauth_and_order_roundtrip`), `0 failed` in `42.34s`**; **`90%` statement coverage (`20,241` stmts, `2,078` missed; `81` files at 100%)** | **VERIFIED BY TEST (`PG16`)** |
| Guardian <-> GhostPay `"policy-v1"` Parity | `modules/ghostpay/tests/test_forensics_hardening.py` | **1,000 / 1,000 randomized scenarios, `0` mismatches** (included in `313 passed`) | **VERIFIED BY TEST** |
| Root QA Harness (`tests/` in `testpaths`) | `tests/{adversarial,concurrency,e2e,integration}/` | **`16 / 16` PASS** (6-role RBAC matrix `3/3`, adversarial `6/6`, concurrency/outbox CAS+PG16 `3/3`, console E2E `1/1`, SDK parity + verbatim docs `3/3` — included in `313 passed`) | **VERIFIED BY TEST** |
| SDK OpenAPI Parity Gate | `uv run pytest -v tests/integration/test_sdk_parity_gate.py -s` | `Total Canonical Endpoints: 99`; **Python SDK `97 / 99 (98.0%)`**, **TypeScript SDK `97 / 99 (98.0%)`** — `3 passed` | **VERIFIED BY TEST** |
| Live Docker Compose Smoke | `POSTGRES_PORT=55432 REDIS_PORT=56379 API_PORT=18000 WEB_PORT=13005 make compose-smoke` | Built integrated `migrate`, `api`, `worker`, & `web` images; `postgres` + `redis` healthy; `migrate` (`0003`) exit `0`; `GET /ready` `200`; `worker --healthcheck` exit `0`; `web` `/login` `200` & `/api/auth/me` `401`; clean teardown | **VERIFIED LIVE (RC1)** |
| TypeScript SDK (`sdk-typescript`) | `npm run typecheck && npm test && npm audit` | `tsc --noEmit` + `tsc` build PASS; **`35 passed` (Vitest `4` suites)** + **`3 passed` (Node legacy)**; `npm audit`: **`found 0 vulnerabilities`** | **VERIFIED BY TEST (RC1)** |
| Next.js Console (`apps/web`) | `npm run typecheck && npm run lint && npm test && npm run build && npm audit --omit=dev` | `tsc` PASS; `eslint .` `0` errors (`4` warnings); **`3/3` unit tests PASS**; `next build` **`24/24` routes PASS**; `npm audit --omit=dev`: **`found 0 vulnerabilities`** (`next@16.4.6`) | **VERIFIED BY TEST (RC1)** |
| Python Supply-Chain Audit | `uv export --frozen --no-emit-workspace --no-hashes -o /tmp/aegis-reqs.txt && uv run pip-audit -r /tmp/aegis-reqs.txt` | **`No known vulnerabilities found`** (`0` advisories, down from `11`; `langgraph>=1.0.10`, `pytest>=9.0.3`, `pytest-asyncio>=1.0.0`) | **VERIFIED (`0` CVEs, RC1)** |
| Playwright Live Browser E2E | `apps/web/tests/playwright_e2e_journeys.spec.ts` (`@playwright/test` + `/usr/bin/google-chrome` vs PG16 + FastAPI + `next start`) | **`5 passed, 0 failed (11.1s)`** across all 5 journeys (0 console/hydration/404/5xx errors; 5 real UI/API bugs fixed) | **VERIFIED LIVE (RC1)** |
| Post-Deadlock-Fix `pytest` (`fix/rc1-guardian-deadlock`) | `DATABASE_URL=... uv run pytest -q` (ephemeral `postgres:16-alpine` @ `55449`) | **`354 passed, 3 skipped, 3 warnings in 30.72s`** (`0` failures; `test_parallel_payment_proposal_idempotency` + 10 stress tests in `test_rc1_deadlock_stress.py` PASS) | **VERIFIED (PG16)** |
| Concurrency Stress Suite (3× PG16) | `uv run pytest -v tests/concurrency/` (3 consecutive runs @ `55447`) | **`18 passed` × 3** (`4.92s`, `4.98s`, `4.90s`; `2/10/50/100` identical, distinct-key burst, multi-tenant, budget exhaustion, rollback/timeout, concurrent `OutboxWorker`) | **VERIFIED (3× PG16)** |
| Failure Injection & Load Baseline | `tests/integration/test_rc1_failure_injection.py`, `aegis_fi` Compose drill, `tests/load/load_benchmark.py` | Failure injection `4/4` PASS + `/ready` `200->503->200` + worker restart recovery PASS; post-fix load baseline **`0.0%` err across all endpoints** (`POST /v1/guardian/proposals`: `63.35 RPS` @ `c=10`, `60.96 RPS` @ `c=25`, `50/50` `201`) | **VERIFIED (PG16)** |
| Live External APIs & Remote VPS | PayPal Sandbox / Stripe / OpenAI+Gemini+Anthropic / S3+R2 / SMTP / Remote Linux VPS | PayPal negative-path integration `13/13` PASS, `deploy/linux-staging/` `compose config` PASS; live PayPal Sandbox (`BLOCKED`, `PAYPAL_*` unset) & live VPS/external APIs not executed | **BLOCKED / NOT VERIFIED** |
