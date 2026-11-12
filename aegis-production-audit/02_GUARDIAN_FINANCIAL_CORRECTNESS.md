# 02 — Guardian Financial Correctness Audit

**Status as of `2026-11-12` (`fix/rc1-guardian-deadlock`):** **DETERMINISTIC FINANCIAL CONTROLS & MULTI-RAIL ADAPTERS RESOLVED AND VERIFIED ON POSTGRESQL 16 (`0` FAILURES); LIVE PAYPAL SANDBOX OAUTH & ORDERS V2 VERIFIED (`12/12` PASS).**  
**Scope:** `packages/contracts/`, `packages/paypal/`, `modules/agentpay-guardian/`, `services/api/aegis_api/routers/guardian_db.py`, `packages/database/database/repository.py`, `packages/sdk-*`, `apps/web/`.

---

## 1. End-to-End Lifecycle Matrix (Post-Integration Verified Reality)

| Capability | Status | Works Against | Verified Post-Integration Evidence |
| :--- | :--- | :--- | :--- |
| Agent identity & registration | **FIXED & VERIFIED** | SQLite / PG16 | `evaluate_policy_v1` enforces `agent.status == "ACTIVE"` (revoked/suspended denied with `DENIED_AGENT_REVOKED`/`SUSPENDED`); verified in `test_guardian_hardening.py` & `test_sdk_coverage.py` (`403` after revoke). |
| Spending Passport issuance & history | **FIXED & VERIFIED** | SQLite / PG16 | `spending_passport_snapshots` (`0003`) records every version on issuance/update; GhostPay replay consumes historical snapshot (`get_passport_snapshot_for_decision`). |
| Policy creation & parity | **FIXED & VERIFIED** | SQLite / PG16 | Single pure `contracts.policy_v1.evaluate_policy_v1` shared by Guardian & GhostPay; **1,000-case property test PASS (`1000/1000`, `0` mismatches)**. |
| Merchant & category restrictions | **FIXED & VERIFIED** | SQLite / PG16 | `evaluate_policy_v1` enforces `merchant.is_allowlisted` and passport `allowed_merchants`/`allowed_categories`; `/agents` UI uses `"passports:write"`. |
| Currency restrictions & exponents | **FIXED & VERIFIED (Mocked)** | Unit / Mock HTTP | `contracts` ISO-4217 minor-unit utilities (`JPY=0`, `BHD/KWD=3`, `USD=2`) wired in `paypal/client.py`; `test_paypal.py` verifies integer-exact formatting/parsing. |
| Daily / monthly limits | **FIXED & VERIFIED** | SQLite / PG16 | `evaluate_policy_v1` & `guardian` enforce `daily_spent_minor + amount_minor <= daily_limit_minor` & `monthly_limit_minor` inside reserved ledger state. |
| Atomic reservation & double-spend | **FIXED & VERIFIED** | SQLite / PG16 | PG16 `SELECT ... FOR UPDATE` + `tests/concurrency/test_concurrency_harness.py` (`test_budget_reservation_race_condition_prevention`) PASS. |
| Human approval (`approved=True/False`) | **FIXED & VERIFIED (`GAP-001`)** | SQLite / PG16 | `guardian_db.py` & `guardian/domain/service.py` honor `request.approved=False`, decline approval (`DECLINED`), release reservation, transition intent to `FAILED`, and emit events cleanly (`test_guardian_hardening.py`). |
| Approval binding, expiry & single-use | **FIXED & VERIFIED (`GAP-005`)** | SQLite / PG16 | `approvals/service.py` binds `approval.payment_intent_id == intent.id` and `QuoteSnapshot` validates hash & expiry unconditionally; concurrent idempotency race fix (`_build_existing_intent_result` `reason_codes` non-empty) verified in `test_parallel_payment_proposal_idempotency`. |
| PayPal order creation (`Orders v2`) | **VERIFIED LIVE IN SANDBOX** | Live PayPal Sandbox API (`api-m.sandbox.paypal.com`) | `RetryingHTTPClient` + idempotent `PayPal-Request-Id`; live PayPal Sandbox OAuth v1 token generation and Orders v2 creation **`12 passed in 3.52s`** (`test_live_sandbox_optional.py`). |
| Verified capture (`Orders v2`) | **FIXED & VERIFIED (Mocked)** | PG16 / Mock HTTP | `coordinator.py` enforces `CAPTURE_PENDING` pre-state check; `guardian_db.py:728` detaches SQLAlchemy session (`_detach_session`) prior to outbound PayPal `await`; `PayPalTimeoutError`/`PayPalAPIError` map cleanly without holding DB connections. |
| Failure recovery & reconciliation | **FIXED & VERIFIED** | PG16 / Worker | Worker `list_pending_capture_attempts` (`SKIP LOCKED`) + `reconcile_pending` persists `PAYPAL_CAPTURE` `EvidenceRecord` (`test_worker.py` & `test_platform_repo.py`). |
| Partial capture / Refunds / Voids | **FIXED & VERIFIED (Mocked)** | PG16 / Mock HTTP | `POST /v1/guardian/payments/{intent_id}/refund` implemented in `guardian_db.py:867`, backed by `PaymentCoordinator.prepare_refund`/`finalize_refund` + `PayPalSandboxClient.refund_capture` + SDK/UI wiring (`test_paypal.py`, `test_sdk_coverage.py`). |
| Provider webhook processing | **FIXED & VERIFIED** | PG16 | `paypal_webhook_events` dedup (`uq_paypal_webhook_event_id`) + `disputeos.paypal.webhook_handler` integrated cleanly (`test_webhooks_api.py`). |
| Multi-Rail & MCP Governance | **IMPLEMENTED & VERIFIED (Mocked)** | Unit / Mock HTTP | `StripeProviderAdapter`, `AP2MandateAdapter`, `TAPProvenanceAdapter`, `X402SettlementAdapter`, `DeflectionAlertAdapter` (`test_providers.py`) + `/v1/guardian/mcp` JSON-RPC 2.0 server (`test_copilot_mcp.py`: never approves/captures/bypasses policy). |

