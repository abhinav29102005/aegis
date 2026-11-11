# 02 — Guardian Financial Correctness Audit

**Scope:** `packages/contracts/`, `packages/paypal/`, `packages/security/`, `modules/agentpay-guardian/`, `services/api/aegis_api/routers/guardian_db.py`, `packages/database/database/repository.py`

---

## 1. End-to-End Lifecycle Matrix (Current Reality)

| Capability | Status | Works Against | Primary Evidence |
| :--- | :--- | :--- | :--- |
| Agent identity & registration | **PARTIALLY IMPLEMENTED** | SQLite / PG16 (via `guardian_db.py`) | Registered in `guardian_db.py:130`, **never checked** during spend eval (`PolicyEngine.evaluate` ignores `AgentIdentity.status`) |
| Spending Passport issuance | **VERIFIED BY TEST** | In-memory / SQLite / PG16 | `guardian_db.py:251-289`, `LedgerRepository.create_passport`; mutates in place on PATCH |
| Policy creation & versioning | **PARTIALLY IMPLEMENTED** | In-memory / SQLite / PG16 | Hardcodes `"policy-v1"` (`policies/engine.py:32`); never inspects `passport.policy_version` |
| Merchant & category restrictions | **PARTIALLY IMPLEMENTED** | In-memory / SQLite / PG16 | `engine.py:110-126` (`merchant.is_allowlisted` bypasses passport `allowed_merchant_ids`) |
| Currency restrictions | **PARTIALLY IMPLEMENTED** | In-memory / SQLite / PG16 | Enforced in `engine.py:65-70` (emits wrong `DENIED_CATEGORY_NOT_ALLOWED` code) |
| Daily / monthly limits | **MISSING** | None | `daily_limit_minor` field exists (`models.py:102`) but unimplemented in `PolicyEngine` & `BudgetCoordinator`; monthly absent |
| Atomic reservation & double-spend | **VERIFIED BY TEST** | SQLite / PG16 (`UPDATE` lock) / Thread Lock (RAM) | Conditional atomic `UPDATE` (`repository.py:537-557`) passes 2-thread PG16 race test (`test_postgres_integration.py`) |
| Human approval (`approved=True/False`) | **BROKEN (`CRITICAL`)** | Failing when `approved=False` | `guardian_db.py:433-439`, `guardian/api/router.py:94`, `guardian/domain/service.py:290` **ignore `request.approved`** |
| Approval binding, expiry & single-use | **PARTIALLY IMPLEMENTED** | In-memory / SQLite / PG16 | `ApprovalService.consume_approval` binds merchant/amount/currency/quote_hash & expiry, **omits `approval.payment_intent_id == intent.id`** |
| PayPal order creation (`Orders v2`) | **VERIFIED WITH MOCKS** | Mocked HTTP (`httpx.MockTransport`) | `packages/paypal/paypal/client.py:183-240`; **live sandbox `NOT VERIFIED`** |
| Buyer approval & decline | **PARTIALLY IMPLEMENTED** | Mocked HTTP / SQLite / PG16 | `guardian_db.py:495,538`; lacks state pre-check & `PayPal`/API error handler mapping |
| Verified capture (`Orders v2`) | **VERIFIED WITH MOCKS (BUGGY)** | Mocked HTTP | Calls `paypal_client.capture_order` *before* checking `CAPTURE_PENDING` (`coordinator.py:225-260,361`); partial capture `409` rejected; 2-decimal math bug |
| Failure recovery & reconciliation | **PARTIALLY IMPLEMENTED** | Mocked HTTP / SQLite / Worker | `PayPalTimeoutError` holds reservation (`PENDING_PROVIDER`) -> worker reconciles; **reconcile misses `PAYPAL_CAPTURE` EvidenceRecord** |
| Partial capture / Refunds / Voids / Chargebacks | **MISSING** | None | Zero refund (`POST /v2/payments/captures/{id}/refund`), void, partial capture, or dispute/chargeback webhook handlers |
| Provider webhook processing | **PARTIALLY IMPLEMENTED** | Mocked HTTP | `webhooks.py:161-220` verifies signature fail-closed & records `PAYPAL_WEBHOOK_RECEIVED`; lacks event-ID dedup & state reconciliation triggers |

---

## 2. Critical & High-Severity Findings

