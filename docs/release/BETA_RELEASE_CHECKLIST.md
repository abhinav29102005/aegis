# AEGIS — Public Beta Release Candidate Checklist

**Document:** `docs/release/BETA_RELEASE_CHECKLIST.md`  
**Revision Date:** `2026-11-12`  
**Target Release:** AEGIS Public Beta (Limited Sandbox Pilot)  

---

## 1. Engineering & Code Hygiene Checklist

- [x] **Static Linting:** `uv run ruff check .` reports `0` errors across all files.
- [x] **Python Unit & Integration Tests:** `354 passed, 3 skipped, 0 failed` on PostgreSQL 16.
- [x] **Concurrency Stress Tests:** 3 consecutive runs of `test_rc1_deadlock_stress.py` (`18 passed` × 3).
- [x] **Advisory Lock Implementation:** `(tenant_id, correlation_id)` and `(tenant_id, idempotency_key)` advisory transaction locks verified.
- [x] **Python Dependency Audit:** `pip-audit` reports `0` known vulnerabilities.
- [x] **TypeScript SDK Tests:** `tsc` typecheck + build, `35/35` Vitest tests, and `3/3` Node tests pass (`0` vulnerabilities).
- [x] **Web Console Tests:** Next.js 16 (`next@16.4.6`), `next lint` 0 errors, `3/3` unit + `7/7` Node journey tests pass (`0` vulnerabilities).
- [x] **Chromium Playwright E2E:** `5/5` real browser user journeys pass in `11.1s` with 0 console or hydration errors.
- [x] **Synthetic Load Benchmark:** `0.0%` error rate across all endpoints under concurrent load (`c=10` and `c=25`).

---

## 2. Infrastructure & Staging Checklist

- [x] **Azure VM Deployment:** Ubuntu 24.04 LTS VM (`20.124.91.36`) operational with 4 GB swap.
- [x] **Docker Compose Stack:** `aegis-api`, `aegis-web`, `aegis-worker` running healthy with non-root containers.
- [x] **Managed Database:** Neon PostgreSQL 18.6 connected with SSL enforced (`sslmode=require`) and connection pooling.
- [x] **Database Migrations:** Alembic revision `0003_prod_hardening` applied; 37 ORM tables; append-only triggers active.
- [x] **Managed Cache:** Upstash Redis 8.4 connected with TLS (`rediss://`); sliding-window rate limiter verified.
- [x] **Reverse Proxy & Edge:** Nginx reverse proxy operational; Cloudflare Edge TLS active on `https://api-staging.abhinavkumarsingh.tech`.
- [x] **Health & Readiness Endpoints:** `/health` and `/ready` (`paypal_configured: true`) return `200 OK`.
- [x] **Web Console Reachability:** Accessible via `http://20.124.91.36/login` and `http://20.124.91.36/` (`200 OK`).

---

## 3. PayPal Sandbox Integration Checklist

- [x] **OAuth Client-Credentials:** Live authentication against `api-m.sandbox.paypal.com` verified (`12/12` pass).
- [x] **Orders v2 Creation:** Live order creation verified (generated Order `9BU33738KW027293J` with approval URL).
- [x] **Pre-Capture Security Guard:** Unapproved order capture rejected by Guardian (`409 Conflict`) and PayPal (`ORDER_NOT_APPROVED`).
- [x] **Webhook Receiver:** Live endpoint `POST /v1/paypal/webhooks` deployed behind Cloudflare TLS.
- [x] **Fail-Closed Security:** Unsigned or tampered requests immediately rejected with `401 Unauthorized`.
- [x] **Live Webhook Reception & Verification:** PayPal Sandbox notification server pushed live webhooks (`PAYMENT.CAPTURE.COMPLETED`, `CUSTOMER.DISPUTE.CREATED`, `PAYMENT.CAPTURE.REFUNDED`); signature verified via PayPal API and recorded in Neon DB.
- [ ] **Interactive Buyer Sandbox Approval:** Requires human tester or sandbox personal buyer account to sign into PayPal UI at approval URL.

---

## 4. Pre-Commercial Launch Requirements (Future Phase)

- [ ] Live Stripe Billing integration in test mode (`STRIPE_API_KEY` unset).
- [ ] Live LLM provider evaluations against OpenAI/Gemini/Anthropic keys (`LLM_PROVIDER=deterministic` active).
- [ ] Remote S3/R2 WORM bucket upload verification (`AEGIS_STORAGE_BACKEND=local` active).
- [ ] External legal counsel sign-off on `/legal/*` (ToS, Privacy Policy, DPA) & DPDPA statutory notices.
- [ ] Third-party penetration testing and SOC 2 Type II audit readiness.
