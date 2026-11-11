# 11 — Test Coverage & Evidence Quality Audit

**Observed Test Counts (`2026-11-12` Verification):**
- Python suite (SQLite / mocked transports): **`143 passed, 1 skipped`** (`pytest -q`, `pytest-cov` not installed in venv — line/branch % unmeasured).
- PostgreSQL 16 test (`test_postgres_integration.py`): **Previously verified passing (`144 passed`) against ephemeral `postgres:16-alpine` prior to final report doc edit; skipped locally when `AEGIS_TEST_POSTGRES_URL` is unset.**
- TypeScript SDK: **`3 passed, 0 failed`** (`node --test tests/sdk.test.mjs`, mocked `fetch`).
- Web Console: **`3 passed, 0 failed`** (`node --test tests/format.test.mjs` — string formatting helpers only).
- **Empty Root Placeholder Suites (`0` tests):** `tests/adversarial/`, `tests/concurrency/`, `tests/e2e/`, `tests/integration/`.

---

## 1. Critical Tests Passing While Production Workflows Are Broken!

These observed defects prove why test count (`149` total) masks serious production failures:
1. **`apps/web` `npm run build` + `3` format tests pass while 5 core screens fail at runtime:** Capture button is unreachable (`BUYER_APPROVED` vs `CAPTURE_PENDING`), Merchant creation is hidden (`merchants:write`), Developer/Settings role dropdowns `422`, Dispute summary/contradictions render blank, GhostPay timeline timestamps/actors render `undefined`. Zero component or Playwright E2E tests exist.
2. **Guardian & Platform API tests pass while `approved: false` still authorizes payment:** Both `test_guardian.py` and `test_api_platform.py` only ever test `approved=True` (`approve_proposal`), never testing human rejection (`{"approved": false}`)!
3. **TypeScript SDK tests pass (`3/3`) despite broken FastAPI error parser:** `tests/sdk.test.mjs:33` mocks `{error_code, message}` instead of FastAPI's `{detail: {error, message}}`, leaving `src/index.ts:156-160` unverified against real `aegis_api`.
4. **DisputeOS tests pass (`14/14`) while `/submit` falsely marks cases `SUBMITTED`:** Tests assert `response["result"]["submitted"] is False` yet accept `case.status == SUBMITTED` — hiding the fact that zero PayPal submission occurred.
5. **Worker tests pass (`2/2`) against SQLite:** Skip PostgreSQL `FOR UPDATE SKIP LOCKED`, leave crash-recovery (`PROCESSING` lease timeout) and multi-worker competing `reconcile_pending_payments` completely untested, and mask outbound SSRF.
6. **GhostPay standalone API tests (`test_ghostpay_api.py`, `test_time_machine.py`) bypass platform `app.py` RBAC:** Never catch that `create_app()` mounts GhostPay without `Permission.GHOSTPAY_READ` / `GHOSTPAY_SIMULATE`.
7. **PayPal client tests (`5/5` mocked):** Never test `PayPalSandboxClient.verify_webhook_signature`, never run against live `api-m.sandbox.paypal.com`, and only test `USD` (missing `JPY`/`KWD` decimal corruption).

---

## 2. Coverage Matrix by Quality Dimension

| Dimension | Current State | Verdict |
| :--- | :--- | :--- |
| Line / Branch Coverage Measurement | `pytest-cov` missing from workspace deps; zero HTML/XML coverage gates in CI | **MISSING** |
| Negative & Adversarial Security Tests | Strong in `ghostpay/tests/test_ghostpay_hardening.py` + `test_security.py`; missing SSRF, `ADMIN->OWNER`, `approved=False`, BOLA artifact download, JWT header collision, `localStorage`/XSS | **PARTIAL** |
| Property-Based / Mutation Testing | Zero `hypothesis` / `mutmut` / fuzzing tests on money math, state transitions, or `PolicyEngine` parity | **MISSING** |
| Browser E2E Coverage | **0 Playwright/Cypress tests** (`tests/e2e/` empty) | **MISSING (`HIGH`)** |
| Provider Contract Tests | Mocks are handwritten; zero schema validation against official PayPal OpenAPI / live sandbox smoke workflow | **MISSING (`HIGH`)** |
| High-Concurrency & Crash-Recovery Stress | Max `2` threads in reservation tests (`test_database.py`, `test_postgres_integration.py`); zero worker crash-kill recovery or connection pool exhaustion tests | **WEAK** |

---

## 3. Mandatory Non-Negotiable Financial Invariants & Required Tests

| Invariant | Currently Proven? | Required Targeted Automated Test |
| :--- | :--- | :--- |
| **1. No transaction exceeds passport/daily/monthly limits even under N-way concurrency** | **Partially** (2-thread total budget only; daily/monthly unimplemented) | 20-worker PG16 asyncio/multiprocess barrier test racing total + daily + per-tx caps -> `sum(held + spent) <= cap` |
| **2. Human rejection (`approved=False`) NEVER authorizes, reserves, or captures** | **FAILING TODAY** | API integration test calling `POST /v1/guardian/proposals/{id}/approve` with `{"approved": false}` asserting `reserved_minor == 0` & capture `409` |
| **3. Approval is strictly single-use & bound to exact `intent_id`, merchant, amount, currency & unexpired quote** | **Partially** (`intent_id` unbound today) | Negative test passing Intent A's `approval_id` against Intent B with identical quote asserting `422 ApprovalMismatchError` |
| **4. One approved order cannot produce unintended duplicate captures** | **Partially** (`PayPal-Request-Id` mocked) | Concurrent double `POST /payments/{id}/capture` race on PG16 asserting at most 1 external PayPal `/capture` call |
| **5. No tenant or unprivileged role can access or mutate cross-tenant/protected resources** | **Partially** (GhostPay RBAC, ADMIN->OWNER & artifact BOLA fail) | Full RBAC x Role (`6` roles x `78` ops) parametrized matrix test verifying expected `200`/`403` + cross-tenant `403` without UUID leak |
| **6. Outbound webhook delivery blocks internal networks & survives worker `SIGKILL` mid-batch** | **NOT TESTED / FAILING** | SSRF IPv4/IPv6/redirect test (`127.0.0.1`, `169.254.169.254`, `postgres:5432`) + crash test reclaiming stuck `PROCESSING` rows |
| **7. Baseline GhostPay replay matches Guardian's live `"policy-v1"` decision 100% of the time** | **FAILING ON BOUNDARIES** | Cross-module property test generating 1,000 random (`amount`, `threshold`, `allowlisted`, `expired`) cases asserting identical Guardian vs GhostPay outcomes |
| **8. Synthetic disputes & unsubmitted drafts can NEVER reach `SUBMITTED` or PayPal** | **FAILING ON DRAFT `/submit`** | Negative test asserting `/submit` returns `501`/`400` or keeps `APPROVED_FOR_SUBMISSION` until HTTP `200/201` from PayPal Disputes API |

