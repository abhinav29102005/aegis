# 05 — Security, Fraud, Threat Model & Regulatory Applicability Audit

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):** **15 OF 16 THREAT VECTORS CLOSED IN CODE (`SEC-09` PARTIAL FOR UNMOUNTED DISPUTEOS MODULE ROUTER); ADVERSARIAL & 6-ROLE RBAC SUITES PASS `100%`; UPSTREAM DEPENDENCY CVES (`pip-audit`/`npm audit`) FLAGGED.**

---

## 1. Threat Model & Risk Register (`2026-11-12` Integrated)

### 1.1 Identity, Access Control & Multi-Tenancy Threats (OWASP API Top 10 2023)

| ID | Threat Vector | Baseline | Current Status (`2026-11-12`) | Verified Post-Integration Evidence |
| :--- | :--- | :--- | :--- | :--- |
| SEC-01 | Missing RBAC on `/v1/ghostpay/*` | CRITICAL | **CLOSED (GATEWAY + ROUTER)** | `app.py` (`GHOSTPAY_READ`) + internal `ghostpay/api/router.py` (`GHOSTPAY_READ` / `GHOSTPAY_SIMULATE`); `test_rbac_negative_matrix.py`, `test_ghostpay_api.py`, `test_gateway_and_rate_limit.py` PASS. |
| SEC-02 | `ADMIN -> OWNER` escalation & cross-org hijack | HIGH | **CLOSED** | `auth_orgs.py` blocks `ADMIN->OWNER`, uses signed invite tokens (`org_invitations`), `test_auth_billing_erasure.py` & `test_rbac_negative_matrix.py` PASS. |
| SEC-03 | Global JWT rate-limit bucket collision & DoS | HIGH | **CLOSED** | `rate_limit.py` hashes full Bearer (`sha256[:16]`), TTL evicts, Redis sorted-set backend (verified live in Compose & tests). |
| SEC-04 | Env-var secret fallback (`JWT_SECRET` ignored) | HIGH | **CLOSED** | `settings.py` supports legacy + `NEXUS_`/`AEGIS_` aliases & rejects weak production secrets/wildcard CORS (`validate_security_posture`). |
| SEC-05 | Cross-tenant UUID leakage & error leakage | HIGH | **CLOSED** | `tenant.py` strips foreign UUIDs on `403`; `/ready` & webhook routes sanitize exceptions (`test_gateway_and_rate_limit.py`, `test_webhooks_api.py`). |
| SEC-06 | Artifact BOLA across cases within tenant | MEDIUM | **CLOSED (`M2`)** | `disputeos_db.py:464-477` verifies `ev_row.dispute_case_id == case_id` before downloading artifact bytes. |
| SEC-07 | API keys bypass disabled user/SA | MEDIUM | **CLOSED** | `deps.py` enforces active `UserRow.is_active`, `ServiceAccountRow.status`, and active membership (`test_gateway_and_rate_limit.py`). |
| SEC-08 | Browser JWT in `localStorage`, missing headers | HIGH | **CLOSED** | `apps/web` `HttpOnly; SameSite=Lax` cookie BFF (`0` `localStorage` hits), CSP + `X-Frame-Options` + `X-Content-Type-Options` headers. |
| SEC-09 | Unmounted standalone module routers | MEDIUM | **PARTIAL (`GUARDIAN CLOSED; DISPUTEOS DEV-ONLY`)** | M2 hardened `guardian/api/router.py` to reject unauthenticated `X-Tenant-Id` outside dev/test; unified app mounts RBAC `guardian_db` & `disputeos_db`, while unmounted `disputeos/api/router.py` stays unit-test-only scaffolding. |

### 1.2 SSRF, Webhooks & Financial Payment Integrity

