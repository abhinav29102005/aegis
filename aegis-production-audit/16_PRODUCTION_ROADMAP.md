# 16 — Dependency-Ordered Production Roadmap (5 Horizons)

**Execution Rule:** Sequencing is strictly dependency-driven (no arbitrary calendar promises). No horizon should launch externally while security gates or acceptance criteria from the prior horizon remain failing.

---

## Horizon 1 — Correctness, Security & Operational Baseline
**Goal:** Eliminate every P0 financial bypass, security vulnerability, runtime config bug, and UI contract break so internal staging runs reproducibly on Linux/Docker + PostgreSQL 16.
- **Deliverables:**
  1. Fix `approved=False` propagation, approval-intent binding, unconditional `quote_hash` verification, and pre-capture state guard (`GAP-001`, `GAP-005`).
  2. Enforce GhostPay RBAC (`Permission.GHOSTPAY_READ`/`SIMULATE`), fix `ADMIN -> OWNER` privilege escalation, block webhook SSRF, fix JWT rate-limit key collision, align `.env`/Compose/`NexusSettings` variable names, sanitize 403/503 error messages (`GAP-002`, `GAP-003`, `GAP-006`, `GAP-007`, `GAP-008`, `GAP-018`).
  3. Add worker outbox `locked_at` lease/reaper, `SKIP LOCKED` payment reconciliation, and DLQ `attempts` reset (`GAP-010`).
  4. Harden Dockerfiles (`USER aegis`, worker healthcheck, pinned digests), add Compose E2E CI smoke test, migrate staging off Android OPPO phone onto Linux VPS / Managed PG.
  5. Fix all `apps/web` contract mismatches (`/payments/[id]`, `/agents`, `/developer`, `/settings`, `/disputes/[id]`, `/ghostpay/replay/[id]`) + add Playwright E2E CI (`GAP-004`).
- **Security Gate:** Full 6-role x 78-op RBAC negative suite passes; zero SSRF/BOLA/escalation findings; Compose boots cleanly in `APP_ENV=production` without default secrets.
- **Rollback Plan:** Feature-branch / immutable container tag pinning; zero destructive DB drops (`alembic` additive revisions only).
- **Estimated Effort:** ~12–16 engineer-days.

---

## Horizon 2 — Real Payments Integration & Forensic Parity
**Goal:** Move off mocked PayPal HTTP onto verified live PayPal Sandbox flows while ensuring 100% deterministic Guardian <-> GhostPay fidelity.
- **Deliverables:**
  1. Implement ISO 4217 currency exponents (`JPY`/`KWD`/etc.), HTTP retry/backoff, Refunds API, `list_disputes` timeout protection, and PayPal `provide-evidence` submission cleanly separated from draft readiness (`GAP-009`, `GAP-012`).
  2. Ingest PayPal `CUSTOMER.DISPUTE.*` webhooks with idempotent event deduplication (`GAP-013`/`SEC-13`), response deadlines, and monotonic `DisputeStatus` guards (`GAP-017`).
  3. Unify Guardian `PolicyEngine` + GhostPay `ReplayEngine` onto one canonical `"policy-v1"` evaluator, retire legacy `timemachine/replay.py` + `forensics/*` duplicates, persist `spending_passport_snapshots` & PG-backed GhostPay traces/Agent DNA (`GAP-011`, `GAP-013`).
  4. Add transactional payload-equivalence idempotency on proposals, `AgentIdentity.status` enforcement, and rolling `daily_limit_minor` tracking (`GAP-016`).
  5. Execute full live **PayPal Sandbox** verification suite (`create -> approve -> capture -> refund -> dispute -> webhook`).
- **Release Criteria:** Zero policy drift across 1,000 randomized property cases; live sandbox suite green; PostgreSQL immutability triggers (`financial_events`) active.
- **Remaining Business Dependency:** Valid PayPal Sandbox merchant + buyer business/personal credentials & webhook tunnel/endpoint.
- **Estimated Effort:** ~14–18 engineer-days.

---

