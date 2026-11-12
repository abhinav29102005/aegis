# 11 — Test Coverage & Evidence Quality Audit

**Observed Post-RC1 Verification Results (`2026-11-12` on `fix/rc1-guardian-deadlock`):**
- **Ruff Static Lint (`uv run ruff check .`):** **`All checks passed!`** (`0` lint errors across entire repository — down from `79`).
- **Full Python Workspace + Root QA Suite vs `postgres:16-alpine` (`uv run pytest -q`):**
  - **Result:** **`354 passed, 3 skipped, 0 failed` in `30.72s`!**
  - **Measured Statement Coverage:** **`90%` overall across `20,241` statements (`2,078` missed; `81` files skipped at `100%` coverage)**!
  - **Notable Verified Subsets Included in `354 passed`:**
    - Guardian <-> GhostPay `"policy-v1"` property parity (`modules/ghostpay/tests/test_forensics_hardening.py`): **`1,000 / 1,000` cases, `0` mismatches**.
    - Concurrency Stress Suite (3 consecutive runs): **`18 passed` × 3** (`test_rc1_deadlock_stress.py` + `test_concurrency_harness.py`).
    - Failure injection: **`4/4` PASS** (`test_rc1_failure_injection.py`).
    - PayPal negative-path suite: **`13/13` PASS** (`test_rc1_paypal_negative_paths.py`).
    - Security regressions & RBAC: **`20/20` PASS** (`test_rc1_security_regressions.py` + `test_rbac_negative_matrix.py`).
    - OpenAPI SDK parity gate: **`97/99` (`98.0%`)** in Python and TypeScript.
- **Live PayPal Sandbox Verification (`packages/paypal/tests/test_live_sandbox_optional.py`):**
  - Executed live against `api-m.sandbox.paypal.com` with real credentials: **`12 passed in 3.52s`** (OAuth token generation, order creation, capture pre-check, and webhook signature verification).
- **Synthetic Load Benchmark (`tests/load/load_benchmark.py`):**
  - Executed against PostgreSQL 16 at `c=10` and `c=25`: **`0.0%` error rate across all endpoints** (`POST /v1/guardian/proposals`: `63.35 RPS` @ `c=10`, `60.96 RPS` @ `c=25`, `50/50` HTTP 201).
- **Chromium Playwright E2E (`apps/web/tests/playwright_e2e_journeys.spec.ts`):**
  - Real browser execution: **`5 passed, 0 failed (11.1s)`** with 0 console, 0 hydration, 0 404, and 0 5xx errors.
- **Supply Chain & CVE Hygiene:**
  - `pip-audit`: **`0` vulnerabilities** (all `11` dependencies upgraded).
  - `npm audit --omit=dev`: **`0` vulnerabilities** (Next.js upgraded to `16.4.6`; `sdk-typescript` clean).
- **Live Azure Staging Deployment (`20.124.91.36`):**
  - API live at `https://api-staging.abhinavkumarsingh.tech` (`/health` & `/ready` return `200 OK`).
  - Web console live at `http://20.124.91.36/login` (`200 OK`).

---

## Remaining `NOT VERIFIED` Test Boundaries
1. **Interactive PayPal Buyer Approval:** Testing the manual buyer authorization flow in an interactive browser window against PayPal Sandbox and confirming real-time webhook push from PayPal's servers.
2. **Third-Party Live Endpoints:** Live Stripe Billing test checkout, live S3/R2 bucket uploads, live LLM API evals (OpenAI/Anthropic/Gemini), and live SMTP delivery.
3. **External Governance & Compliance:** External legal sign-off on `/legal/*` and SOC 2 Type II audit readiness.
