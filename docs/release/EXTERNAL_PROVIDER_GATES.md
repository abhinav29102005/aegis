# External Provider Gates & Integration Readiness Status

**Document:** `docs/release/EXTERNAL_PROVIDER_GATES.md`  
**Revision Date:** `2026-11-12`  

---

## 1. Provider Readiness & Credential Ledger

| Provider | Purpose | Status | Configured Settings | Observed Evidence & Action Required |
| :--- | :--- | :---: | :--- | :--- |
| **PayPal Sandbox** | Core payment rail (Orders v2, Webhooks, Disputes v1) | **OPERATIONAL & VERIFIED LIVE** | `PAYPAL_MODE=sandbox`<br>`PAYPAL_CLIENT_ID` (set)<br>`PAYPAL_CLIENT_SECRET` (set)<br>`PAYPAL_WEBHOOK_ID=2JA67664A1962980D` | OAuth2, Orders v2 creation, unapproved capture guard, and live webhook reception/verification verified live against `api-m.sandbox.paypal.com`. Ready for interactive buyer test. |
| **Stripe** | SaaS customer subscription billing & checkout portal | **CODE READY (CREDENTIAL GATED)** | `STRIPE_API_KEY` (unset)<br>`STRIPE_WEBHOOK_SECRET` (unset) | Implemented in `services/api/aegis_api/routers/billing.py`. Unit-tested with mock webhooks. Requires provision of test-mode API key for live execution. |
| **LLM Intelligence** | Dispute contradiction detection & citation validation | **FALLBACK OPERATIONAL (CREDENTIAL GATED)** | `LLM_PROVIDER=deterministic`<br>`OPENAI_API_KEY` (unset)<br>`GOOGLE_API_KEY` (unset)<br>`ANTHROPIC_API_KEY` (unset) | Fully operational via deterministic rule-based analysis. Adapters implemented for OpenAI, Gemini, and Anthropic in `llm_client.py`. Live evaluations require API keys. |
| **Evidence Storage** | Immutable WORM audit trail & dispute artifact storage | **LOCAL STORAGE OPERATIONAL** | `AEGIS_STORAGE_BACKEND=local`<br>`EVIDENCE_STORAGE_DIR=./var/aegis-evidence`<br>`AEGIS_S3_BUCKET` (unset) | Filesystem storage operational with streaming 10 MB cap. `S3ObjectStorage` adapter implemented; live bucket upload requires S3/R2 credentials. |
| **Email / SMTP** | User onboarding invitations & verification tokens | **DEFERRED FOR STAGING** | `EMAIL_VERIFICATION_REQUIRED=false`<br>`SMTP_HOST` (unset) | Organization invitations and tokens generated and stored in database. Token dispatch printed to logs in staging mode; live SMTP requires mail server credentials. |

---

## 2. Release Impact Assessment

- **Public Beta (Sandbox Pilot):** **UNBLOCKED**. Core functionality (agent governance, spending passports, policy engine, PayPal Sandbox Orders v2, and live webhooks) is fully operational.
- **Commercial Production Launch:** **GATED** by Stripe Billing, live LLM evals, and remote S3/R2 WORM bucket credentials.