| ID | Threat Vector | Baseline | Current Status (`2026-11-12`) | Verified Post-Integration Evidence |
| :--- | :--- | :--- | :--- | :--- |
| SEC-10 | Outbound Webhook SSRF & Response Reflection | CRITICAL | **CLOSED** | `security/ssrf.py` blocks private/loopback/link-local/CGNAT/metadata IPv4/IPv6 + `follow_redirects=False` + HTTP status-only redacted worker errors (`test_worker.py`, `test_webhooks_api.py`, `test_security_adversarial.py`). |
| SEC-11 | Human approval `approved=False` bypassed | CRITICAL | **CLOSED (`M2`+`M3`)** | UI, Python/TS SDKs, `guardian_db.py`, and `guardian/domain/service.py` decline & release reservation cleanly (`test_guardian_hardening.py`). |
| SEC-12 | Cross-intent approval reuse & `quote_hash` bypass | HIGH | **CLOSED (`M2`)** | `approvals/service.py` checks `approval.payment_intent_id == intent.id`; `QuoteSnapshot` enforces unconditional hash & expiry (`test_security_adversarial.py`, `test_contracts.py`). |
| SEC-13 | Inbound PayPal webhook replay | MEDIUM | **CLOSED** | `paypal_webhook_events` unique dedup + `disputeos.paypal.webhook_handler` (`test_webhooks_api.py`). |
| SEC-14 | Outbound webhook lacks timestamp replay guard | MEDIUM | **CLOSED** | Worker, `security/hashing.py`, Python SDK, TS SDK (Node + WebCrypto), and `INTEGRATION_GUIDE.md` unified on `AEGIS-Signature: t=<unix>,v1=<hex>` (`300s` tolerance). |
| SEC-15 | Evidence tampering & GhostPay partial digest | HIGH | **CLOSED (`M2`)** | `ProvenanceVerifier` validates full hash chains; `disputeos/ingestion/normalizer.py` hashes full canonical context (`test_forensics_hardening.py`). |
| SEC-16 | Audit log `DELETE`/`UPDATE` at DB layer | MEDIUM | **CLOSED ON `financial_events`** | Alembic `0003` trigger `trg_aegis_prevent_financial_event_mutation` raises on `UPDATE`/`DELETE` (verified PG16). *(Optional DB trigger on `admin_audit_logs` remains future hardening.)* |

---

## 2. Supply-Chain Vulnerabilities, AI Boundaries & Regulatory Posture
- **Observed Dependency Audit Findings (`2026-11-12`):**
  - `pip-audit` (`make audit`) reported **`11` known vulnerabilities across `4` Python packages**: `langgraph 0.6.11` (`PYSEC-2026-83`), `langgraph-checkpoint 3.0.1` (`PYSEC-2026-2573`, `PYSEC-2026-2574`), `langgraph-sdk 0.2.15` (`PYSEC-2026-2194`, `PYSEC-2026-2575`, `PYSEC-2026-4240`), and `pytest 8.4.2` (`PYSEC-2026-1845`). Upgrading `langgraph` (dev/prod runtime) & `pytest` (dev) is recommended before commercial launch.
  - `packages/sdk-typescript` `npm audit --omit=dev`: **`0` vulnerabilities**.
  - `apps/web` `npm audit --omit=dev`: **`2` vulnerabilities (`1` moderate, `1` high)** in transitive `postcss` under `next@15.x` (`npm audit` indicates `next@16.4.6` remediation).
- **AI / MCP Deterministic Control Boundary (`AGENTS.md` #1):**
  - `guardian/mcp_server.py` (`check_policy`, `propose_payment`, `get_passport_budget`, `list_audit_timeline`) and `disputeos/analysis/llm_client.py` (`sanitize_untrusted_text`, `llm_invocation_logs`) strictly separate AI reasoning from deterministic policy approval, budget reservation, and PayPal capture (`test_copilot_mcp.py`, `test_ai_eval.py`, `test_security_adversarial.py`).
- **Regulatory Perimeter:** Non-custodial governance + GDPR/DPDPA export/crypto-shredding (`erasure.py`), EU/IN/US residency env profiles, and legal docs implemented; external legal counsel sign-off, SOC 2 Type II, & external penetration testing remain pre-commercial requirements (`NOT VERIFIED`).