## Horizon 3 — Customer-Ready AEGIS (Public Beta -> Initial Paid Launch)
**Goal:** Deliver production-ready DX, observability, reliability, real LLM integrations, and commercial self-serve prerequisites.
- **Deliverables:**
  1. Unify `AEGIS-Signature: t=,v1=` replay-protected webhooks across worker, Python SDK, TS SDK, and `INTEGRATION_GUIDE.md`; reach `>= 85%` endpoint parity in both SDKs (`GAP-014`, `GAP-015`).
  2. Replace `PurchasingCopilot` & `DisputeAnalyzer` stubs with provider-abstracted OpenAI/Gemini/Anthropic adapters, semantic citation verification, token/cost logging, and prompt-injection tests (`GAP-019`).
  3. Migrate `apps/web` session to `HttpOnly` cookies + CSP/HSTS security headers, add search/pagination across all tables, add email verification & org onboarding wizard.
  4. Move `rate_limit.py` to Redis, detach synchronous DB sessions from outbound HTTP `await`s, move `LocalObjectStorage` -> S3/R2 object storage, deploy Prometheus/OTel metrics + SLO alerting + tested PG PITR backups (`GAP-021`, `GAP-022`).
  5. Ship Stripe Billing subscription tiers/usage metering, self-serve quotas, GDPR/DPDPA PII erasure/export workflows, published ToS/Privacy/DPA, & status page (`GAP-024`).
- **Security Gate:** External web/API penetration test + Playwright E2E + load test (Tier 2 `100` active org profile, `>= 20` RPS sustained) pass.
- **Remaining Business/Legal Dependencies:** Legal sign-off on ToS, Privacy Policy, DPA, and non-custodial compliance boundary memo.
- **Estimated Effort:** ~20–28 engineer-days.

---

## Horizon 4 — Multi-Provider Agentic Governance & Enterprise Readiness
**Goal:** Establish AEGIS's core moat as the rail-neutral financial black box across multiple PSPs and emerging agentic payment protocols.
- **Deliverables:**
  1. Provider-neutral `PaymentProviderAdapter` supporting **Stripe** (PaymentIntents, Shared Payment Tokens, Connect, Disputes, Issuing webhook ingestion) alongside PayPal (`GAP-025`).
  2. Protocol adapters: **Google AP2** `CheckoutMandate`/`PaymentMandate` import, **Visa TAP** / **Mastercard Agent Pay** token provenance verification, and **x402** micro-payment ledger ingestion.
  3. **AEGIS MCP Server** + native LangGraph/OpenAI Agents SDK/Vercel AI SDK middlewares so developers drop AEGIS guardrails in 3 lines.
  4. Enterprise identity & trust: SAML/OIDC SSO, WebAuthn/TOTP MFA, KMS/HSM webhook/API-key wrapping, 7-year WORM S3 Object Lock ledger exports, SOC 2 Type I/II readiness.
- **Estimated Effort:** ~25–35 engineer-days.

---

## Horizon 5 — Commercial Expansion & Partnered Infrastructure
**Goal:** Scale globally and unlock higher-take-rate monetization safely via regulated partners (never unpartnered custody/acquiring).
- **Deliverables:**
  1. Multi-region active-active / data-residency deployments (EU GDPR, India RBI localization zone, US).
  2. Co-branded / partnered **Agent Virtual Card & Wallet Controls** powered via **Stripe Issuing / Connect** or licensed **BaaS bank sponsor** (preserving AEGIS's software-only non-custodial perimeter unless explicitly licensed).
  3. Enterprise SIEM connectors (Splunk/Datadog/BigQuery), cross-org benchmark risk intelligence (anonymized Agent DNA baselines), and automated chargeback pre-dispute deflection integrations (Verifi/Ethoca via PSPs).
- **Remaining Business/Regulatory Dependencies:** Stripe/PayPal/BaaS partner commercial agreements, regional legal entity setup, and ISO 27001 / SOC 2 Type II / (if touching cards) PCI-DSS TPSP audits.

