# 05 — Security, Fraud, Threat Model & Regulatory Applicability Audit

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **10 OF 16 THREAT VECTORS FIXED IN M1 + M3; 6 FINANCIAL/DISPUTE/AI VECTORS AWAIT COMPUTER 2 (`work/m2`).**

---

## 1. Threat Model & Risk Register (`2026-11-12` Sync Update)

### 1.1 Identity, Access Control & Multi-Tenancy Threats (OWASP API Top 10 2023)

| ID | Threat Vector | Baseline Severity | Current Status (`498043e`) | Observed Evidence |
| :--- | :--- | :--- | :--- | :--- |
| SEC-01 | Missing RBAC on `/v1/ghostpay/*` | **CRITICAL** | **FIXED AT API GATEWAY (`M1`)** *(Internal router per-method `SIMULATE` check awaits M2)* | `app.py` wires `Permission.GHOSTPAY_READ`; M3 `test_rbac_negative_matrix` & M1 `test_gateway_and_rate_limit` verify `403` for `VIEWER`/`AGENT_SERVICE`. |
| SEC-02 | `ADMIN -> OWNER` privilege escalation & cross-org hijack | **HIGH** | **FIXED (`M1`)** | `auth_orgs.py` forbids non-`OWNER` assigning `OWNER` role/keys; cross-org direct user add replaced by `org_invitations` + `/v1/orgs/invitations/{token}/accept`. Verified by `test_auth_billing_erasure.py` & `test_rbac_negative_matrix.py`. |
| SEC-03 | Global JWT rate-limit bucket collision & memory DoS | **HIGH** | **FIXED (`M1`)** | `rate_limit.py` hashes full Bearer token (`sha256[:16]`), adds TTL bucket eviction, & implements Redis sorted-set backend (verified live in Compose + unit tests). |
| SEC-04 | Env-var secret fallback (`JWT_SECRET` ignored) | **HIGH** | **FIXED (`M1`)** | `settings.py` supports legacy (`JWT_SECRET`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR`, `JWT_ACCESS_TTL_MINUTES`) & `NEXUS_`/`AEGIS_` aliases; `validate_security_posture` rejects `jwt_secret == signing_secret`, `"aegis"` DB passwords, wildcard `"*"` CORS in staging/prod. |
| SEC-05 | Cross-tenant UUID leakage on 403 & error leakage | **HIGH** | **FIXED (`M1`)** | `tenant.py` omits foreign UUIDs from HTTP 403 detail; `/ready` & `webhooks.py` return sanitized generic errors (`test_gateway_and_rate_limit.py`, `test_webhooks_api.py`). |
| SEC-06 | Artifact BOLA across cases within tenant | **MEDIUM** | **STILL OPEN (`M2`)** | `disputeos_db.py:267-362` awaits Computer 2 (`evidence_record.dispute_case_id == case_id` check). |
| SEC-07 | API keys bypass disabled user/SA; no logout revocation | **MEDIUM** | **FIXED (`M1`)** | `deps.py` checks `UserRow.is_active`, `ServiceAccountRow.status`, and active membership on API keys & JWTs (`test_gateway_and_rate_limit.py`). |
| SEC-08 | Browser JWT in `localStorage`, zero security headers | **HIGH** | **FIXED (`M3` + `M1`)** | `apps/web` uses `HttpOnly; SameSite=Lax` cookie `aegis_session` via `/api/auth/*` & `/api/proxy/*` (zero `localStorage` matches); `middleware.ts` / `next.config.ts` & `app.py` emit CSP / `X-Frame-Options: DENY` / `X-Content-Type-Options: nosniff` / `Referrer-Policy`. |
| SEC-09 | Unmounted standalone insecure routers (`guardian`, `disputeos`) | **MEDIUM** | **STILL OPEN (`M2`)** | Unmounted routers in `modules/agentpay-guardian` & `modules/disputeos` await M2 removal/auth-gating. |

### 1.2 SSRF, Webhooks & Financial Payment Integrity

| ID | Threat Vector | Baseline Severity | Current Status (`498043e`) | Observed Evidence |
| :--- | :--- | :--- | :--- | :--- |
| SEC-10 | Outbound Webhook SSRF & Response Reflection | **CRITICAL** | **FIXED (`M1`)** | `security/ssrf.py` blocks non-HTTPS in prod + private/loopback/link-local/CGNAT/metadata IPv4/IPv6; `webhooks.py` & `processor.py` enforce at registration & delivery with `follow_redirects=False` and HTTP status-only redacted errors (verified by `test_ssrf_kms_erasure_webhooks.py`, `test_webhooks_api.py`, `test_worker.py`, `test_security_adversarial.py`). |
| SEC-11 | Human approval `approved=False` bypassed | **CRITICAL** | **STILL OPEN (`M2`)** | UI/SDK (`M3`) fixed; backend `guardian_db.py:433` & `service.py:290` await Computer 2! |
| SEC-12 | Cross-intent approval reuse & bypassable `quote_hash` | **HIGH** | **STILL OPEN (`M2`)** | `approvals/service.py` & `contracts/models.py` await Computer 2 (`M3` adversarial test verifies intent/quote tamper at mock/API checks — re-verify full fix on M2). |
| SEC-13 | Inbound PayPal webhook lacks replay deduplication | **MEDIUM** | **FIXED (`M1`)** | `paypal_webhook_events` unique table + `record_paypal_webhook_once` wired in `webhooks.py` (`test_webhooks_api.py`). |
| SEC-14 | Outbound webhook signature lacks timestamp replay guard | **MEDIUM** | **FIXED (`M1` + `M3`)** | Worker, `security/hashing.py`, Python SDK, TS SDK (Node + WebCrypto), and `INTEGRATION_GUIDE.md` unified on `AEGIS-Signature: t=<unix>,v1=<hex>` (`300s` tolerance). |
| SEC-15 | Evidence tampering & GhostPay partial digest gaps | **HIGH** | **STILL OPEN (`M2`)** | `provenance/verifier.py` & `disputeos/ingestion/normalizer.py` await Computer 2. |
| SEC-16 | Audit log `DELETE`/`UPDATE` possible at DB layer | **MEDIUM** | **FIXED FOR `financial_events` (`M1`)** | Alembic `0003` creates `trg_aegis_prevent_financial_event_mutation` (`BEFORE UPDATE OR DELETE` raising exception), verified on live PG16 in `test_database.py` and `restore_verify.sh`. *(Column hash chain on `admin_audit_logs` remains optional enhancement.)* |

### 1.3 AI Agent & Compliance Update
- **Deterministic Boundary (`M1+M3`):** `ADMIN->OWNER`, `/v1/ghostpay/*` RBAC, webhook SSRF, and frontend auth hardening are closed. Remaining AI controls — live OpenAI/Gemini/Anthropic adapters with prompt-injection sanitization & semantic `CitationValidator` (`GAP-019`), plus `AGENT_SERVICE` capture/approval parity (`GAP-001`, `GAP-005`) — await Computer 2.
- **GDPR / India DPDPA / PCI v4.0.1 (`M1+M3`):** Added `GET /v1/privacy/export`, `POST /v1/privacy/erasure-requests`, crypto-shredding (`erasure.py`), EU-GDPR / IN-DPDPA / US-EAST residency env configs (`deploy/linux-staging/`), `/legal/{terms,privacy,dpa}` pages, and CSP/security headers (`apps/web`). Email verification tokens + `/register` abuse throttling added (`auth_orgs.py`); SMTP delivery & legal counsel sign-off still pending.
