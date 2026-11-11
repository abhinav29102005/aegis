# 14 — Engineering Maturity Scorecard (`43.5 / 100`)

**Scoring Rule:** Earned credit reflects strictly verified code behavior and runtime test evidence (`NOT` mocked aspirations or build-only UI screens).

---

## 1. Weighted Category Breakdown

| # | Category | Weight | Earned | % of Max | Confidence | Key Observed Evidence (Positives vs Deductions) |
|---:|---|---:|---:|---:|---|---|
| 1 | **Core financial correctness** | 15 | **7.5** | 50.0% | High | `+` Integer minor units everywhere, SHA-256 `quote_hash`, atomic conditional `UPDATE` budget reservation in PG16, 2-step PayPal capture check.<br>`-` **`approved=False` ignored in both APIs (`CRITICAL`)**; `paypal/client.py` 2-decimal bug breaks JPY/BHD; `daily_limit_minor` & `AgentIdentity.status` unchecked in `PolicyEngine`; `approval.payment_intent_id` unbound; Guardian vs GhostPay `"policy-v1"` divergence; `capture` calls PayPal before checking `CAPTURE_PENDING`. |
| 2 | **Security and tenant isolation** | 15 | **6.5** | 43.3% | High | `+` PBKDF2-600k, HMAC API keys, fail-closed PayPal webhook API verify, `LocalObjectStorage` path-traversal guard, production secret length guard.<br>`-` **All `/v1/ghostpay/*` lack RBAC**; **critical outbound webhook SSRF**; **`ADMIN->OWNER` privilege escalation**; `JWT_SECRET`/`RATE_LIMIT_RPM` ignored by settings; JWT rate-limit prefix collision; `TenantIsolationError` leaks victim UUID; `localStorage` JWT; inactive-user API key bypass; DisputeOS artifact BOLA. |
| 3 | **Reliability and recovery** | 12 | **5.5** | 45.8% | High | `+` Transactional outbox + exponential backoff/DLQ, graceful worker `SIGINT`/`SIGTERM`, PayPal timeout holds funds for reconciliation.<br>`-` Worker `PROCESSING` rows lack lease/reaper; `reconcile_pending_payments` lacks `SKIP LOCKED`; DLQ requeue keeps old `attempts`; uncaught `SQLAlchemyError` crashes worker; zero HTTP retries; GhostPay `/traces` & `POST /investigations` volatile RAM. |
| 4 | **Backend / API maturity** | 10 | **5.5** | 55.0% | High | `+` Versioned `/v1/*`, `69` paths / `78` ops OpenAPI, structured JSON logs + correlation IDs.<br>`-` `IdempotencyRecordRow` unused; split GhostPay DB vs RAM storage; unhandled `PayPal*Error` in `guardian_db.py` (`500`); unbounded list routes; raw `str(exc)` leakage; missing `mark_resolved` & PayPal dispute webhooks. |
| 5 | **Database integrity** | 8 | **4.5** | 56.3% | High | `+` 27 clean SQLAlchemy 2.0 tables, 2 Alembic migrations tested up/down/up on PG16, uniqueness constraints.<br>`-` Zero Postgres `UPDATE`/`DELETE` immutability triggers/`REVOKE` on `financial_events`; mutable in-place `SpendingPassport` (breaks historical replay); unlocked `append_financial_event` sequence read; missing `pool_recycle`/backups; silent field drops in `save_dispute_case`. |
| 6 | **Frontend product usability** | 8 | **2.5** | 31.3% | High | `+` 14 Next.js 15 routes cleanly build/lint, accessible `<dialog>` modals & skip links, `/dashboard` & `/ghostpay` work cleanly.<br>`-` Capture button **unreachable** (`BUYER_APPROVED` vs `CAPTURE_PENDING`); Merchant controls **hidden** (`merchants:write`); `/developer` & `/settings` roles fail `422`; Dispute analysis & GhostPay timeline broken; zero pagination/search/E2E. |
| 7 | **Developer experience and SDKs** | 7 | **2.5** | 35.7% | High | `+` Typed clients started in Py & TS, clean repo `INTEGRATION_GUIDE.md` intent.<br>`-` Only `12.8%` (Py) & `25.6%` (TS) endpoint coverage; TS error parser drops `detail.message`; no retries/pagination/async Python SDK; docs webhook signature crashes SDK (`AEGIS-Signature: t=,v1=` vs `X-AEGIS-Signature: sha256=`). |
| 8 | **Payment integrations** | 7 | **2.5** | 35.7% | High | `+` Clean isolated PayPal Orders v2 wrapper + webhook verifier + fail-closed sandbox mode.<br>`-` **Zero live PayPal Sandbox execution (`NOT VERIFIED`)**; mocked only; no Stripe/cards/AP2/x402; no refunds/voids/partial captures; DisputeOS submission is a simulated no-op (`submitted: False`). |
| 9 | **Test effectiveness** | 6 | **3.0** | 50.0% | High | `+` 143/144 pytest + PG16 concurrency integration test + strong GhostPay adversarial matrix + DisputeOS hallucination-rejection fakes.<br>`-` Zero Playwright E2E tests (missed 5 broken UI screens); SQLite masks PG behaviors across API/worker suites; mocked TS error shape hid parser bug; `0` files in `tests/{adversarial,concurrency,e2e,integration}`; zero coverage/load metrics. |
| 10 | **Observability and operations** | 5 | **1.5** | 30.0% | High | `+` Structured API JSON logging + `/health` & `/ready` probes.<br>`-` Zero Prometheus/OTel metrics/traces, zero alerts, worker unstructured logs & no healthcheck, root Python containers, broken Compose volume/env var mapping, zero backup scripts, full Compose stack boot unverified. |
| 11 | **Compliance & governance readiness** | 4 | **1.5** | 37.5% | High | `+` Clear security invariants doc, `is_synthetic` separation, MIT `LICENSE`.<br>`-` No GDPR/DPDPA erasure/redaction, unenforced `retention_until`, no PCI v4 script telemetry on payment pages, no SOC 2/SOX controls or vendor KYC/sanctions gating. |
| 12 | **Commercial readiness** | 3 | **0.5** | 16.7% | High | `+` Multi-tenant signup & org switching models exist.<br>`-` Zero billing/Stripe/metering/quotas/ToS/Privacy/DPA/SLA/support/onboarding wizard. |
| **TOTAL** | **100** | **43.5** | **43.5%** | **High** | **Strong architectural prototype; requires Horizon 1–3 hardening before beta or customer funds.** |