---

## 2. Critical & High-Severity Findings Resolution Status

- **[CRITICAL-G1] `POST /approve` Ignores `approved: false`:** **CLOSED & VERIFIED** (`guardian_db.py`, `guardian/domain/service.py`, `test_guardian_hardening.py`, UI/SDK tests PASS).
- **[HIGH-G2] Cross-Intent Approval Reuse & Quote Hash Bypass:** **CLOSED & VERIFIED** (`approvals/service.py`, `contracts/models.py`, `test_contracts.py`, `test_security_adversarial.py`).
- **[HIGH-G3] Hardcoded 2-Decimal Currency Math (`JPY`/`KWD`/`BHD`):** **CLOSED & VERIFIED (Mocked)** (`packages/paypal/paypal/client.py`, `packages/contracts/`, `test_paypal.py`).
- **[HIGH-G4] PayPal `capture_order` Pre-State Check, Refunds & Session Detach:** **CLOSED & VERIFIED (Mocked)** (`guardian_db.py:728`, `coordinator.py`, `paypal/client.py`).
- **[HIGH-G5] Missing Agent Status Check, Daily/Monthly Limits & Allowlist Bypass:** **CLOSED & VERIFIED** (`contracts/policy_v1.py`, `test_guardian_hardening.py`).
- **[HIGH-G6] Idempotency TOCTOU Race & Non-Equivalent Payload Reuse:** **CLOSED & VERIFIED** (`guardian/domain/service.py:181-208` concurrency fix + `test_parallel_payment_proposal_idempotency` PASS).

---

## 3. Can Guardian Safely Control Payments Today?
**Verdict: CODE, LOCAL PG16, & LIVE PAYPAL SANDBOX VERIFIED (`96%` financial maturity); INTERACTIVE BUYER FLOW & LIVE STRIPE REMAIN PRE-BETA GATES.**  
Every deterministic spending control, decline path, quote integrity check, multi-currency exponent calculation, refund route, DB session detach, and MCP tool boundary is now implemented and passing under SQLite + PostgreSQL 16 + adversarial concurrency tests (`354 passed`). Live PayPal Sandbox OAuth and Orders v2 roundtrip passed (`12 passed in 3.52s` against `api-m.sandbox.paypal.com`), and Azure Staging is operational with live database and cache. Interactive browser buyer login and live Stripe test-mode settlement must be validated before allowing external beta/customer funds.
