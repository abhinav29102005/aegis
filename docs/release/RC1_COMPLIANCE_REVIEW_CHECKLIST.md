# AEGIS RC1 — Section 12: Privacy, Legal, and Compliance Gates Checklist

**Branch:** `release/rc1-c1-security-e2e-deploy`  
**Review Date:** 2026-11-12  
**Scope:** Codebase, infrastructure templates, and legal documentation inspection for RC1 Section 12 compliance gates.

> [!IMPORTANT]
> **Certification Disclaimer:** AEGIS does **NOT** claim SOC 2 Type I/II, ISO/IEC 27001, PCI-DSS Level 1, or HIPAA certification. Technical controls documented below are engineering safeguards verified locally in code and unit/API tests; formal third-party audit attestation and legal counsel sign-off remain external prerequisites prior to General Availability (GA).

---

## Verification Status Legend

- **`VERIFIED LOCALLY`**: Control implementation and/or automated test behavior directly observed in source files and local test execution.
- **`PARTIALLY VERIFIED`**: Core technical mechanism exists in code, but operational/runtime enforcement, scheduled automation, or external configuration is incomplete or unverified.
- **`NOT VERIFIED`**: Requires live staging/production infrastructure, external sub-processor configuration, or formal legal counsel sign-off not executable in local repo inspection.

---

## 1. Section 12 Compliance Gate Matrix

