# 15 — Prioritized Gap Register (`2026-11-12` M1 + M3 Sync Tracker)

**Synced Branch:** `integration/nexus` @ `498043e` (`work/m1` + `work/m3` merged; **`work/m2-financial-forensics-ai` NOT YET PUSHED**)

---

## 1. Closed / Resolved Gaps in M1 + M3 (`VERIFIED ON 498043e`)

| ID | Gap Summary | Closing Branch | Verification Evidence Observed |
| :--- | :--- | :--- | :--- |
| **GAP-003** | Outbound webhook SSRF & error body exfiltration | **M1** | `ssrf.py` + `webhooks.py` + `processor.py` (`follow_redirects=False`, IPv4/IPv6 block, status-only errors); PASS in `test_worker.py`, `test_webhooks_api.py`, `test_security_adversarial.py`. |
| **GAP-004** | Broken Next.js UI contracts (`CAPTURE_PENDING`, `passports:write`, 6 `Role`s, `DisputeAnalysis`, timeline) | **M3** | Fixed across `apps/web/src/`; `next lint` `0` errors, `10` Web Node tests & `next build` (`24` pages) PASS. *(Live Chromium Playwright run still pending.)* |
| **GAP-006** | `.env` / Compose `JWT_SECRET`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR` ignored by `NexusSettings` | **M1** | `settings.py` aliases + `validate_security_posture`; verified in `test_settings_and_auth.py` & live Compose smoke run. |
| **GAP-007** | Global HS256 JWT rate-limit prefix collision & unbounded RAM buckets | **M1** | `rate_limit.py` `sha256[:16]` + TTL eviction + Redis sorted-set backend; verified live in Compose (`x-ratelimit-remaining: 239->238`). |
| **GAP-008** | `ADMIN -> OWNER` escalation & cross-org hijack; open `/register` abuse | **M1** | `auth_orgs.py` blocks `ADMIN->OWNER` (`403`), switches to signed invite tokens, adds email verification tokens + `/register` throttling. |
| **GAP-014** | Webhook signature mismatch (`X-AEGIS-Signature` vs `AEGIS-Signature: t=,v1=`) & doc crash | **M1 + M3** | Unified across `processor.py`, `hashing.py`, `sdk-python`, `sdk-typescript` (Node + WebCrypto), & `INTEGRATION_GUIDE.md`; `test_verbatim_integration_guide_*` PASS. |
| **GAP-020** | PG `financial_events` immutability triggers, `FOR UPDATE` sequence lock, `save_dispute_case` drops, PITR scripts | **M1** | Alembic `0003` trigger verified PG16 + `backup_pitr.sh`/`restore_verify.sh` verified live against Compose dump. |
| **GAP-021** | Non-root Dockerfiles, worker healthcheck, `127.0.0.1:5432`, Prometheus `/metrics`, OTel, Compose CI, Linux VPS manifests | **M1** | `id`=`uid=999(aegis)`, `worker_healthcheck=OK`, `/metrics` + `/ready` verified live in Compose; `deploy/linux-staging/` + `deploy/observability/` added. |
| **GAP-024** | Stripe billing/metering scaffolding, GDPR/DPDPA erasure/export, `/onboarding`, `/status`, `/legal/{terms,privacy,dpa}` | **M1 + M3** | Backend `/v1/billing/*` & `/v1/privacy/*` unit-tested (`test_auth_billing_erasure.py`); UI & legal markdown pages built (`live Stripe/legal review pending`). |

---

## 2. Partially Closed Gaps (Waiting on M2 or Post-Merge Sync Fixes)

| ID | What M1 / M3 Already Completed | What Still Remains Open |
| :--- | :--- | :--- |
| **GAP-002** | **M1** wired `Permission.GHOSTPAY_READ` at `app.py` router mount; **M3** verified `VIEWER`/`AGENT_SERVICE` get `403` (`test_rbac_negative_matrix`). | **M2:** Add granular `Permission.GHOSTPAY_READ` / `GHOSTPAY_SIMULATE` inside `modules/ghostpay/ghostpay/api/router.py` directly. |
| **GAP-010** | **M1** added outbox `locked_at`/`lease_expires_at` reaper, `SKIP LOCKED` reconciliation, `attempts=0` DLQ reset & concurrency semaphore (`test_worker.py` & `test_platform_repo.py` PASS PG16). | **M3 Test Fix:** `tests/concurrency/test_concurrency_harness.py::test_outbox_lease_claim_concurrency` FAILS (`60` vs `20`) because fixture uses SQLite WAL instead of `AEGIS_TEST_POSTGRES_URL`. |
| **GAP-015** | **M3** built `AsyncAegisClient`, fixed TS `detail` parser, Edge WebCrypto, middlewares, pagination, & READMEs (`72/96` Py, `76/96` TS). | **M3 + Sync:** Wrap M1's `18` new billing/privacy/MFA/SSO/invitation routes in both SDKs to pass `test_openapi_sdk_coverage_gate` (`>=85%`, currently `75.0%`/`79.2%`). |
| **GAP-018** | **M1** sanitized 403/503/webhook errors & enforced active principals; **M3** replaced `localStorage` with `HttpOnly` cookie BFF + CSP headers. | **M2:** Resolve `disputeos_db.py` cross-case artifact IDOR & unmounted standalone module routers (`SEC-06`, `SEC-09`). |
| **GAP-022** | **M1** added S3/R2 WORM storage, 10MB streaming uploads, worker HTTP semaphore, M1 list pagination; **M3** added UI search/pagination/accessibility. | **M2:** Detach synchronous `Session` across PayPal `await` calls (`guardian_db.py`) + wire `guardian_db`/`disputeos_db` pagination. |
| **GAP-023** | **M1** added SHA-pinned CI, `pytest-cov`, `pip-audit`, `gitleaks`, `trivy`; **M3** populated `tests/{adversarial,concurrency,e2e,integration}/`. | **Sync Cleanup:** Fix `79` Ruff errors in M3, add `"tests"` to `pyproject.toml` `testpaths`, & add `@playwright/test` dependency to run Chromium E2E live. |
| **GAP-026** | **M1** added `0003` migration/deploy cleanup; **M3** deleted `docs/TEAM_HANDOFF.md`, updated `README.md`/`docs`, unlinked `packages/ui/`. | **M2:** Export missing `contracts.schema.json` schemas & reconcile `origin/feature/ghostpay` (`2a243e1`); `rmdir packages/ui`. |

---

## 3. Completely Open Gaps (100% Waiting on Unpushed Computer 2 `work/m2`)

| ID | Priority | Owner | Summary of Open Work Blocking Release |
| :--- | :--- | :--- | :--- |
| **GAP-001** | **P0** | M2 | `POST /approve` in `guardian_db.py:433` & `guardian/domain/service.py:290` still ignores `request.approved=False` (critical payment bypass!). |
| **GAP-005** | **P0** | M2 | `consume_approval` still omits `approval.payment_intent_id == intent.id`; `QuoteSnapshot` still skips hash check when `quote_hash` supplied. |
| **GAP-009** | **P0** | M2 | `DisputePayPalAdapter.submit_dispute_response` still no-op while `disputeos_db.py:510` marks cases `SUBMITTED` without calling PayPal. |
| **GAP-011** | **P1** | M2 | Guardian `PolicyEngine` omits `AgentIdentity.status`, `daily_limit_minor`, allowlist strictness, & diverges from GhostPay `"policy-v1"`. |
| **GAP-012** | **P1** | M2 | `paypal/client.py` 2-decimal math breaks `JPY`/`KWD`/`BHD`; `capture_order` calls PayPal before `CAPTURE_PENDING` check; zero refunds/retries/live Sandbox test. |
| **GAP-013** | **P1** | M2 | GhostPay legacy `timemachine/replay.py` + `forensics/*` still active; `/traces`/`POST /investigations` volatile RAM; `adapters.py` does naive subtraction instead of using M1's `spending_passport_snapshots`. |
| **GAP-016** | **P1** | M2 | `submit_proposal` idempotency outside DB lock without payload equivalence; `create_checkout` ignores attempt idempotency. |
| **GAP-017** | **P1** | M2 | Missing `DisputeStatus` state guard, `POST /resolve`, `disputeos.paypal.webhook_handler` (`CUSTOMER.DISPUTE.*`), & full-context `normalizer.py` hash. |
| **GAP-019** | **P2** | M2 | Zero live LLM integration in `PurchasingCopilot` & `DisputeAnalyzer` (`LLM_PROVIDER=deterministic` only); naive `CitationValidator`. |
| **GAP-025** | **P3** | M2 | Single PayPal adapter only — missing `PaymentProviderAdapter` (Stripe/AP2/TAP/x402/MCP). |
