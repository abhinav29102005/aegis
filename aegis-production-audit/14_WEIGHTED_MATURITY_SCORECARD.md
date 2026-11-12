# 14 — Engineering Maturity Scorecard (`72.5 / 100`)

**Baseline (`1be376e`):** `43.5 / 100` -> **Post-M1 & M3 Sync (`integration/nexus` @ `498043e`):** **`72.5 / 100` (`+29.0 pts`)**  
**Scoring Rule:** Earned credit reflects strictly verified code behavior and runtime test evidence (`work/m2-financial-forensics-ai` is NOT yet pushed, so zero credit is awarded for unpushed M2 fixes).

---

## 1. Weighted Category Breakdown (`498043e`)

| # | Category | Weight | Baseline | Current | % of Max | Key Observed Evidence (Verified Gains vs Remaining Gaps) |
|---:|---|---:|---:|---:|---:|---|
| 1 | **Core financial correctness** | 15 | 7.5 | **7.5** | 50.0% | `=` Unchanged (`M2` unpushed). Atomic PG reservations & contracts intact; `approved=False` STILL approves payments (`guardian_db.py:433`, `service.py:290`), JPY/BHD 2-decimal bug, missing daily/agent-status checks, unbound `approval.payment_intent_id`, & `"policy-v1"` drift remain open. |
| 2 | **Security and tenant isolation** | 15 | 6.5 | **12.5** | 83.3% | `+` GhostPay RBAC (`app.py`), outbound SSRF IPv4/IPv6 guard, `ADMIN->OWNER` blocked + invite consent, SHA-256 Redis rate limiter, `.env` aliases & security posture guard, active principal checks, sanitized 403/503/webhooks, `HttpOnly` cookie BFF + CSP headers, MFA/OIDC/KMS/erasure.<br>`-` M2 DisputeOS artifact cross-case IDOR & unmounted module routers remain. |
| 3 | **Reliability and recovery** | 12 | 5.5 | **9.5** | 79.2% | `+` Worker `locked_at` leases + reaper, `FOR UPDATE SKIP LOCKED` reconcile, DLQ `attempts=0` reset, `asyncio.Semaphore` dispatch, S3/R2 WORM + streaming 10MB cap, live `backup_pitr.sh`/`restore_verify.sh` drill passed.<br>`-` M2 GhostPay RAM split, sync DB held across PayPal `await`, M3 SQLite concurrency fixture bug. |
| 4 | **Backend / API maturity** | 10 | 5.5 | **7.5** | 75.0% | `+` `85` paths / `96` ops (billing, privacy, MFA/SSO, invitations, audit export), `/metrics` + OTel, PayPal `event.id` dedup + lazy dispute webhook dispatch, clean M1 pagination & error sanitization.<br>`-` M2 `guardian_db`/`disputeos_db` unhandled `500`s, missing `/resolve`, `IdempotencyRecordRow` unused. |
| 5 | **Database integrity** | 8 | 4.5 | **7.0** | 87.5% | `+` `37` ORM tables (`0003` migration tested PG16), PG `BEFORE UPDATE OR DELETE` trigger on `financial_events`, `FOR UPDATE` sequence lock, `spending_passport_snapshots` + trace/DNA/LLM tables, fixed `save_dispute_case`/`save_evidence`, `pool_recycle`.<br>`-` M2 not yet reading snapshots / trace tables; `0001` dynamic `create_all`. |
| 6 | **Frontend product usability** | 8 | 2.5 | **6.5** | 81.3% | `+` All 5 broken UI contract bugs fixed (`CAPTURE_PENDING`, `passports:write`, 6 canonical `Role`s, `DisputeAnalysis`, timeline), `HttpOnly` cookie BFF, `/onboarding`, `/status`, `/legal/*`, Billing/Privacy tabs, `next build` (`24` pages) + `10` Node tests pass.<br>`-` Live Chromium `@playwright/test` absent from `package.json`; M2 backend actions pending. |
| 7 | **Developer experience and SDKs** | 7 | 2.5 | **5.5** | 78.6% | `+` `AEGIS-Signature: t=,v1=` unified across worker/Py/TS/docs (verbatim `INTEGRATION_GUIDE` tests pass!), `AsyncAegisClient`, TS `detail` parser fixed, Edge WebCrypto, LangGraph/OpenAI/Vercel AI middlewares.<br>`-` `75.0%` Py (`72/96`) & `79.2%` TS (`76/96`) < `85%` gate due to M1's new routes; Ruff lint cleanup needed. |
| 8 | **Payment integrations** | 7 | 2.5 | **2.5** | 35.7% | `=` Unchanged (`M2` unpushed). PayPal still mocked only; live Sandbox `NOT VERIFIED`; JPY/BHD 2-decimal bug, fake DisputeOS `SUBMITTED`, missing refunds/Stripe/AP2/x402. |
| 9 | **Test effectiveness** | 6 | 3.0 | **4.5** | 75.0% | `+` `228 passed` PG16 pytest (`87%` coverage via `pytest-cov` across `10,490` stmts), `35` TS Vitest, `10` Web Node, `14/16` M3 QA harness (`tests/{adversarial,concurrency,e2e,integration}`).<br>`-` `test_outbox_lease_claim_concurrency` SQLite FAIL, `test_openapi_sdk_coverage_gate` FAIL, Ruff `79` errors, live Chromium/PayPal/LLM unrun. |
| 10 | **Observability and operations** | 5 | 1.5 | **4.5** | 90.0% | `+` Non-root containers, worker `--healthcheck`, `127.0.0.1:5432`, Prometheus `/metrics`, OTel, Grafana/alerts, Linux VPS manifests retiring Android staging, live Compose + restore drill passed, SHA-pinned CI + `gitleaks`/`trivy`/`pip-audit`.<br>`-` Live multi-node VPS & Alertmanager runtime unrun. |
| 11 | **Compliance & governance readiness** | 4 | 1.5 | **3.0** | 75.0% | `+` GDPR/DPDPA export + crypto-shredding erasure APIs, EU/IN/US residency configs, `/legal/{terms,privacy,dpa}`, `NON_CUSTODIAL_PERIMETER.md`, PG audit triggers.<br>`-` Legal counsel review, SOC 2 Type II, & `/register` KYB pending. |
| 12 | **Commercial readiness** | 3 | 0.5 | **2.0** | 66.7% | `+` Stripe `/v1/billing/*` metering/plans, `/onboarding`, `/status`, legal docs, `/settings` Billing & Privacy UI.<br>`-` Live Stripe API & SMTP email delivery `NOT VERIFIED`. |
| **TOTAL** | **100** | **43.5** | **72.5** | **72.5%** | **Platform, DB, Worker, UI & SDK spine near launch-ready; commercial/money safety blocked on missing M2 (`work/m2`) + 3 M1/M3 sync fixes.** |

