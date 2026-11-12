# 16 — Dependency-Ordered Production Roadmap (Updated `2026-11-12`)

**Current Checkpoint (`integration/nexus` Post-M1+M2+M3):** **All three machine branches and post-merge integration fixes are landed, passing Ruff (`0` errors), PG16 `pytest --cov` (`313 passed, 1 skipped`, `90%` cov), TS SDK (`38/38`), Next.js (`10/10` + `24`-route build), and `make compose-smoke` (`exit 0`). Remaining milestones are live external provider verification, CVE updates, browser Playwright, and compliance/staging rollouts.**

---

## Horizon Progress Status

| Horizon | Scope Summary | Current Completion (`2026-11-12`) | Remaining Concrete Exit Criteria |
| :--- | :--- | :--- | :--- |
| **Horizon 1 — Correctness, Security & Operational Baseline** | Security, RBAC, SSRF, Worker Leases, Non-root Compose, UI Contracts, Financial Approval/Binding fixes | **~96% Complete** | Add `@playwright/test` & run `playwright_e2e_journeys.spec.ts` against live Chromium + `next start` + `aegis_api`. |
| **Horizon 2 — Real Payments Integration & Forensic Parity** | ISO-4217 currencies, PayPal capture/refund/disputes, unified `"policy-v1"`, PG snapshots/traces, live PayPal Sandbox | **~85% Complete** *(All code & PG16 tests PASS)* | Execute `packages/paypal/tests/test_live_sandbox_optional.py` & Disputes webhook roundtrip against **real PayPal Sandbox** (`NOT VERIFIED`). |
| **Horizon 3 — Customer-Ready AEGIS (Public Beta -> Initial Paid)** | `>=98%` SDKs, `t=,v1=` webhooks, `HttpOnly` auth, Redis RL, S3/WORM, `/metrics`, backups, Stripe Billing, GDPR, Legal/Status, Real LLMs | **~82% Complete** | Resolve `pip-audit` (`langgraph`/`pytest`) & `apps/web` `postcss` CVEs; execute live Stripe Billing, live S3/R2, live LLM evals, SMTP, Linux VPS deploy & legal counsel sign-off. |
| **Horizon 4 — Multi-Rail & Enterprise Readiness** | Stripe/AP2/TAP/x402/MCP (`GAP-025`), OIDC SSO, TOTP MFA, KMS, 7yr WORM S3, SOC 2 Type II | **~65% Complete** *(All code adapters & `/v1/guardian/mcp` landed)* | Live provider sandbox verification for Stripe/AP2/x402, RPS load benchmarks, external penetration test, & SOC 2 Type II readiness. |
| **Horizon 5 — Global Scale & Partnered Infrastructure** | Regional residency (`EU`/`IN`/`US`), Partnered Card/Wallet controls | **~20% Complete** | Customer demand, Stripe Connect/Issuing or BaaS agreements, & regulatory licensing review. |
