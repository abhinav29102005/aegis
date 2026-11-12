# 02 — Guardian Financial Correctness Audit

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **BLOCKED ON COMPUTER 2 (`work/m2-financial-forensics-ai` NOT YET PUSHED).**  
**Scope:** `packages/contracts/`, `packages/paypal/`, `modules/agentpay-guardian/`, `services/api/aegis_api/routers/guardian_db.py`, `packages/database/database/repository.py` (M1), `packages/sdk-*` & `apps/web/` (M3).

---

## 1. End-to-End Lifecycle Matrix (Current Reality After M1 + M3 Sync)

| Capability | Status | Works Against | Observed Delta in M1 + M3 vs Baseline |
| :--- | :--- | :--- | :--- |
| Agent identity & registration | **PARTIALLY IMPLEMENTED** | SQLite / PG16 | Unchanged (M2): `PolicyEngine.evaluate` still ignores `AgentIdentity.status`. |
| Spending Passport issuance & history | **IMPROVED BY M1 (`SNAPSHOTS ACTIVE`)** | SQLite / PG16 | **M1** added `spending_passport_snapshots` table (`0003`) & auto-records snapshots in `LedgerRepository`; M2 still needed to consume snapshots on replay. |
| Policy creation & versioning | **PARTIALLY IMPLEMENTED** | SQLite / PG16 | Unchanged (M2): `PolicyEngine` hardcodes `"policy-v1"`, diverges from GhostPay. |
| Merchant & category restrictions | **PARTIALLY IMPLEMENTED (UI FIXED)** | SQLite / PG16 | **M3** fixed `/agents` UI (`"passports:write"`), SDK `create_merchant`; **M2** still needed to remove `merchant.is_allowlisted` bypass. |
| Currency restrictions & exponents | **BROKEN (`JPY/BHD`)** | Mocked HTTP | Unchanged (M2): `paypal/client.py` still divides/multiplies by `100` (`:.2f`). |
| Daily / monthly limits | **MISSING** | None | Unchanged (M2): `daily_limit_minor` still ignored in `PolicyEngine`. |
| Atomic reservation & double-spend | **VERIFIED BY TEST (`PG16 + CONCURRENCY`)** | SQLite / PG16 | **M3** added `tests/concurrency/test_budget_reservation_race_condition_prevention` (PASS); M1 PG16 concurrency tests PASS. |
| Human approval (`approved=True/False`) | **STILL BROKEN (`CRITICAL` API BACKEND)** | UI/SDK fixed; Backend **FAILS** | **M3** added Decline UI & `approved: bool` SDK support, **but backend `guardian_db.py:433` & `service.py:290` STILL hardcode `approved=True` (waiting on M2)!** |
| Approval binding, expiry & single-use | **PARTIALLY IMPLEMENTED** | SQLite / PG16 | Unchanged (M2): `approval.payment_intent_id == intent.id` & unconditional `QuoteSnapshot` hash still unfixed in `approvals/service.py` & `contracts/models.py` *(M3 adversarial test checks `approval_id` against another intent only on API boundary/mocked cases — confirm post-M2)*. |
| PayPal order creation (`Orders v2`) | **VERIFIED WITH MOCKS** | Mocked HTTP | Unchanged (M2): Live PayPal Sandbox `NOT VERIFIED`. |
| Verified capture (`Orders v2`) | **UI FIXED / BACKEND STILL BUGGY** | UI shows on `CAPTURE_PENDING`; Backend unguarded | **M3** fixed `/payments/[id]` Capture visibility (`CAPTURE_PENDING`), `attempt.state`, `paypal_approval_url`; **M2** still needed for `coordinator.py` pre-capture check & `PayPal*Error` 502/504 mapping. |
| Failure recovery & reconciliation | **WORKER IMPROVED (`M1`)** | PG16 / Worker | **M1** added `FOR UPDATE SKIP LOCKED` to `list_pending_capture_attempts`; **M2** still needed to save `PAYPAL_CAPTURE` `EvidenceRecord` in `reconcile_pending`. |
| Partial capture / Refunds / Voids | **UI/SDK STUBBED / BACKEND MISSING** | UI/SDK call endpoints; Backend 404/Missing | Unchanged (M2): Zero PayPal refund/void implementation exists yet. |
| Provider webhook processing | **DEDUP HARDENED (`M1`)** | SQLite / PG16 | **M1** added `paypal_webhook_events` deduplication (`uq_paypal_webhook_event_id`) & lazy DisputeOS webhook dispatch hook in `webhooks.py`. |

---

## 2. Critical & High-Severity Findings Status

- **[CRITICAL-G1] `POST /approve` Ignores `approved: false`:** **STILL OPEN (Waiting on M2).** M3 fixed `apps/web` & both SDKs to send `approved: false`, so the frontend/SDK caller side is ready, **but the FastAPI server (`guardian_db.py:433`, `guardian/domain/service.py:290`) still executes approval + budget reservation unconditionally!**
- **[HIGH-G2] Cross-Intent Approval Reuse & Quote Hash Bypass:** **STILL OPEN (Waiting on M2).**
- **[HIGH-G3] Hardcoded 2-Decimal Currency Math (`JPY`/`KWD`/`BHD`):** **STILL OPEN (Waiting on M2).**
- **[HIGH-G4] PayPal `capture_order` Pre-State Check & Uncaught `500`s:** **STILL OPEN (Waiting on M2).**
- **[HIGH-G5] Missing Agent Status Check, Daily/Monthly Limits & Allowlist Bypass:** **STILL OPEN (Waiting on M2).**
- **[HIGH-G6] Idempotency TOCTOU Race & Non-Equivalent Payload Reuse:** **STILL OPEN (Waiting on M2).**

---

## 3. Can Guardian Safely Control Payments for External AI Agents Today?
**Verdict: NO.** M1 secured the infrastructure/database triggers/snapshots/rate limits and M3 fixed the frontend Capture/Merchant/Decline UX and SDKs, **but Computer 2's Guardian + PayPal fixes (`work/m2-financial-forensics-ai`) have not been pushed yet**. Do **not** route real money or external sandbox beta users through `POST /v1/guardian/payments/{id}/approve` until M2 lands and passes negative `approved=False`, approval-binding, JPY currency, and live PayPal Sandbox E2E verification.