---

## 2. Updated Stage Readiness Levels (`498043e`)

| Target Stage | Baseline | Current (`498043e`) | Blocking Conditions Remaining |
| :--- | :--- | :--- | :--- |
| **1. Local Development** | `72%` | **READY (`88%`)** | Clean up M3 `79` Ruff lint errors, wrap M1 routes in SDKs (`>=85%`), add `tests/` to `pyproject.toml`, fix `concurrency_env` PG16 usage. |
| **2. Internal Staging** | `45%` | **PARTIAL (`72%`)** | Infra & UI contracts work; **blocked on M2 (`approved=False`, DisputeOS submit, GhostPay split-brain, PayPal fixes)**. |
| **3. Public Beta (Sandbox)** | `28%` | **NOT READY (`55%`)** | Requires M2 merge + M1/M3 SDK/Ruff sync fixes + live PayPal Sandbox verification + live Chromium Playwright run. |
| **4. Limited Commercial Launch** | `18%` | **NOT READY (`38%`)** | Requires M2 + live Stripe Billing & LLM verification + live Linux VPS deployment + legal counsel sign-off. |
| **5. Enterprise Production** | `10%` | **NOT READY (`28%`)** | Requires Horizon 4 M2 multi-PSP (`Stripe`/AP2/TAP/x402/MCP), external pen-test, & SOC 2 Type II controls. |
| **6. Regulated MoR / Wallets** | `4%` | **NOT READY (`4%`)** | Unchanged — DO NOT self-build without licensed PSP/BaaS partners & regional regulatory licenses. |
