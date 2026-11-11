# AEGIS Threat Model & Trust Assumptions

## 1. Security Invariants (Non-Negotiable)

1. **Deterministic Spending Control**: AI models (`LangGraph` copilot or `DisputeAnalyzer` LLM mode) can propose purchases or summarize disputes, but they never mutate `SpendingPassportRow` budgets, issue approvals, override `PolicyEngine` rules, or invoke PayPal capture directly.
2. **Server-Side Tenant Isolation**: Every authenticated human JWT and API key resolves an `AuthContext` bound to an authorized `tenant_id` (`X-Org-Id` verified against `MembershipRow` or API-key tenant ownership). Cross-tenant ID lookups raise `TenantIsolationError` -> HTTP `403`.
3. **Immutable Financial Provenance**: All state transitions write append-only `financial_events` sequenced per correlation ID with canonical SHA-256 hash chaining (`previous_hash`, `event_hash`) verified via `verify_financial_event_chain`.
4. **Atomic Budget Reservations**: Concurrent spending proposals lock the target `spending_passports` row with `SELECT ... FOR UPDATE` on PostgreSQL before creating `budget_reservations`, preventing double-spend race conditions.
5. **Fail-Closed External Integrations**:
   - PayPal webhook ingestion rejects unverified or unconfigured webhook verification fail-closed with HTTP `401`.
   - Production startup (`APP_ENV=production`) refuses default development `NEXUS_SIGNING_SECRET` / `JWT_SECRET` values via `NexusSettings.validate_security_posture()`.
   - Synthetic DisputeOS demo cases (`is_synthetic=True`, `source_type=SYNTHETIC_DEMO`) raise `SyntheticSubmissionError` -> HTTP `403` before reaching any outbound PayPal adapter.

## 2. Threat Matrix & Mitigations

| Threat Vector | Mitigation Implemented | Residual Risk / Boundary |
| --- | --- | --- |
| Compromised or prompt-injected AI agent overspending | Deterministic `PolicyEngine` (per-tx, daily, total budget, merchant allowlist, category check, expiry) + human approval threshold | Requires valid passport configuration per agent |
| Merchant or quote tampering between decision and checkout | `compute_quote_hash()` binds amount, currency, merchant, and line items to `PaymentIntent.quote_hash` | Downstream external fulfillment occurs off-platform |
| Concurrent double-spend by parallel agent tool calls | PostgreSQL `SELECT ... FOR UPDATE` row lock + idempotency key uniqueness (`tenant_id`, `idempotency_key`) | SQLite test harness lacks cross-connection row locks (PG 16 verified in CI/Docker) |
| Spoofed PayPal webhook events | PayPal `verify-webhook-signature` API verification on `/v1/paypal/webhooks` (fail-closed if unconfigured/invalid) | Requires `PAYPAL_WEBHOOK_ID` + sandbox/live PayPal credentials in deployed env |
| Forged outbound webhook consumers | `AEGIS-Signature` header (`t=<ts>,v1=<hmac_sha256>`) verified with constant-time `hmac.compare_digest` and max age check | Receiver must validate timestamp tolerance to prevent replay |
| Cross-tenant data exfiltration | Mandatory `AuthContext`, RBAC permission matrix (`packages/security/security/auth.py`), tenant-filtered queries, explicit `assert_same_tenant` | Super-tenant operator console not exposed |
| Brute-force or accidental request flood | Sliding-window in-memory rate limiter middleware (`RATE_LIMIT_RPM`) on `/v1/*` routes | Multi-replica horizontal scaling should front API with shared Redis rate limiting |
| Forged synthetic disputes sent to PayPal | Immutable `is_synthetic` DB/domain flag + `SyntheticSubmissionError` gate in `/v1/disputeos/cases/{id}/submit` | None within AEGIS API surface |

## 3. Trust Boundaries

- **Untrusted Inputs**: Browser requests, agent tool proposals (`AuthenticatedProposalRequest`), uploaded artifact files (10 MB size cap + SHA-256 integrity hashing), inbound PayPal webhooks, external LLM text outputs.
- **Trusted Core**: `services/api` RBAC + `packages/security` hashing/JWT/HMAC + `modules/agentpay-guardian` deterministic engine + `packages/database` transactional ledger + PostgreSQL 16.
- **External Boundary**: PayPal Sandbox (`api-m.sandbox.paypal.com`), outbound tenant webhook URLs, optional LLM API providers.
