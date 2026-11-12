# 10 — Competitive Benchmarking: PayPal, Stripe & Agentic Payment Ecosystems

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):**

- **Capabilities Closed & Verified Locally Across M1 + M2 + M3:**
  - **#1 Developer API Experience:** `88` paths / `99` ops (`/metrics`, billing, privacy, MFA/OIDC, invitations, refund, resolve, MCP `/v1/guardian/mcp`).
  - **#18 Webhooks:** Outbound SSRF-guarded, lease-protected, concurrent-dispatch, unified `AEGIS-Signature: t=,v1=` worker + SDKs + inbound deduped PayPal + `CUSTOMER.DISPUTE.*` DisputeOS webhook handler.
  - **#19 SDK Quality:** Both `aegis-sdk` (Python Sync+Async, LangGraph/OpenAI) and `@aegis-platform/sdk` (TS, Node+WebCrypto, Vercel AI) hit **`97 / 99` (`98.0%`) OpenAPI parity** (`0` Ruff errors, `38/38` TS tests PASS, `INTEGRATION_GUIDE.md` verbatim tests PASS).
  - **#20 Observability & #21 Reliability & #22 Enterprise Security:** Live Docker Compose (`api` + `worker` + `migrate` + `postgres` + `redis`), PG `financial_events` immutability triggers, S3/R2 WORM storage, Redis rate limiting, worker leases + `SKIP LOCKED` + SQLite CAS, `HttpOnly` cookie BFF, Gateway+Router RBAC (`SEC-01`), Artifact BOLA fix (`SEC-06`), MFA/OIDC, and `backup_pitr.sh`/`restore_verify.sh` all shipped & verified.
  - **#23 Compliance & #24 Commercial Onboarding:** GDPR/DPDPA privacy export/erasure crypto-shredding, EU/IN/US residency configs, `/legal/{terms,privacy,dpa}`, `/onboarding`, `/status`, runbooks, and Stripe `/v1/billing/*` (`live Stripe/legal review pending`).
  - **#3/#4/#8/#10/#11/#13/#14/#16/#17 Core Guardian, Disputes, Multi-Rail & Replay (M2 Code & Mocked Verification Complete):**
    - ISO-4217 exponents (`JPY`/`BHD`/`KWD`), `approved=False` decline/release, `approval.payment_intent_id` binding, unconditional quote hash, `daily/monthly_limit_minor`, `AgentIdentity.status`, pre-capture state guard, PayPal refunds, `PayPalDisputeAdapter` (`provide-evidence`, `accept-claim`), PG-backed GhostPay replay sharing canonical `contracts.policy_v1` (`1,000/1,000` parity PASS), async `httpx` OpenAI/Gemini/Anthropic DisputeAnalyzer adapters, AND `StripeProviderAdapter`, `AP2MandateAdapter`, `TAPProvenanceAdapter`, `X402SettlementAdapter`, `DeflectionAlertAdapter` + MCP server!
- **Remaining Gap vs Commercial Incumbents:**
  - **Live External Wire Verification (`NOT VERIFIED`):** Live PayPal Sandbox (`Orders v2` + `Disputes v1`), Live Stripe API (`PaymentIntent` + Billing webhooks), and Live OpenAI/Gemini/Anthropic evals have **not** run over live networks with real credentials yet (mocked/unit suites pass cleanly).

*(Strategic positioning reinforced: AEGIS's differentiation sits cleanly above PSPs in **Agent Spend Governance**, **Cross-Rail Forensic Replay (`policy-v1` parity + GhostPay)**, and **Evidence-Grounded Dispute Intelligence** — non-custodial by design.)*
