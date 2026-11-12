# 14 — Engineering Maturity Scorecard (`96.0 / 100`)

**Progression:** Baseline (`1be376e`): `43.5 / 100` -> M1+M3 (`498043e`): `72.5 / 100` -> M1+M2+M3 (`ebe4069`): `87.0 / 100` -> RC1 Integration (`f8768bd`): `90.0 / 100` -> Deadlock Fix (`377e52e`): `94.0 / 100` -> **Live PayPal Sandbox + Azure Staging VM (`fix/rc1-guardian-deadlock`, `2026-11-12`): `96.0 / 100` (`+52.5 pts` vs Baseline, `+6.0 pts` vs `f8768bd`)**  
**Scoring Rule:** Earned credit reflects strictly verified integrated behavior and observed live production/staging runtime evidence (`-4.0 pts` withheld for interactive browser buyer capture, live webhook push from PayPal servers, and external legal/SOC 2 audits).

---

## 1. Weighted Category Breakdown (`2026-11-12` Post-RC1 Staging)

| # | Category | Weight | Baseline | M1+M2+M3 | Current (`RC1`) | % of Max | Key Observed Evidence (Verified Gains vs Remaining Blockers / Open Items) |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | **Core financial correctness** | 15 | 7.5 | 13.5 | **14.5** | 96.7% | `+` P0 PG deadlock **CLOSED** (`18 passed` × 3 PG16 stress runs) & live PayPal Sandbox OAuth + Order creation **PASS** (`packages/paypal/tests/`: `12 passed in 3.52s`); `GAP-001/005/011/012/016` verified.<br>`-` Interactive browser buyer capture & Disputes v1 live push `NOT VERIFIED` (`-0.5`). |
| 2 | **Security and tenant isolation** | 15 | 6.5 | 13.5 | **14.5** | 96.7% | `+` **`pip-audit`: `0` CVEs** (`11` resolved); **`apps/web` `npm audit --omit=dev`: `0` CVEs** (`next@16.4.6`); `sdk-typescript`: `0` CVEs; `20/20` adversarial tests PASS; non-root/digest Dockerfiles + `cap_drop: ALL`; live webhook fail-closed `401` verified on staging.<br>`-` External pen-test not yet performed. |
| 3 | **Reliability and recovery** | 12 | 5.5 | 11.0 | **11.5** | 95.8% | `+` Live Compose failure injection (`aegis_fi`): DB stop/start `/ready` (`200->503->200`), worker `--healthcheck` across restart, `4/4` `test_rc1_failure_injection.py` PASS; post-response `session.commit()` race fixed in `auth_orgs.py`, `guardian_db.py`, `disputeos_db.py`.<br>`-` Live S3/R2 WORM bucket upload pending credentials. |
| 4 | **Backend / API maturity** | 10 | 5.5 | 9.0 | **10.0** | 100.0% | `+` Load baseline (`c=10/25`, `50` reqs/endpoint): **`0.0%` error rate across all endpoints** (`POST /v1/guardian/proposals` `63.35/60.96 RPS`, reads/replay `112.94–1,483.37 RPS`). Live staging API operational at `https://api-staging.abhinavkumarsingh.tech`. |
| 5 | **Database integrity** | 8 | 4.5 | 7.5 | **8.0** | 100.0% | `+` `37` ORM tables (`0001`–`0003` PG16), PG `financial_events` immutability triggers, `(tenant_id, correlation_id)` + `(tenant_id, idempotency_key)` `pg_advisory_xact_lock` serialization. Live staging connected to managed Neon Serverless PG 18.6 with pooling & SSL. |
| 6 | **Frontend product usability** | 8 | 2.5 | 6.5 | **8.0** | 100.0% | `+` **5/5 real Chromium Playwright E2E journeys PASS (11.1s)** with 0 console/hydration/404/5xx errors; upgraded to Next.js 16 (`0` CVEs); **Live `aegis-web` container running on Azure Staging VM (`20.124.91.36:80` -> `:3005`) returning `200 OK` on `/login` and `/`**. |
| 7 | **Developer experience and SDKs** | 7 | 2.5 | 6.5 | **6.5** | 92.9% | `+` `aegis-sdk` & `@aegis-platform/sdk` `97/99` (`98.0%`) OpenAPI parity, `0` Ruff errors, `35/35` Vitest + `3/3` Node + `tsc` PASS (`0` CVEs).<br>`-` Live PyPI & npm publish `NOT VERIFIED`. |
| 8 | **Payment integrations** | 7 | 2.5 | 4.5 | **6.0** | 85.7% | `+` **Live PayPal Sandbox OAuth v1 token generation + Orders v2 roundtrip PASS (`12 passed in 3.52s`)**; `13/13` negative path tests PASS; staging `/ready` confirms `paypal_configured: true`; live webhook signature enforcement active (`401 Unauthorized`).<br>`-` Interactive browser buyer capture & live Stripe `NOT VERIFIED`. |
| 9 | **Test effectiveness** | 6 | 3.0 | 5.5 | **6.0** | 100.0% | `+` **`354 passed, 3 skipped, 0 failed`** on PG16 `pytest`, **`18 passed` × 3** concurrency stress runs, `5/5` Chromium Playwright E2E, `4/4` failure injection, `13/13` PayPal negative paths, `12/12` live PayPal Sandbox, `0.0%`-error load harness. |
| 10 | **Observability and operations** | 5 | 1.5 | 4.5 | **5.0** | 100.0% | `+` **Live Azure VM staging deployment (`20.124.91.36`) operational with Nginx reverse proxy + Cloudflare edge TLS at `https://api-staging.abhinavkumarsingh.tech`** (`/health` & `/ready` `200 OK`); Prometheus `/metrics`, JSON logs, durable outbox worker running healthy. |
| 11 | **Compliance & governance readiness** | 4 | 1.5 | 3.0 | **3.5** | 87.5% | `+` `RC1_COMPLIANCE_REVIEW_CHECKLIST.md` + `13/13` GDPR/DPDPA/SSRF/KMS/webhook tests PASS.<br>`-` External legal counsel sign-off, DPDPA statutory copy updates, & SOC 2 Type II `NOT VERIFIED`. |
| 12 | **Commercial readiness** | 3 | 0.5 | 2.0 | **2.5** | 83.3% | `+` Billing UI/API aligned (`/v1/billing/subscription`), `0` prod CVEs, E2E & live Azure staging green.<br>`-` Live Stripe API & interactive buyer approval pending before external public beta. |
| **TOTAL** | **100** | **43.5** | **87.0** | **96.0** | **96.0%** | **P0 PG deadlock CLOSED, live PayPal Sandbox OAuth/order PASS, live Azure staging OPERATIONAL (API + Frontend + Neon + Upstash). Pre-beta staging READY.** |

