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
| Live Docker Compose Smoke | `POSTGRES_PORT=55432 REDIS_PORT=56379 API_PORT=18000 make compose-smoke` | Built integrated `migrate`, `api`, & `worker` images; `postgres` + `redis` healthy; `migrate` exit `0`; `GET /ready` `{"status":"ready","database":"connected","paypal_configured":false}`; `worker --healthcheck` exit `0`; clean teardown | **VERIFIED LIVE** |
| TypeScript SDK (`sdk-typescript`) | `npm run typecheck && npm test && npm audit --omit=dev` | `tsc --noEmit` + `tsc` build PASS; **`35 passed` (Vitest `4` suites)** + **`3 passed` (Node legacy)**; `npm audit --omit=dev`: **`found 0 vulnerabilities`** | **VERIFIED BY TEST** |
| Next.js Console (`apps/web`) | `npm run typecheck && npm run lint && npm test && node --test tests/console_e2e_journeys.test.mjs && npm run build && npm audit --omit=dev` | `tsc` PASS; `0` ESLint warnings/errors; **`3/3` unit + `7/7` E2E Node tests PASS**; `next build` **`24` routes PASS**; `npm audit --omit=dev`: **`2` transitive `postcss` advisories (`1` moderate, `1` high)** | **VERIFIED BY TEST** |
| Python Supply-Chain Audit | `uv export --frozen ... && uv run pip-audit -r /tmp/aegis-reqs.txt --desc` | Reports **`11` known vulnerabilities in `4` packages**: `langgraph 0.6.11` (`PYSEC-2026-83`), `langgraph-checkpoint 3.0.1` (`PYSEC-2026-2573/2574`), `langgraph-sdk 0.2.15` (`PYSEC-2026-2194/2575/4240`), `pytest 8.4.2` (`PYSEC-2026-1845`) | **VERIFIED (`11` ADVISORIES)** |
| Playwright Live Browser E2E | `apps/web/tests/playwright_e2e_journeys.spec.ts` (`90` lines) | `@playwright/test` absent from `apps/web/package.json`; not executed in live Chromium | **NOT VERIFIED** |
| Live External APIs & VPS | PayPal Sandbox / Stripe Billing+Provider / OpenAI+Gemini+Anthropic / S3+R2 / SMTP / Linux VPS | Mocked/stubbed locally only (`test_live_paypal_sandbox_oauth_and_order_roundtrip` skipped); live external credentials & VPS deploy not executed | **NOT VERIFIED** |
