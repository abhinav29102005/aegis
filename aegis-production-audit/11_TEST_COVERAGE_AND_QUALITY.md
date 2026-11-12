# 11 — Test Coverage & Evidence Quality Audit

**Observed Post-Sync Test Results (`2026-11-12` on `integration/nexus` @ `498043e`):**
- **Workspace PG16 Pytest (`packages/*/tests`, `modules/*/tests`, `services/*/tests`)**: **`228 passed, 0 failed, 0 skipped`** in `23.32s` (`87%` measured statement coverage across `10,490` statements via `pytest-cov`!).
- **Root M3 QA Harness (`uv run pytest tests/ -v`)**: **`14 passed, 2 failed`** in `7.44s`:
  - `tests/adversarial/test_rbac_negative_matrix.py`: **`3/3` PASS** (`6-role` negative matrix, `ADMIN->OWNER` blocked, `AGENT_SERVICE` blocked)
  - `tests/adversarial/test_security_adversarial.py`: **`6/6` PASS** (SSRF, quote tamper, webhook tamper, replay, policy & dispute prompt injection)
  - `tests/concurrency/test_concurrency_harness.py`: **`2/3` PASS** (`budget_reservation_race`, `parallel_proposal_idempotency`); **`test_outbox_lease_claim_concurrency` FAILED (`Total claimed: 60, unique: 20`)**
  - `tests/e2e/test_console_journeys_e2e.py`: **`1/1` PASS**
  - `tests/integration/test_sdk_parity_gate.py`: **`2/3` PASS** (verbatim `INTEGRATION_GUIDE.md` verifier & flow PASS); **`test_openapi_sdk_coverage_gate` FAILED (`75.0%` Py `72/96`, `79.2%` TS `76/96` vs `>=85%`)**
- **TypeScript SDK (`packages/sdk-typescript`)**: **`35 passed` (Vitest `4` suites)** + **`3 passed` (Node legacy test)** + **`tsc` build PASS**.
- **Next.js Console (`apps/web`)**: **`next lint` (`0` warnings/errors)** + **`3/3` unit (`format.test.mjs`)** + **`7/7` E2E journey (`console_e2e_journeys.test.mjs`)** + **`next build` (`24` static/dynamic pages) PASS**. (`@playwright/test` is NOT installed in `package.json`, so `playwright_e2e_journeys.spec.ts` has not executed in Chromium.)
- **Ruff (`uv run ruff check .`)**: **`79` lint errors** (M1 paths `0` errors; M3 added unused/unsorted imports, `2` `F821` undefined `Any` in `packages/sdk-python/tests/test_pagination.py`, `S102` `exec` in `test_sdk_parity_gate.py`, plus `1` pre-existing `BLE001` in `guardian/payments/coordinator.py:294`).
- **Live Infra Smoke (`work/m1` `d9ab7b8`)**: Docker Compose (`postgres` + `redis` + `migrate` + `api` + `worker`) + `backup_pitr.sh` + `restore_verify.sh` **VERIFIED LIVE**.

---

## 1. Critical Unverified / Still-Failing Gaps Revealed by Sync Testing
1. **Unpushed M2 Financial Tests:** No backend negative tests exist yet for `approved=False` reserving `0`, `JPY`/`KWD` 0/3-decimal PayPal formatting, 1,000-case Guardian <-> GhostPay `"policy-v1"` property parity, or DisputeOS failed PayPal submission staying `APPROVED_FOR_SUBMISSION` because `work/m2-financial-forensics-ai` is not pushed.
2. **M3 Concurrency Fixture Bug (`test_outbox_lease_claim_concurrency`):** Fixture opens SQLite WAL (`sqlite:///concurrency.db`) instead of `AEGIS_TEST_POSTGRES_URL`, failing disjoint lease claims (`60` vs `20`) because SQLite does not support `FOR UPDATE SKIP LOCKED`. *(PG16 worker test `test_platform_repo.py` passes cleanly.)*
3. **M3 OpenAPI Coverage Gate Drift:** M1 expanded OpenAPI from `78` to `96` ops, lowering M3 SDK parity to `75.0%` / `79.2%` until M1 routes are wrapped in `sdk-python` & `sdk-typescript`.
4. **Root `tests/` Excluded from Default `pytest`:** `pyproject.toml` `[tool.pytest.ini_options].testpaths` does not yet include `"tests"`, so default `uv run pytest` skips `tests/{adversarial,concurrency,e2e,integration}`.
5. **External Network Flows Remain `NOT VERIFIED`:** Live PayPal Sandbox, live Stripe Billing webhooks, live S3/R2 remote upload, live LLM API calls, and Playwright live Chromium execution.
