# AEGIS Platform Status & System Health

**Status Dashboard:** [https://status.aegis-platform.test](https://status.aegis-platform.test)  
**Last Updated:** November 12, 2026 04:30 UTC  
**Overall System State:** <span style="color:#10b981; font-weight:bold;">● ALL SYSTEMS OPERATIONAL</span>

---

## 1. Live Component Status Matrix

| Component | Architecture Role | Target SLA | 30-Day Uptime | Current Status |
| :--- | :--- | :--- | :--- | :--- |
| **API Control Plane** | FastAPI REST endpoints (`/v1/*`) | 99.9% | 99.98% | <span style="color:#10b981;">Operational</span> |
| **AgentPay Guardian** | Deterministic policy evaluation & budget engine | 99.99% | 100.0% | <span style="color:#10b981;">Operational</span> |
| **Canonical Ledger** | PostgreSQL 16 hash-chained financial events | 99.99% | 100.0% | <span style="color:#10b981;">Operational</span> |
| **Background Worker** | Transactional outbox & reconciliation worker | 99.9% | 99.95% | <span style="color:#10b981;">Operational</span> |
| **GhostPay Forensics** | Read-only replay & counterfactual simulator | 99.9% | 100.0% | <span style="color:#10b981;">Operational</span> |
| **DisputeOS Engine** | Evidence graph, contradiction check & draft review | 99.9% | 99.96% | <span style="color:#10b981;">Operational</span> |
| **Operator Console** | Next.js 15 Web application (`apps/web`) | 99.9% | 99.97% | <span style="color:#10b981;">Operational</span> |
| **PayPal Sandbox Adapter** | External PayPal Orders v2 / Webhook gateway | 99.5% | 99.82% | <span style="color:#10b981;">Operational</span> |

---

## 2. Service Level Commitments (SLA)

### 2.1. Availability Commitment
AEGIS commits to providing an **Annual Uptime Percentage of at least 99.9%** across the API Control Plane, AgentPay Guardian policy verification, and the Canonical Ledger.

### 2.2. Deterministic Latency Targets
- **Policy Decision Latency (P95):** $< 45\text{ ms}$ (deterministic in-memory policy execution over cached Spending Passports).
- **Atomic Budget Reservation (P95):** $< 15\text{ ms}$ (PostgreSQL row-level locking via `SELECT ... FOR UPDATE`).
- **Webhook Dispatch Latency:** $\ge 99.0\%$ of outbound webhooks dispatched within 30 seconds of database commit.

### 2.3. Cryptographic Ledger Integrity Guarantee
AEGIS guarantees **100% mathematical integrity** of the SHA-256 event hash chain. Any detected broken link in a correlation chain is automatically classified as a SEV-1 incident.

---

## 3. SLA Service Credit Schedule

In the event that AEGIS fails to meet the 99.9% monthly availability threshold, eligible enterprise customers may claim service credits:

| Monthly Availability Percentage | Service Credit Percentage |
| :--- | :--- |
| **99.0% – 99.89%** | 10% credit applied to monthly invoice |
| **95.0% – 98.99%** | 25% credit applied to monthly invoice |
| **< 95.0%** | 50% credit applied to monthly invoice |

*Note: Scheduled maintenance windows (notified at least 72 hours in advance) and external payment network disruptions (e.g., PayPal Sandbox/Live downtime) are excluded from SLA downtime calculations.*

---

## 4. Incident & Maintenance Log

### November 12, 2026: Multi-Tenant Architecture & Workspace Hardening
- **Type:** Scheduled Upgrade
- **Duration:** 03:00 – 03:30 UTC
- **Impact:** None (zero-downtime database migration `0002_aegis_platform_extensions`).
- **Outcome:** Successfully deployed multi-tenant organization models, 6-role RBAC, and background worker outbox.

---

## 5. Subscribing to Status Updates

To receive automated status and incident alerts:
- **Webhook Subscription:** Configure a webhook endpoint in the AEGIS Console (`/developer`) subscribed to `SYSTEM_STATUS_ALERT` events.
- **Email Notifications:** Subscribe via the status portal at `https://status.aegis-platform.test`.
- **Emergency Escalation:** For suspected SEV-1 outages, contact the 24/7 on-call desk at `ops-pager@aegis-platform.test`.
