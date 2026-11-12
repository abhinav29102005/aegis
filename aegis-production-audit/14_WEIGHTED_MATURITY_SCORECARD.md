# 14 — Engineering Maturity Scorecard (`90.0 / 100`)

**Progression:** Baseline (`1be376e`): `43.5 / 100` -> M1+M3 (`498043e`): `72.5 / 100` -> M1+M2+M3 (`ebe4069`): `87.0 / 100` -> **Post-RC1 Dual-Computer Integration (`integration/nexus` @ `f8768bd`, `2026-11-12`): `90.0 / 100` (`+46.5 pts` vs Baseline, `+3.0 pts` vs `ebe4069`)**  
**Scoring Rule:** Earned credit reflects strictly verified integrated behavior and observed post-merge runtime evidence (`-10.0 pts` withheld for the `tenants FOR UPDATE` burst deadlock in `submit_proposal()`, `BLOCKED` live PayPal Sandbox, and `NOT VERIFIED` remote VPS/Stripe/LLM/S3/external audits).

---

## 1. Weighted Category Breakdown (`2026-11-12` Post-RC1)

| # | Category | Weight | Baseline | M1+M2+M3 | Current (`RC1`) | % of Max | Key Observed Evidence (Verified Gains vs Remaining Blockers / Open Items) |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | **Core financial correctness** | 15 | 7.5 | 13.5 | **13.0** | 86.7% | `+` `tests/concurrency/test_rc1_financial_invariants.py` (`8/8` on C2 branch); `GAP-001/005/011/012/016` verified.<br>`-` **New RC1 blocker:** `POST /v1/guardian/proposals` hits `DeadlockDetected` (`tenants FOR UPDATE` lock upgrade in `append_financial_event()`) under burst concurrency (`test_parallel_payment_proposal_idempotency` failed in post-merge PG16 `pytest`); live PayPal Sandbox `BLOCKED`. |
| 2 | **Security and tenant isolation** | 15 | 6.5 | 13.5 | **14.5** | 96.7% | `+` **`pip-audit`: `0` CVEs** (`11` resolved); **`apps/web` `npm audit --omit=dev`: `0` CVEs** (`next@16.4.6`); `sdk-typescript`: `0` CVEs; `20/20` adversarial tests PASS (`+11` in `test_rc1_security_regressions.py`); non-root/digest Dockerfiles + `cap_drop: ALL`.<br>`-` External pen-test not yet performed. |
| 3 | **Reliability and recovery** | 12 | 5.5 | 11.0 | **11.5** | 95.8% | `+` Live Compose failure injection (`aegis_fi`): DB stop/start `/ready` (`200->503->200`), worker `--healthcheck` across restart, `4/4` `test_rc1_failure_injection.py` PASS; post-response `session.commit()` race fixed in `auth_orgs.py`, `guardian_db.py`, `disputeos_db.py`.<br>`-` Live S3/R2 WORM & proposal burst deadlock fix pending. |
| 4 | **Backend / API maturity** | 10 | 5.5 | 9.0 | **9.0** | 90.0% | `+` Read/replay load baseline: `117.82–1,281.95 RPS` with `0.0%` errors at `c=10/25`.<br>`-` `POST /v1/guardian/proposals` `98.0%` burst error (`DeadlockDetected`) under `c=10/25`. |
| 5 | **Database integrity** | 8 | 4.5 | 7.5 | **7.5** | 93.8% | `+` `37` ORM tables (`0001`–`0003` PG16), PG `financial_events` immutability triggers, snapshot/trace/DNA/LLM tables verified end-to-end.<br>`-` `append_financial_event()` `tenants FOR UPDATE` lock ordering needs fix to eliminate FK `FOR KEY SHARE` deadlock. |
| 6 | **Frontend product usability** | 8 | 2.5 | 6.5 | **7.5** | 93.8% | `+` **5/5 real Chromium Playwright E2E journeys PASS (11.1s)** with 0 console/hydration/404/5xx errors; fixed ES2024 `v`-flag `<input pattern>`, `/v1/billing/subscription`, `EvidenceSourceType` options, & `/icon.svg`.<br>`-` 8 dev-only `minimatch` advisories in `eslint-config-next`. |
| 7 | **Developer experience and SDKs** | 7 | 2.5 | 6.5 | **6.5** | 92.9% | `+` `aegis-sdk` & `@aegis-platform/sdk` `97/99` (`98.0%`) OpenAPI parity, `0` Ruff errors, `35/35` Vitest + `3/3` Node + `tsc` PASS (`0` CVEs).<br>`-` Live PyPI & npm publish `NOT VERIFIED`. |
| 8 | **Payment integrations** | 7 | 2.5 | 4.5 | **4.5** | 64.3% | `+` `13/13` `test_rc1_paypal_negative_paths.py` + `11 passed, 1 skipped` `packages/paypal/tests/` PASS.<br>`-` Live PayPal Sandbox (`PAYPAL_*` unset) **BLOCKED / NOT VERIFIED**; live Stripe `NOT VERIFIED`. |
| 9 | **Test effectiveness** | 6 | 3.0 | 5.5 | **5.5** | 91.7% | `+` `343 passed, 1 failed, 3 skipped` post-merge PG16 `pytest`, `5/5` Chromium Playwright E2E, `4/4` failure injection, `13/13` PayPal negative paths, load harness (`tests/load/load_benchmark.py`).<br>`-` `1` PG16 concurrency failure (`test_parallel_payment_proposal_idempotency`) & `3` skipped external tests. |
| 10 | **Observability and operations** | 5 | 1.5 | 4.5 | **4.5** | 90.0% | `+` Full-stack `make compose-smoke` (including `web`) PASS post-merge; `/metrics` Prometheus, JSON logs, `deploy/linux-staging/` `ports: !override` & Nginx hardening verified.<br>`-` Remote Linux VPS + Certbot TLS runtime `NOT VERIFIED`. |
| 11 | **Compliance & governance readiness** | 4 | 1.5 | 3.0 | **3.5** | 87.5% | `+` `RC1_COMPLIANCE_REVIEW_CHECKLIST.md` + `13/13` GDPR/DPDPA/SSRF/KMS/webhook tests PASS.<br>`-` External legal counsel sign-off, DPDPA statutory copy updates, & SOC 2 Type II `NOT VERIFIED`. |
| 12 | **Commercial readiness** | 3 | 0.5 | 2.0 | **2.5** | 83.3% | `+` Billing UI/API aligned (`/v1/billing/subscription`), `0` prod CVEs, E2E & Compose smoke green.<br>`-` Live Stripe API, live PayPal Sandbox, & proposal deadlock fix pending before external beta. |
| **TOTAL** | **100** | **43.5** | **87.0** | **90.0** | **90.0%** | **All CVE, Chromium E2E, failure-injection, & full-stack Compose gates PASS; `NO-GO FOR EXTERNAL BETA` until proposal deadlock & PayPal Sandbox are resolved.** |

