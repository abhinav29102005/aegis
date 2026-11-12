# 10 — Competitive Benchmarking: PayPal, Stripe & Agentic Payment Ecosystems

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):**  
- **Improved Categories via M1 + M3 Sync:**
  - **#1 Developer API Experience:** Expanded to `85` paths / `96` ops with `/metrics`, billing, privacy, MFA/OIDC, invitations, pagination (`auth_orgs`/`webhooks`/`overview`).
  - **#18 Webhooks:** Upgraded from broken/SSRF-vulnerable to SSRF-hardened, lease-protected, concurrent-dispatch, `AEGIS-Signature: t=,v1=` unified worker + SDKs + deduped PayPal webhooks (`SEC-10`/`SEC-13`/`SEC-14` RESOLVED).
  - **#19 SDK Quality:** Elevated from `12.8%/25.6%` to **`75.0%/79.2%`** (`72/96` Py, `76/96` TS), with `AsyncAegisClient`, LangGraph/OpenAI/Vercel AI middlewares, Edge WebCrypto, fixed TS `detail` parser, and working `INTEGRATION_GUIDE.md`.
  - **#20 Observability & #21 Operational Reliability & #22 Enterprise Security:** Prometheus `/metrics`, OTel tracing, Grafana/alerts, PG `financial_events` immutability triggers, S3/R2 WORM storage, Redis rate limiting, worker leases + `SKIP LOCKED`, `HttpOnly` cookie BFF, GhostPay RBAC, MFA/OIDC, and `backup_pitr.sh`/`restore_verify.sh` PITR verification all shipped in M1 + M3.
  - **#23 Compliance & #24 Commercial Onboarding:** GDPR/DPDPA privacy export/erasure crypto-shredding, EU/IN/US residency configs, `/legal/{terms,privacy,dpa}`, `NON_CUSTODIAL_PERIMETER.md`, `/onboarding` wizard, `/status` + runbooks, and Stripe SaaS `/v1/billing/*` metering/plans shipped (`live Stripe/legal review pending`).
- **Still Unchanged / Blocked Until Computer 2 (`work/m2`) Pushes:**
  - **#3 Checkout, #4 International Payments (`JPY`/`BHD`), #8 Risk Management (`daily_limit_minor`), #10 Disputes (`provide-evidence`), #11 Refunds, #13 AI Agent Authorization (`approved=False`), #14 Policy Enforcement (`policy-v1` parity), #16 Historical Replay (RAM/DB split-brain), #17 Multi-Provider (Stripe/AP2/TAP/x402/MCP):** All still reside on baseline `1be376e` awaiting Computer 2 (`work/m2-financial-forensics-ai`).

*(Strategic conclusion remains unchanged: AEGIS's durable moat lies in **Market 2 (Agent Spend Governance)** + **Market 3 (Cross-Rail Forensic Replay & Agentic Dispute Intelligence)** sitting above PayPal, Stripe, AP2, TAP, and x402 — never unpartnered money transmission.)*
