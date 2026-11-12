# RC1 Financial Invariant & Concurrency Verification Report

**Branch:** `release/rc1-c2-payments-ops-load`  
**Database Engine:** Ephemeral `postgres:16-alpine` (`127.0.0.1:55441`, cleaned up on exit)  
**Migrations Applied:** Alembic `0001_initial_schema` -> `0002_aegis_platform_extensions` -> `0003_prod_hardening` (`head`)  

## Verification Commands & Results

1. **Lint (`ruff`):**
   ```bash
   uv run ruff check tests/concurrency/
   ```
   Result: `All checks passed!` (exit code `0`)

2. **Concurrency & Invariant Suite (`pytest` against PostgreSQL 16):**
   ```bash
   DATABASE_URL="postgresql+psycopg://aegis:aegis_conc@127.0.0.1:55441/aegis_conc" \
     uv run pytest -v tests/concurrency/
   ```
   Result: **`8 passed in 2.25s`** (exit code `0`, `0 failed`, `0 skipped`)

## Verified Test Cases (`tests/concurrency/`)

| Test File | Test Name | Invariant Verified | Status |
| :--- | :--- | :--- | :--- |
| `tests/concurrency/test_concurrency_harness.py` | `test_budget_reservation_race_condition_prevention` | 10 concurrent workers ($20 each) against $100 passport: exactly 5 succeed, 5 fail with `InsufficientBudgetError`, `reserved_minor == 10000`, `available == 0` | PASSED |
| `tests/concurrency/test_concurrency_harness.py` | `test_outbox_lease_claim_concurrency` | 6 concurrent workers claiming 30 outbox events via `claim_due_outbox_events`: mutually disjoint claims, zero duplicate claims, all claimed rows transition to `PROCESSING` | PASSED |
| `tests/concurrency/test_concurrency_harness.py` | `test_parallel_payment_proposal_idempotency` | 8 concurrent `POST /v1/guardian/proposals` requests with identical `idempotency_key` return the exact same `payment_intent.id` and persist 1 intent | PASSED |
| `tests/concurrency/test_rc1_financial_invariants.py` | `test_parallel_budget_reservations_under_race` | 10 concurrent workers ($25 each) against $100 passport: exactly 4 succeed, 6 fail; idempotent retry for winning `payment_intent_id` returns the existing reservation without double-reserving | PASSED |
| `tests/concurrency/test_rc1_financial_invariants.py` | `test_single_use_approval_record_consumption` | `ApprovalService.consume_approval` marks `ApprovalRecord` as `CONSUMED` with `consumed_at` set; replay raises `InvalidStateTransitionError` (`already been consumed`) | PASSED |
| `tests/concurrency/test_rc1_financial_invariants.py` | `test_quote_hash_mismatch_and_expiry_rejection` | `ApprovalService.consume_approval` rejects tampered `current_quote_hash` (`ApprovalMismatchError`), amount mismatch (`ApprovalMismatchError`), expired `QuoteSnapshot` (`ApprovalExpiredError`), and expired `ApprovalRecord` (`ApprovalExpiredError` + `EXPIRED` state transition) | PASSED |
| `tests/concurrency/test_rc1_financial_invariants.py` | `test_hash_chain_monotonicity_under_concurrent_appends` | 12 concurrent `append_financial_event` calls across 6 workers for the same `(tenant_id, correlation_id)` yield strict `1..12` sequence numbers, `verify_financial_event_chain` returns `(True, [])`, and payload tampering is detected (`(False, errors)`) | PASSED |
| `tests/concurrency/test_rc1_financial_invariants.py` | `test_outbox_atomicity_commit_and_rollback` | `append_financial_event(..., also_enqueue_outbox=True)` persists both `FinancialEventRow` and `OutboxEventRow` on `commit()`, and persists neither on `rollback()` | PASSED |

## Strict Write Boundary Check

Only files under `tests/concurrency/` and `docs/release/RC1_FINANCIAL_INVARIANT_REPORT.md` were modified or created.