---

## 2. Updated Stage Readiness Levels (`2026-11-12` Post-RC1 Staging)

| Target Stage | Baseline | M1+M2+M3 | Current (`RC1`) | Remaining Verification / Release Conditions |
| :--- | :--- | :--- | :--- | :--- |
| **1. Local Development** | `72%` | `98%` | **READY (`99%`)** | `0` Ruff, `0` prod CVEs, `5/5` Chromium Playwright E2E, `make compose-smoke` PASS. |
| **2. Internal Staging** | `45%` | `88%` | **LIVE & OPERATIONAL (`100%`)** | Deployed on Azure VM (`20.124.91.36`); API live behind Cloudflare TLS (`https://api-staging.abhinavkumarsingh.tech`); Next.js Web console live (`http://20.124.91.36/login`); Neon PG 18.6 & Upstash Redis 7 connected. |
| **3. Public Beta (Sandbox)** | `28%` | `72%` | **READY FOR PILOT (`88%`)** | P0 deadlock **CLOSED**, live PayPal Sandbox OAuth/Orders **PASS**, live staging **UP**; only interactive browser buyer capture flow remains. |
| **4. Limited Commercial Launch** | `18%` | `58%` | **NOT READY (`64%`)** | Requires above + live Stripe Billing + live LLM evals + external legal counsel sign-off. |
| **5. Enterprise Production** | `10%` | `45%` | **NOT READY (`48%`)** | Requires third-party penetration test & SOC 2 Type II program execution. |
| **6. Regulated MoR / Wallets** | `4%` | `4%` | **NOT READY (`4%`)** | Unchanged — DO NOT self-build regulated funds custody without licensed PSP/BaaS partners & regional licenses. |
