# PostgreSQL 16 Concurrency Stress Qualification Report

- **Target Release:** AEGIS RC1 (`fix/rc1-guardian-deadlock`)
- **Live PostgreSQL 16 Status:** `NOT VERIFIED` (`BLOCKED` — PostgreSQL 16 is unavailable on this host)

## 1. Required Workload Scope (`tests/concurrency/`)

The concurrency qualification suite comprises 18 tests across three files:
- `tests/concurrency/test_concurrency_harness.py` (3 tests): budget reservation race prevention, outbox lease claim concurrency, parallel payment proposal idempotency.
- `tests/concurrency/test_rc1_deadlock_stress.py` (10 tests):
  - `test_concurrent_identical_proposals_tiers` parameterized over `[2, 10, 50, 100]` concurrent callers sharing an idempotency key
  - `test_concurrent_distinct_idempotency_keys_same_tenant`
  - `test_concurrent_multi_tenant_isolation`
  - `test_concurrent_conflicting_payload_same_idempotency_key` (`IdempotencyConflictError` / `DuplicateIntentError`)
  - `test_concurrent_budget_exhaustion` (`15 x $100` proposals against `$300` ceiling)
  - `test_forced_rollback_and_timeout_leave_no_partial_state`
  - `test_worker_processing_during_concurrent_proposals`
- `tests/concurrency/test_rc1_financial_invariants.py` (5 tests): parallel budget reservations under race, single-use approval record consumption, quote hash mismatch/expiry rejection, hash-chain monotonicity under concurrent appends, outbox atomicity commit/rollback.

Plus `packages/database/tests/test_database.py::test_postgres_financial_event_immutability_trigger_and_concurrent_seq` and `services/api/tests/test_postgres_integration.py::test_postgres_migrations_concurrency_and_restart_persistence`.

## 2. CI Qualification Wiring Fix Applied

- Updated `stress_session_factory` (`test_rc1_deadlock_stress.py`), `pg_or_sqlite_session_factory` (`test_rc1_financial_invariants.py`), and `concurrency_env` (`test_concurrency_harness.py`) to inspect `(os.getenv("DATABASE_URL") or os.getenv("AEGIS_TEST_POSTGRES_URL") or "").strip()`.
- This ensures `.github/workflows/ci.yml` (`AEGIS_TEST_POSTGRES_URL=postgresql+psycopg://aegis:aegis_test_password@localhost:5432/aegis_test`) runs the entire concurrency & deadlock stress suite against `postgres:16-alpine` instead of falling back to SQLite.

## 3. Qualification Verdict

- **SQLite Fallback Run:** `18 passed` (locally observed).
- **PostgreSQL 16 Live Stress & Trigger Tests:** `NOT VERIFIED` (`BLOCKED`). SQLite passing does **not** prove PostgreSQL 16 deadlock absence because SQLite uses file-level `BEGIN IMMEDIATE` serialization rather than PostgreSQL MVCC row locks (`FOR UPDATE`) and `pg_advisory_xact_lock`.

