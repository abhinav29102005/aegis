# 17 — Three-Computer Parallel Execution Tracker (`2026-11-12` Sync Status)

**Purpose:** Track merge synchronization across Computer 1 (`work/m1-platform-security-infra`), Computer 2 (`work/m2-financial-forensics-ai`), and Computer 3 (`work/m3-web-sdks-qa`) into `integration/nexus`.

---

## 1. Branch Synchronization Matrix (`2026-11-12`)

| Machine / Branch | Remote Status (`origin`) | Merge into `integration/nexus` | Scope & Verified Health |
| :--- | :--- | :--- | :--- |
| **Computer 1 (`work/m1-platform-security-infra`)** | **PUSHED (`d9ab7b8`)** | **MERGED (`0` conflicts)** | `59` files (`security`, `database`, `worker`, API gateway/rate-limit/billing/erasure/webhooks, `deploy/`, `scripts/`, `ci.yml`). PG16 tests `70/70`, live Compose + Redis + PG restore drill PASSED. |
| **Computer 2 (`work/m2-financial-forensics-ai`)** | **NOT ON `origin` (UNPUSHED)** | **PENDING** | Owns `packages/contracts`, `packages/paypal`, `modules/{agentpay-guardian,ghostpay,disputeos}`, `adapters.py`, `guardian_db.py`, `disputeos_db.py`. Zero commits pushed to remote yet. |
| **Computer 3 (`work/m3-web-sdks-qa`)** | **PUSHED (`4b5d52f`)** | **MERGED (`0` conflicts)** | `82` files (`apps/web/`, `packages/sdk-python/`, `packages/sdk-typescript/`, `docs/`, `README.md`, `tests/`). TS SDK `35/35` Vitest, Web `next build` (`24` pages) & `10` Node tests PASS; needs `79` Ruff fixes, SDK parity bump (`75%`/`79.2%` -> `85%`), & `concurrency_env` PG16 fixture fix. |

---

## 2. Exact Next Sync & Release Checklist

1. **Computer 2 Push & Merge:** Push `work/m2-financial-forensics-ai` -> inspect write boundaries (`0` overlap expected with M1 `d9ab7b8` & M3 `4b5d52f`) -> merge into `integration/nexus` (`Step 2` of release choreography).
2. **Post-Merge Stabilization Patch (Small Integration Cleanup PR on `integration/nexus`):**
   - Wrap M1's `18` new routes (+ any new M2 routes like `/disputeos/cases/{id}/resolve`) in `packages/sdk-python` & `packages/sdk-typescript` so `test_openapi_sdk_coverage_gate` passes `>= 85%`.
   - Update `tests/concurrency/test_concurrency_harness.py` to use `AEGIS_TEST_POSTGRES_URL` when configured so `test_outbox_lease_claim_concurrency` exercises real PG16 `SKIP LOCKED`.
   - Fix `79` Ruff lint findings (especially `test_pagination.py` `F821` `Any` & unused imports) + add `"tests"` to `[tool.pytest.ini_options].testpaths` in `pyproject.toml`.
   - Add `@playwright/test` to `apps/web/package.json` & execute `playwright_e2e_journeys.spec.ts` live against Docker Compose (`api` + `worker` + `postgres` + `redis` + `web`).
   - Run `rmdir packages/ui` cleanly.
3. **Live External Gate:** Execute credentialed PayPal Sandbox E2E, Stripe Billing test-mode webhooks, S3/R2 remote upload, and live LLM evals before staging sign-off.
