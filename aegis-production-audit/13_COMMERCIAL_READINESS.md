# 13 — Commercial Product Readiness Assessment

**Verdict: NOT READY FOR PAYING CUSTOMERS.**  
AEGIS currently has multi-tenant org models and self-serve signup, **but lacks every commercial, operational, billing, legal, and customer-onboarding capability required to charge external organizations.**

---

## 1. Commercial Capability Audit

| Dimension | Current State | Verdict |
| :--- | :--- | :--- |
| Customer Onboarding & Trial Environments | Open `/login` "Create organization" form (`auth_orgs.py:130`); **no email verification, no interactive onboarding checklist, no sandbox vs live tenant toggle**, and DisputeOS seeds fake demo cases inline (`seed-demo`) while Guardian has broken UI merchant creation. | **PARTIAL / INCOMPLETE** |
| Organization Provisioning & Self-Service API Keys | `POST /v1/auth/register` & `/v1/orgs/api-keys` exist backend-side, **but UI `/developer` defaults to `"DEVELOPER"` (422)** and `/settings` defaults to `"RISK_ANALYST"` (422). | **BROKEN IN UI** |
| Pricing, Plan Tiers, Quotas & Usage Metering | Zero `Plan` / `Subscription` / `Quota` models, zero API-call or transaction-volume metering, zero Stripe Billing integration. | **MISSING** |
| Customer Billing & Invoicing | None. | **MISSING** |
| Status Page, SLOs & Incident Management | No `/status` page, no published uptime SLA/SLOs, no PagerDuty/Opsgenie alerting, no incident runbooks. | **MISSING** |
| Support Escalation & Documentation Portal | Static markdown files in repo (`docs/sdk/INTEGRATION_GUIDE.md` is broken vs SDK code); zero in-app help/docs or support ticketing. | **MISSING** |
| Legal Disclosures (ToS, Privacy Policy, DPA, SLA) | MIT `LICENSE` covers open-source code only; zero customer Terms of Service, Privacy Notice, Data Processing Addendum, or Cookie/Disclosures in `apps/web`. | **MISSING** |
| Audit Exports, Data Retention, Deletion & Account Closure | Audit log JSON API exists (`GET /v1/audit-events`); zero CSV/JSONL export download, `retention_until` unenforced, **zero tenant deletion, GDPR erasure, or account offboarding routes**. | **MISSING** |

---

## 2. Recommended Monetization & Pricing Architecture (Strategic Hypothesis — Unvalidated by Customer Demand)

*(Clearly separated as strategic hypothesis requiring design-partner discovery interviews before locking pricing.)*

Do **not** charge bps (% of payment volume) while acting purely as a non-custodial governance/forensics SaaS — bps pricing invites comparison against Stripe/PayPal processing fees (`2.9%`) and complicates regulatory optics. Instead, pair **Platform Tier + Consumption Usage**:
1. **Per Active Agent & Governance Volume (`Guardian`):**
   - *Free / Sandbox:* 1 org, 3 agents, 1,000 evaluations/mo, 7-day replay retention.
   - *Growth (\$99–\$299/mo):* Includes 25 active agents + 25,000 policy evaluations/mo, then **\$0.005–\$0.01 per authorized transaction** (matches API infra/audit cost + scales cleanly with agent autonomy).
2. **Forensic Archive & Time Machine Retention (`GhostPay`):**
   - Tiered retention (`30d / 1yr / 7yr` WORM-immutable archive) + counterfactual batch backtesting quota.
3. **Dispute Operations Recovery (`DisputeOS`):**
   - Base module add-on or per-dispute evidence packet fee (`\$2–\$5/case`) rather than Stripe's steep `%` / success fee unless full autonomous win-back rates are proven.
4. **Enterprise Compliance Plan (`\$1,500–\$5,000+/mo`):**
   - SSO/SAML, custom RBAC/approvals, SIEM/webhook streaming, dedicated 7-year immutable ledger retention, SOC 2 report, BAA/DPA, SLA (`99.9%`).

---

## 3. Minimum Viable Commercial Bar (Required Before Charging \$1)
1. **Working End-to-End Core Product:** Zero P0 security/correctness bugs; PayPal live sandbox + Stripe adapter verified; functional `/payments`, `/agents`, `/passports`, `/ghostpay`, `/disputes`, `/developer`, `/settings` UIs; accurate Python & TS SDKs.
2. **Trust & Data Protection Basics:** Email verification, RBAC fixed, `HttpOnly` auth/session hardening, GDPR/DPDPA org offboarding & PII redaction plan, published ToS + Privacy Policy + DPA.
3. **Commercial Operations:** Usage metering counters per tenant + Stripe Billing checkout/webhooks for plan enforcement + automated Postgres PITR backups + uptime monitoring & status page + real support channel.

