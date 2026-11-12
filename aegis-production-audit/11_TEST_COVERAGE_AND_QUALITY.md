# 11 — Test Coverage & Evidence Quality Audit

**Observed Post-Integration Final Verification Results (`2026-11-12` on `integration/nexus`, after ALL edits including `pyproject.toml` `testpaths`):**
- **Ruff Static Lint (`uv run ruff check .`):** **`All checks passed!`** (`0` lint errors across entire repository — down from `79`).
- **Full Python Workspace + Root QA Suite vs `postgres:16-alpine` (`uv run pytest -q --cov=packages --cov=modules --cov=services --cov-report=term-missing:skip-covered`):**
  - **Result:** **`313 passed, 1 skipped` (`packages/paypal/tests/test_live_sandbox_optional.py::test_live_paypal_sandbox_oauth_and_order_roundtrip`), `0 failed` in `42.34s`!**
  - **Measured Statement Coverage:** **`90%` overall across `20,241` statements (`2,078` missed; `81` files skipped at `100%` coverage)**!
  - **Notable Verified Subsets Included in `313 passed`:**
    - Guardian <-> GhostPay `"policy-v1"` property parity (`modules/ghostpay/tests/test_forensics_hardening.py`): **`1,000 / 1,000` cases, `0` mismatches**.
    - Root QA Harness (`tests/` now included in `pyproject.toml` `testpaths`): **`16 / 16` PASS** — 6-role RBAC negative matrix (`3/3`), adversarial SSRF/quote-tamper/webhook-tamper/replay/prompt-injection (`6/6`), concurrency race & outbox lease harness (`3/3`), console journey E2E (`1/1`), OpenAPI SDK parity gate (`97/99` = `98.0%` Py & TS) + verbatim `INTEGRATION_GUIDE.md` checks (`3/3`).
    - Multi-rail providers (`modules/agentpay-guardian/tests/test_providers.py`), MCP + copilot (`test_copilot_mcp.py`), DisputeOS AI evals (`modules/disputeos/tests/test_ai_eval.py`), PG16 concurrency/migration triggers (`test_postgres_integration.py`, `test_database.py`, `test_platform_repo.py`), & worker DLQ/leases (`test_worker.py`).
- **Live Docker Compose Smoke (`POSTGRES_PORT=55432 REDIS_PORT=56379 API_PORT=18000 make compose-smoke`):** **`exit 0`** — rebuilt `migrate`, `api`, & `worker` images from integrated tree, migrated PG16 + Redis, verified `/ready` `{"status":"ready","database":"connected","paypal_configured":false}` and `worker --healthcheck`.
- **TypeScript SDK (`packages/sdk-typescript`):** `tsc` typecheck + build PASS, **`35 passed` (Vitest `4` files)** + **`3 passed` (Node legacy)**, `npm audit --omit=dev` **`0` vulnerabilities**.
- **Next.js Console (`apps/web`):** `tsc --noEmit` PASS, `next lint` (`0` warnings/errors), **`3/3` unit (`format.test.mjs`)** + **`7/7` Node E2E (`console_e2e_journeys.test.mjs`)**, `next build` **`24` routes PASS**, `npm audit --omit=dev` reports `2` transitive `postcss` advisories (`1` moderate, `1` high).
- **`pip-audit` (`uv run pip-audit -r /tmp/aegis-reqs.txt --desc`):** Reports `11` known vulnerabilities across `4` packages (`langgraph 0.6.11`, `langgraph-checkpoint 3.0.1`, `langgraph-sdk 0.2.15`, `pytest 8.4.2`).

---

## Remaining `NOT VERIFIED` Test Boundaries
1. **Live PayPal Sandbox (`test_live_sandbox_optional.py`):** Explicitly skipped without sandbox client credentials (`1 skipped`).
2. **Live Stripe Billing / Provider, Live S3/R2 Upload, Live LLM API Calls, Live SMTP:** Tested with `httpx` mocks / local disk stubs; unrun against real third-party endpoints (`NOT VERIFIED`).
3. **Live Chromium Browser E2E (`playwright_e2e_journeys.spec.ts`):** Spec file (`90` lines) present, **`@playwright/test` absent from `apps/web/package.json`** (`NOT VERIFIED` in headless browser).
4. **Load / Saturation Benchmarks & Live Linux VPS Deploy:** Capacity/RPS latency benchmarks not yet executed (`NOT VERIFIED`).