---

## 2. Environment & Stage Readiness Levels

| Target Stage | Readiness Verdict | Current Score / Gate | Blocking Conditions |
| :--- | :--- | :--- | :--- |
| **1. Local Development** | **READY WITH KNOWN BUGS** | **72%** | Works cleanly via `uv` + SQLite + Docker PG16 (`143 passed, 1 skipped` locally); fix broken Compose env names & UI contract drift for full local Compose E2E. |
| **2. Internal Staging** | **BLOCKED ON P0 FIXES** | **45%** | Must fix Compose `JWT_SECRET`/`EVIDENCE_STORAGE_DIR` mapping, `approved=False`, GhostPay RBAC, webhook SSRF, UI Capture/Merchant/Role mismatches, and deploy off OPPO phone onto Linux VPS/cloud. |
| **3. Public Beta (Non-Monetary / Sandbox)** | **NOT READY** | **28%** | Requires Horizon 1 + live PayPal Sandbox verification, Redis rate-limiting, worker crash leases, Playwright E2E, SDK parity `>=80%`, & working `INTEGRATION_GUIDE.md`. |
| **4. Limited Commercial Launch (Real Money Governance)** | **NOT READY** | **18%** | Requires Horizon 1–3: unified `"policy-v1"`, immutable passport history, refunds/disputes, real LLM provider + fallback telemetry, Stripe Billing, backups/PITR, OTel alerts, ToS/DPA. |
| **5. Enterprise Production** | **NOT READY** | **10%** | Requires Horizon 4: multi-PSP adapter (Stripe + PayPal), OIDC/SSO + MFA, PG immutability triggers, KMS secret wrapping, SOC 2 Type II audit trail, penetration test. |
| **6. Regulated Payment Processing / MoR / Wallets** | **NOT READY (DO NOT ATTEMPT DIRECTLY)** | **4%** | Requires Horizon 5 legal entity licensing (FinCEN MSB/MTL, RBI PA, EU PSD2) OR licensed BaaS/Stripe Connect/PayPal partner architecture + PCI Level 1 TPSP RoC. |