---

## 2. Updated Stage Readiness Levels (`2026-11-12` Post-RC1)

| Target Stage | Baseline | M1+M2+M3 | Current (`RC1`) | Remaining Verification / Release Conditions |
| :--- | :--- | :--- | :--- | :--- |
| **1. Local Development** | `72%` | `98%` | **READY (`99%`)** | `0` Ruff, `0` prod CVEs, `5/5` Chromium Playwright E2E, `make compose-smoke` PASS. |
| **2. Internal Staging** | `45%` | `88%` | **READY (`92%`, Mocked)** | `deploy/linux-staging/` config validated; deploy to live Linux VPS + fix `tenants FOR UPDATE` deadlock. |
| **3. Public Beta (Sandbox)** | `28%` | `72%` | **NO-GO (`76%`)** | **Requires:** (1) fix `tenants FOR UPDATE` deadlock (`submit_proposal()`/`append_financial_event()`), (2) live PayPal Sandbox roundtrip (`PAYPAL_*` creds). |
| **4. Limited Commercial Launch** | `18%` | `58%` | **NOT READY (`62%`)** | Requires above + live Stripe Billing + live LLM evals + remote Linux VPS TLS + external legal counsel sign-off. |
| **5. Enterprise Production** | `10%` | `45%` | **NOT READY (`48%`)** | Requires third-party penetration test, post-fix load re-benchmark, & SOC 2 Type II program execution. |
| **6. Regulated MoR / Wallets** | `4%` | `4%` | **NOT READY (`4%`)** | Unchanged — DO NOT self-build regulated funds custody without licensed PSP/BaaS partners & regional licenses. |