### [CRITICAL-G1] `POST /approve` Ignores `approved: false` — Rejection Approves & Consumes Payment!
- **Files:** `services/api/aegis_api/routers/guardian_db.py:412-440` (`approve_proposal`), `modules/agentpay-guardian/guardian/api/router.py:86-101`, `modules/agentpay-guardian/guardian/domain/service.py:265-302` (`approve_and_consume`), `packages/sdk-python/aegis_sdk/client.py`, `packages/sdk-typescript/src/index.ts`.
- **Evidence Observed:** `HumanApprovalRequest` (`guardian/api/models.py:88`) defines `approved: bool = True`. Neither `guardian_db.py:433-439` nor `guardian/api/router.py:94` passes `request.approved` into `svc.approve_and_consume(...)`, and `GuardianService.approve_and_consume` (`service.py:290`) hardcodes `approved=True` when calling `self.approvals.decide_approval(...)`. Submitting `{"approved": false}` authorizes the payment, moves the intent to `CHECKOUT_READY`, reserves budget, and marks the approval `CONSUMED`. (`apps/web` and both SDKs also hardcode `approved: true` with no decline action.)
- **Severity:** **CRITICAL (`P0`)** | **Status:** `VERIFIED IN CODE`
- **Remediation:** Pass `approved=request.approved` from both routers into `approve_and_consume`; when `False`, call `decide_approval(..., approved=False)`, transition intent to `FAILED` (or `REJECTED`), release any held budget reservation, do not reserve funds, and emit `APPROVAL_DECIDED` / `PAYMENT_REJECTED` events.
- **Verification Required:** API negative test asserting `POST /v1/guardian/proposals/{id}/approve` with `{"approved": false}` denies checkout, leaves passport `reserved_minor == 0`, and prevents subsequent capture.

### [HIGH-G2] Cross-Intent Approval Reuse & Quote Hash Tamper Bypass
- **Files:** `modules/agentpay-guardian/guardian/approvals/service.py:157-221` (`consume_approval`), `modules/agentpay-guardian/guardian/domain/service.py:265-321`, `packages/contracts/contracts/models.py:182-191` (`QuoteSnapshot._populate_hash`).
- **Evidence Observed:**
  1. `consume_approval` checks `bound_merchant_id`, `bound_amount_minor`, `bound_currency`, and `bound_quote_hash`, but **never checks `approval.payment_intent_id == intent.id`** (`service.py:287-302`, `approvals/service.py:188-205`). Two proposals within the same tenant to the same merchant/amount/currency/line-items share a hash and an `ApprovalRecord` from Intent A can be consumed for Intent B if passed via `approval_id` query param (`guardian_db.py:419`).
  2. `approve_and_consume` never re-checks `quote.expires_at` or `passport.expires_at`/`status` after human approval delay.
  3. `QuoteSnapshot._populate_hash` (`contracts/models.py:184`) checks `if not self.quote_hash:` — caller-provided non-empty `quote_hash` bypasses recomputation, and `PolicyEngine.evaluate` never verifies `quote_hash` or `proposal.merchant_id == quote.merchant_id` / `proposal.amount_minor == quote.amount_minor`.
- **Severity:** **HIGH (`P0/P1`)** | **Status:** `VERIFIED IN CODE`
- **Remediation:** Assert `approval.payment_intent_id == intent.id` in `consume_approval`; always verify `quote_hash == compute_quote_hash(...)` and `proposal/quote` field equality in `PolicyEngine` & `QuoteSnapshot`; re-validate passport status and quote/passport expiry upon human approval before reserving funds.

### [HIGH-G3] Hardcoded 2-Decimal Currency Math Corrupts JPY / KWD / BHD
- **Files:** `packages/paypal/paypal/client.py:39-45,195,453` (`minor_to_paypal_value`, `paypal_value_to_minor`).
- **Evidence Observed:** `minor_to_paypal_value` divides unconditionally by `Decimal(100)` (`:.2f`), and `paypal_value_to_minor` multiplies by `Decimal(100)`. PayPal requires 0 decimals for `JPY`/`HUF`/`TWD` and 3 decimals for `BHD`/`JOD`/`KWD`/`OMR`/`TND`. Passing `amount_minor=1000` JPY sends `"10.00"` JPY (error or 100x wrong).
- **Severity:** **HIGH (`P1`)** | **Status:** `VERIFIED IN CODE`
- **Remediation:** Parameterize both helpers on ISO 4217 currency exponent (`CURRENCY_EXPONENTS = {"JPY": 0, ..., "KWD": 3, ...}` defaulting to `2`).

