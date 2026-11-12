# Budget Exhaustion Enforcement & Denial Semantics

- **Audited Code:**
  - `modules/agentpay-guardian/guardian/domain/service.py` (`GuardianService.submit_proposal()`)
  - `modules/agentpay-guardian/guardian/policies/engine.py` (`PolicyEngine.evaluate()`)
  - `packages/contracts/contracts/policy_v1.py` (`evaluate_policy_v1`)
  - `modules/agentpay-guardian/guardian/budgets/coordinator.py` (`BudgetCoordinator.reserve()`)
  - `packages/database/database/repository.py` (`LedgerRepository.reserve_budget_atomic()`)
  - `services/api/aegis_api/routers/guardian_db.py` (`_raise_http_for_guardian_error`)
  - `tests/concurrency/test_rc1_deadlock_stress.py` (`test_concurrent_budget_exhaustion`)

## 1. Two-Layer Deterministic Enforcement Architecture

`GuardianService.submit_proposal()` enforces spending ceilings via two complementary deterministic controls:

1. **Layer 1 — Deterministic Policy Evaluation (`PolicyEngine.evaluate()`):**
   - Runs before budget reservation inside `submit_proposal()`.
   - Raises `PolicyDeniedError` (`DENIED_EXCEEDS_PASSPORT_BUDGET`, `DENIED_EXCEEDS_DAILY_LIMIT`) when the committed passport state already lacks headroom for the requested `amount_minor`.
   - Mapped by `guardian_db.py` to HTTP `403`.
2. **Layer 2 — Atomic Conditional SQL Reservation (`LedgerRepository.reserve_budget_atomic()`):**
   - Executes atomic `UPDATE spending_passports SET reserved_minor = reserved_minor + :amt WHERE ... (total_budget_minor - spent_minor) - reserved_minor >= :amt`.
   - Catches concurrent pre-commit races where multiple requests pass Layer 1 before earlier transactions commit.
   - Wrapped by `BudgetCoordinator.reserve()` into `guardian.domain.exceptions.InsufficientBudgetError`, mapped by `guardian_db.py` to HTTP `409`.

## 2. Concurrency Test Discrepancy & Fix

- In `tests/concurrency/test_rc1_deadlock_stress.py::test_concurrent_budget_exhaustion`, 15 concurrent `$100` (`10_000`) proposals compete for a `$300` (`30_000`) budget.
- Previously, the test assumed all 12 denials would be Layer 2 `InsufficientBudgetError`. Under serialized transactions (such as SQLite `BEGIN IMMEDIATE` or sequentially ordered commits after the first 3 commits under PG16), threads 4..15 read `available_budget_minor == 0` / `daily_spent == 30_000` in Layer 1 and deterministically raise `PolicyDeniedError` (`DENIED_EXCEEDS_PASSPORT_BUDGET`, `DENIED_EXCEEDS_DAILY_LIMIT`).
- Notice `modules/agentpay-guardian/tests/test_guardian.py` (`test_06_concurrent_70_reservations_cannot_both_succeed`) already treats `(PolicyDeniedError, InsufficientBudgetError)` as valid concurrent denial outcomes.
- Updated `_submit_in_thread` to include `getattr(exc, "reason_codes", None)` and updated `test_concurrent_budget_exhaustion` to accept either `InsufficientBudgetError` or `PolicyDeniedError` with reason code in `{"DENIED_EXCEEDS_PASSPORT_BUDGET", "DENIED_EXCEEDS_DAILY_LIMIT"}`, fail on any unexpected error (`other == []`), assert `3` successes + `12` budget denials, and assert durable DB state (`passport.reserved_minor == 30_000`, `len(reservations) == 3`).

## 3. Verification Observed

- `tests/concurrency/test_rc1_deadlock_stress.py::test_concurrent_budget_exhaustion`: `PASSED` (on SQLite; PG16 execution `NOT VERIFIED`).