| # | Gate Area | Status | Key Evidence (File & Lines) | Summary & Gaps |
|---|---|---|---|---|
| 1 | Actual Data Retention Behavior | `PARTIALLY VERIFIED` | `packages/database/database/storage.py` (L24, L228–277, L512–527); `packages/database/database/platform_repo.py` (L477); `scripts/backup_pitr.sh` (L19, L180–183); `deploy/linux-staging/postgres-backup.sh` (L15, L35); `deploy/linux-staging/env.{eu-gdpr,in-dpdpa,us-east}.example` | 7-year (`2555` days) / 8-year (`2920` days for IN) WORM retention helpers and `DisputeCaseMetadataRow.retention_until` exist. **Gap:** No automated background purge job enforces the 60-day post-termination account deletion or 30-day staged upload purge stated in `PRIVACY_POLICY.md` (L86–88). |
| 2 | Access & Audit Logging | `VERIFIED LOCALLY` | `packages/database/database/orm.py` (L263–280, L460–472, L599–611); `packages/database/database/platform_repo.py` (L1008–1053); `services/api/aegis_api/routers/auth_orgs.py` (L1355–1382); `erasure.py` (L117–124, L205–213); `billing.py` (L298–306, L345–353, L462–470) | `financial_events` (hash-chained), `admin_audit_logs` (exposed via `GET /orgs/audit-logs` with `Permission.AUDIT_READ`), and `llm_invocation_logs` (token/cost metadata without prompt text) are implemented and wired. |
| 3 | Legal Basis & Jurisdictional Scope | `PARTIALLY VERIFIED` | `docs/legal/PRIVACY_POLICY.md` (L11–16, L92–109); `docs/legal/DATA_PROCESSING_ADDENDUM.md` (L6, L12, L70, L98); `docs/legal/TERMS_OF_SERVICE.md` (L21–31, L124); `deploy/linux-staging/env.{eu-gdpr,in-dpdpa,us-east}.example` | Legal docs cover GDPR, UK GDPR, and CCPA/CPRA, plus EU SCCs (2021/914 Module Two) and Delaware governing law. **Gap:** `env.in-dpdpa.example` and `erasure.py` reference India DPDPA, but `PRIVACY_POLICY.md` and `DATA_PROCESSING_ADDENDUM.md` omit explicit DPDPA 2023 statutory disclosures; `docs/legal/NON_CUSTODIAL_PERIMETER.md` does not exist as a standalone file (non-custodial terms reside in `TERMS_OF_SERVICE.md` §2). |
| 4 | Erasure vs. Financial Audit Immutability | `VERIFIED LOCALLY` | `packages/database/database/orm.py` (L27–44, L694–700); `packages/security/security/erasure.py` (L44–118); `packages/database/database/platform_repo.py` (L1374–1445); `services/api/aegis_api/routers/erasure.py` (L174–214) | PostgreSQL `BEFORE UPDATE OR DELETE ON financial_events` trigger (`aegis_prevent_financial_event_mutation`) blocks ledger mutation. `execute_user_erasure` redacts `UserRow` PII, revokes API keys/invitations, records a `generate_crypto_shred_marker` tombstone, and preserves `financial_events` (`"ledger_preserved": True`). **Caveat:** Callers must not embed raw PII inside immutable `financial_events.payload` JSON. |
| 5 | Encryption Controls (KMS, JWT/HMAC, TLS) | `PARTIALLY VERIFIED` | `packages/security/security/kms.py` (L78–206); `packages/security/security/auth.py` (L157–201, L252–325); `packages/security/security/settings.py` (L214–250); `deploy/linux-staging/aegis.nginx.conf` (L11, L21, L26, L64, L67) | Envelope encryption (`EnvelopeCipher` + `LocalKMSProvider`, per-secret DEKs with HMAC-SHA256 CTR+MAC and AAD binding), HS256 JWT, PBKDF2-SHA256 (600k iterations), HMAC-SHA256 API keys, and fail-closed `validate_security_posture()` verified in code. **Gap:** Only `LocalKMSProvider` is implemented (no AWS/GCP KMS SDK integration); Nginx TLSv1.2/1.3 + HSTS is templated but live host TLS certificates are `NOT VERIFIED`. |
| 6 | Backup & WORM Storage Handling | `PARTIALLY VERIFIED` | `scripts/backup_pitr.sh` (L101–175); `scripts/restore_verify.sh` (L101–244); `packages/database/database/storage.py` (L480–560, L685–715) | `backup_pitr.sh` checks `wal_level`/`archive_mode`/`archive_command` and produces `pg_dump --format=custom` + SHA-256 + JSON manifest. `restore_verify.sh` restores into an ephemeral DB and asserts `alembic current` and `financial_events` trigger presence. `S3ObjectStorage` supports S3 Object Lock (`COMPLIANCE`/`GOVERNANCE`). Live execution against staging PostgreSQL + S3 Object Lock bucket is `NOT VERIFIED`. |
| 7 | Evidence Access Controls (`SEC-06`, RBAC, `AuthContext`) | `VERIFIED LOCALLY` | `packages/security/security/auth.py` (L29–151, L228–249); `services/api/aegis_api/deps.py` (L80–170); `services/api/aegis_api/routers/disputeos_db.py` (L368–490); `packages/database/database/storage.py` (L126–135) | `AuthContext` enforces 6 canonical RBAC roles. `POST /cases/{case_id}/artifacts` requires `Permission.DISPUTES_WRITE`; `GET /cases/{case_id}/artifacts/{artifact_id}` requires `Permission.DISPUTES_READ`, enforces `assert_same_tenant` on artifact + evidence record + case linkage, verifies SHA-256 integrity, and `_validate_tenant_object_key` blocks cross-tenant/path-traversal access. |
| 8 | Customer Offboarding | `PARTIALLY VERIFIED` | `services/api/aegis_api/routers/erasure.py` (L42–214); `services/api/aegis_api/routers/auth_orgs.py` (L1332); `services/api/aegis_api/routers/billing.py` (L100–107, L437–438) | User data export (`GET /privacy/export`), user erasure (`POST /privacy/erasure-requests`), API key revocation, and Stripe `customer.subscription.deleted` -> `CANCELED` (`402 SUBSCRIPTION_INACTIVE`) exist. **Gap:** No self-service organization-level offboarding/deletion endpoint (e.g., `DELETE /orgs/current` for bulk user/artifact offboarding) exists. |
| 9 | Privacy Disclosures (`/legal/*`) | `PARTIALLY VERIFIED` | `apps/web/src/app/legal/{terms,privacy,dpa}/page.tsx`; `apps/web/src/app/legal/layout.tsx`; `apps/web/src/app/login/page.tsx` (L479–487); `apps/web/src/app/status/page.tsx` (L337–339); `apps/web/src/components/AppShell.tsx` (L187); `docs/legal/*.md` | `/legal/terms`, `/legal/privacy`, and `/legal/dpa` pages are implemented and linked in login, status, and app shell UI, backed by `docs/legal/*.md`. **Gap:** Placeholder contact emails (`legal@aegis-platform.internal`, `privacy@aegis-platform.test`, `security@aegis-platform.test`) must be replaced before production. |
| 10 | Cross-Border Data Processing Assumptions | `PARTIALLY VERIFIED` | `packages/security/security/settings.py` (L134, L154–168); `deploy/linux-staging/env.{eu-gdpr,in-dpdpa,us-east}.example`; `services/api/aegis_api/routers/billing.py` (L154) | Regional env overlays pin `AEGIS_DATA_RESIDENCY` (`EU`, `IN`, `US`), PostgreSQL, and S3 bucket/region (`eu-central-1`, `ap-south-1`, `us-east-1`). **Gap:** `AEGIS_DATA_RESIDENCY` is not enforced at runtime against outbound egress; external LLM providers (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`), PayPal, and Stripe (`https://api.stripe.com`) may process metadata outside the regional boundary unless `LLM_PROVIDER=deterministic` or regional endpoints are configured. |

---

## 2. Detailed Verification Findings

### 2.1 Actual Data Retention Behavior
- **Object Storage WORM Retention (`packages/database/database/storage.py`):**
  - `DEFAULT_WORM_RETENTION_DAYS = 2555` (7 years, L24).
  - `compute_worm_retain_until()` (L228–236) and `is_retention_expired()` (L239–247) compute and evaluate UTC retention deadlines.
  - `delete_if_erased()` (L250–277) enforces precedence: `legal_hold=True` blocks deletion -> un-erased subjects are not deleted -> active `retention_until` blocks deletion -> `storage.delete()` is invoked only after expiry.
  - `S3ObjectStorage._resolve_object_lock()` (L512–527) and `_build_put_kwargs()` (L529–560) attach `ObjectLockMode` (`COMPLIANCE` or `GOVERNANCE`), `ObjectLockRetainUntilDate`, and `ContentMD5` when configured.
- **Database & Backup Retention:**
  - `DisputeCaseMetadataRow` defaults `retention_until` to `_utc_now() + timedelta(days=2555)` (`packages/database/database/platform_repo.py`, L477).
  - `scripts/backup_pitr.sh` (L19, L180–183) defaults `BACKUP_PRUNE_DAYS=0` (local pruning disabled unless configured).
  - `deploy/linux-staging/postgres-backup.sh` (L15, L35) defaults `RETENTION_DAYS=14` for local `.sql.gz` dumps.
  - Regional overlays set `AEGIS_S3_RETENTION_DAYS=2555` (`env.eu-gdpr.example` L36, `env.us-east.example` L35) and `2920` (8 years, `env.in-dpdpa.example` L36).
- **Identified Gap:** `docs/legal/PRIVACY_POLICY.md` (L86–88) states account data is deleted within 60 days of termination and uncommitted temporary uploads are purged within 30 days. No automated scheduled worker or cron job in the repository currently executes 30-day or 60-day TTL purges.

### 2.2 Access & Audit Logging
- **`financial_events` (`packages/database/database/orm.py`, L263–280):** Append-only, hash-chained (`previous_event_hash`, `event_hash`), unique per `(correlation_id, sequence_number)`.
- **`admin_audit_logs` (`packages/database/database/orm.py`, L460–472):** Records administrative and privacy actions (`PRIVACY_DATA_EXPORTED`, `GDPR_ERASURE_EXECUTED`, `BILLING_CHECKOUT_CREATED`, `BILLING_PORTAL_CREATED`, `BILLING_SUBSCRIPTION_UPDATED`) with `tenant_id`, `actor_type`, `actor_id`, `action`, `resource_type`, `resource_id`, `details`, and `occurred_at`. Exposed via `GET /orgs/audit-logs` (`services/api/aegis_api/routers/auth_orgs.py`, L1355–1382) gated by `Permission.AUDIT_READ`.
- **`llm_invocation_logs` (`packages/database/database/orm.py`, L599–611; `platform_repo.py`, L1008–1053):** Logs `tenant_id`, `correlation_id`, `module`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, and `estimated_cost_usd_micros` without persisting raw prompt or completion payloads.

### 2.3 Erasure vs. Financial Audit Preservation Conflict
- **Immutability Trigger (`packages/database/database/orm.py`, L27–44, L694–700):** PostgreSQL function `aegis_prevent_financial_event_mutation()` and trigger `trg_aegis_prevent_financial_event_mutation` (`BEFORE UPDATE OR DELETE ON financial_events`) raise an exception on any update or delete.
- **Crypto-Shredding & PII Redaction (`packages/security/security/erasure.py`, L44–118; `packages/database/database/platform_repo.py`, L1374–1445; `services/api/aegis_api/routers/erasure.py`, L174–214):**
  - `execute_user_erasure()` overwrites `UserRow.email` (`erased-{user.id}@redacted.local`), `full_name` (`ERASED_USER`), `password_hash` (`ERASED`), disables `is_active`/`email_verified`/`mfa_enabled`, clears `mfa_secret_encrypted`, sets `erased_at`, marks `MembershipRow.status = "ERASED"`, revokes active `ApiKeyRow` and pending `OrgInvitationRow` records, and creates an `ErasureRequestRow` with `"ledger_preserved": True` (L1438).
  - `erasure.py` router attaches `generate_crypto_shred_marker()` (L193–202) to `details_json` and writes a `GDPR_ERASURE_EXECUTED` admin audit log.
  - Because `financial_events` is never updated or deleted, the PostgreSQL immutability trigger is respected.

### 2.4 Local Test Verification
Executed locally on `release/rc1-c1-security-e2e-deploy`:
```bash
uv run pytest packages/security/tests/test_ssrf_kms_erasure_webhooks.py services/api/tests/test_auth_billing_erasure.py -q
```
**Observed Output:** `13 passed in 3.63s` (no skipped or relaxed assertions).

---

## 3. Legal Counsel Review Blockers (Pre-GA)

The following items **block production / GA launch** until resolved by qualified legal counsel and operations:

1. **Placeholder Legal & Security Contact Addresses:** `docs/legal/PRIVACY_POLICY.md` (L108, L118–119) uses `privacy@aegis-platform.test` and `security@aegis-platform.test`; `apps/web/src/app/legal/terms/page.tsx` (L92) uses `legal@aegis-platform.internal`. Must be replaced with monitored corporate addresses and designated DPO/Grievance Officer details.
2. **India DPDPA 2023 & RBI Localization Alignment:** `deploy/linux-staging/env.in-dpdpa.example` and `erasure.py` reference India DPDPA, but `docs/legal/PRIVACY_POLICY.md` and `docs/legal/DATA_PROCESSING_ADDENDUM.md` only cite GDPR, UK GDPR, and CCPA/CPRA. Counsel must add DPDPA 2023 notices, consent/legitimate-use basis, and Grievance Officer disclosures if operating in India.
3. **Standalone Non-Custodial Perimeter & Sub-Processor List:** `docs/legal/NON_CUSTODIAL_PERIMETER.md` does not exist; non-custodial disclaimers are currently inside `TERMS_OF_SERVICE.md` §2. Additionally, `DATA_PROCESSING_ADDENDUM.md` §5.3 requires maintaining an up-to-date sub-processor list (cloud host, PayPal, Stripe, and any enabled LLM providers), which is not yet published.
4. **Retention Policy vs. Engineering Implementation Alignment:** Counsel must review whether the 60-day post-termination account deletion and 30-day temporary upload purge commitments in `PRIVACY_POLICY.md` (L86–88) require automated TTL enforcement before launch, or whether the policy text must be updated.
5. **Financial Event PII Hygiene & Statutory Basis:** Counsel must confirm that retaining pseudonymized/actor-ID-referenced `financial_events` for 7 years (`2555` days) / 8 years (`2920` days IN) under statutory accounting/anti-fraud exceptions satisfies GDPR Art. 17(3)(b)/(e) and DPDPA erasure exceptions, and engineering must ensure raw PII is never written into `financial_events.payload`.
6. **Cross-Border Egress Governance:** Counsel must approve SCCs / transfer mechanisms for Stripe (`https://api.stripe.com`), PayPal, and external LLM APIs when deployed in `EU` or `IN` residency modes, or mandate `LLM_PROVIDER=deterministic` / regional endpoints.
7. **No Compliance Certification Claimed:** Confirm all marketing, sales, and UI copy explicitly avoids claiming SOC 2 or ISO 27001 certification until an independent audit is completed.