### [HIGH-G4] PayPal `capture_order` Called Before Validating `PaymentState.CAPTURE_PENDING` + Missing Reservation Release on Checkout Error
- **Files:** `modules/agentpay-guardian/guardian/payments/coordinator.py:83-94,160-216,225-260,361,493-534`.
- **Evidence Observed:** `PaymentCoordinator.capture_order` calls `await self.paypal_client.capture_order(...)` at `L255-261` **before** validating `intent.state == PaymentState.CAPTURE_PENDING` (`transition_intent` only executes at `L361` *after* PayPal money capture succeeds!). If `intent.state` is wrong (or racing), PayPal captures money on an invalid transition and throws `InvalidStateTransitionError` post-capture. Likewise, `create_checkout` failure at `L93-94` leaves the budget reservation held, and `reconcile_pending` (`L493-534`) fails to save a `PAYPAL_CAPTURE` `EvidenceRecord`. Also `guardian_db.py:515-535` lacks `try/except` for `PayPalTimeoutError`/`PayPalAPIError`/`GuardianError`, returning unhandled HTTP `500`.
- **Severity:** **HIGH (`P0/P1`)** | **Status:** `VERIFIED IN CODE`
- **Remediation:** Validate state preconditions *before* outbound PayPal HTTP requests; map `PayPalTimeoutError -> 504`, `PayPalAPIError -> 502`, `GuardianError -> 400`; persist `PAYPAL_CAPTURE` `EvidenceRecord` in `reconcile_pending`.

### [HIGH-G5] Missing Agent Status Check, Daily/Monthly Limits & Allowlist Bypass in `PolicyEngine`
- **Files:** `modules/agentpay-guardian/guardian/policies/engine.py:32-131`, `guardian/domain/service.py:161-173`, `guardian/passports/service.py:37-51`.
- **Evidence Observed:**
  1. Neither `GuardianService.submit_proposal` nor `PolicyEngine.evaluate` fetches `AgentIdentity` or checks `agent.status == AgentStatus.ACTIVE` (`SUSPENDED`/`REVOKED` agents can still transact!).
  2. `SpendingPassport.daily_limit_minor` is ignored by `PolicyEngine` (even though `GhostPay` checks it!) and monthly limits do not exist.
  3. `engine.py:110-112` uses `merchant.id in passport.allowed_merchant_ids or merchant.is_allowlisted` — making any org-wide allowlisted merchant bypass per-passport merchant restrictions!
  4. `PassportService.validate_passport_active` is dead code; currency mismatch emits `DENIED_CATEGORY_NOT_ALLOWED`.
- **Severity:** **HIGH (`P1`)** | **Status:** `VERIFIED IN CODE`

### [HIGH-G6] Idempotency Check TOCTOU Race & Non-Equivalent Payload Reuse
- **Files:** `modules/agentpay-guardian/guardian/domain/service.py:87-110`, `guardian/domain/exceptions.py:26-27`, `guardian/payments/coordinator.py:78`.
- **Evidence Observed:** `submit_proposal` queries `get_intent_by_idempotency` outside any DB transaction lock (`service.py:87`) and returns any existing intent without comparing payload equivalence (`amount_minor`, `merchant_id`, `passport_id`) — `DuplicateIntentError` is never raised! And `PaymentCoordinator.create_checkout` (`L78`) has an unimplemented comment `# Check if attempt already exists for this idempotency key`.
- **Severity:** **HIGH (`P1`)** | **Status:** `VERIFIED IN CODE`

---

## 3. Can Guardian Safely Control Payments for External AI Agents Today?
**Verdict: NO.** While the core pattern (non-privileged agent submits proposal -> deterministic `PolicyEngine` -> atomic PG reservation -> server-side PayPal capture) is structurally sound and avoids letting any agent touch PayPal secrets directly, Guardian cannot safely govern real agent payments until: (1) `approved=False` is honored (`CRITICAL-G1`), (2) `AgentIdentity.status`, `daily_limit_minor`, approval-intent binding, and strict passport allowlists are enforced, (3) `PayPal` pre-capture state guards, retries, 0/3-decimal currencies, refunds, and live sandbox flows are verified, and (4) `submit_proposal` idempotency verifies payload equivalence inside the DB transaction.

