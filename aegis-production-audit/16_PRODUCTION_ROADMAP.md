# 16 — Dependency-Ordered Production Roadmap (Updated `2026-11-12`)

**Current Checkpoint (`498043e`):** **M1 (Platform/Security/Worker/Infra/Commercial) and M3 (Next.js/SDKs/Docs/QA) are MERGED on `integration/nexus`. Next mandatory gate is Computer 2 (`work/m2-financial-forensics-ai`).**

---

## Horizon Progress Status

| Horizon | Scope Summary | Current Completion (`498043e`) | Next Concrete Gate |
| :--- | :--- | :--- | :--- |
| **Horizon 1 — Correctness, Security & Operational Baseline** | Security, RBAC, SSRF, Worker Leases, Non-root Compose, UI Contracts, Financial Approval/Binding fixes | **~75% Complete** *(M1+M3 security/infra/UI done; M2 financial/approval P0 fixes open)* | Merge `work/m2` (`GAP-001`, `GAP-002` internal, `GAP-005`), fix M3 `concurrency_env` PG16 fixture + `79` Ruff lint errors, run Playwright Chromium E2E. |
| **Horizon 2 — Real Payments Integration & Forensic Parity** | ISO 4217 currencies, PayPal capture/refund/disputes, unified `"policy-v1"`, PG snapshots/traces, live PayPal Sandbox | **~20% Complete** *(M1 DB tables/hooks/PG triggers ready; M2 logic unpushed)* | Merge `work/m2` (`GAP-009`, `GAP-011`, `GAP-012`, `GAP-013`, `GAP-016`, `GAP-017`) + execute **live PayPal Sandbox** E2E suite. |
| **Horizon 3 — Customer-Ready AEGIS (Public Beta -> Initial Paid)** | `>=85%` SDKs, `t=,v1=` webhooks, `HttpOnly` auth, Redis RL, S3/WORM, `/metrics`, backups, Stripe Billing, GDPR, Legal/Status, Real LLMs | **~75% Complete** *(M1+M3 platform/UI/SDK/billing/privacy/legal shipped)* | Expand SDKs (`75%`/`79.2%` -> `>=85%` across `96+` ops), merge M2 live LLMs (`GAP-019`), verify live Stripe Billing + S3/R2 + Linux VPS staging + counsel review. |
| **Horizon 4 — Multi-Rail & Enterprise Readiness** | Stripe/AP2/TAP/x402/MCP (`GAP-025`), OIDC SSO, TOTP MFA, KMS, 7yr WORM S3, SOC 2 Type II | **~35% Complete** *(M1 shipped MFA/OIDC/KMS/WORM; M2 multi-rail/MCP unpushed)* | Merge `work/m2` multi-rail/MCP adapters + run enterprise penetration test & SOC 2 Type II readiness. |
| **Horizon 5 — Global Scale & Partnered Infrastructure** | Regional residency (`EU`/`IN`/`US` envs added in M1), Partnered Card/Wallet controls | **~15% Complete** *(Residency templates ready)* | Customer demand, Stripe Connect/Issuing or BaaS agreements, & regulatory licensing review. |
