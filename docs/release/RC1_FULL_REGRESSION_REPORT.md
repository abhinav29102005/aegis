# RC1 Full Regression Qualification Report

- **Branch:** `fix/rc1-guardian-deadlock` (based on `5c95e76`, building on `377e52e`)
- **Host OS:** Windows (SQLite fallback active; PostgreSQL 16 unavailable)
- **Overall Release Qualification Verdict:** `BLOCKED` (Live PG16 concurrency & migration gates `NOT VERIFIED`; pre-existing Windows TCP timeout flake/failure in worker healthcheck test)

## 1. Lint & Code Quality

- `uv run ruff check .`: **PASSED** (`All checks passed!`)

## 2. Suite-by-Suite Observed Results (Post-Final-Edit)

| Suite / Command | Passed | Failed | Skipped | Notes |
| --- | ---: | ---: | ---: | --- |
| `packages/{contracts,security,database,paypal,sdk-python}/tests` | 88 | 0 | 2 | Skips: `test_postgres_financial_event_immutability_trigger_and_concurrent_seq` (no PG), `test_live_sandbox_optional.py` (no PayPal creds) |
| `modules/{agentpay-guardian,ghostpay,disputeos}/tests` | 177 | 0 | 0 | Clean pass |
| `services/api/tests` | 24 | 0 | 1 | Skip: `test_postgres_migrations_concurrency_and_restart_persistence` (no PG) |
| `services/worker/tests/test_worker.py` | 6 | 1 | 0 | Pre-existing failure on Windows: `test_worker_healthcheck_cli_and_loop_resilience` (130.12s TCP connect retry on `127.0.0.1:1` expired the 30s heartbeat before CLI `--healthcheck`) |
| `tests/concurrency/` | 18 | 0 | 0 | All 18 pass on SQLite (`BEGIN IMMEDIATE`); **PG16 NOT VERIFIED** |
| `tests/{adversarial,e2e,integration,load}` | 41 | 0 | 0 | Clean pass |
| **Total** | **354** | **1** | **3** | |

## 3. Code Changes Verified by This Run

1. `packages/database/database/session.py`: Set `dbapi_conn.isolation_level = None` in SQLite `"connect"` hook and execute `BEGIN IMMEDIATE` in SQLite `"begin"` hook. Fixes `SAVEPOINT` auto-commit leak on `session.rollback()` and prevents `SHARED` -> `RESERVED` `SQLITE_BUSY` deadlocks and hash-chain sequence collisions on SQLite.
2. `packages/database/tests/test_database.py`: Added `test_sqlite_nested_savepoint_rolled_back_by_outer_rollback`.
3. `tests/concurrency/test_rc1_deadlock_stress.py`, `test_rc1_financial_invariants.py`, `test_concurrency_harness.py`: Fallback check updated to `(os.getenv("DATABASE_URL") or os.getenv("AEGIS_TEST_POSTGRES_URL") or "").strip()` so CI `postgres:16-alpine` runs exercise PG16 instead of SQLite.
4. `tests/concurrency/test_rc1_deadlock_stress.py::test_concurrent_budget_exhaustion`: Accepts both Layer 2 `InsufficientBudgetError` (`409`) and Layer 1 `PolicyDeniedError` (`403`, reason codes `DENIED_EXCEEDS_PASSPORT_BUDGET` / `DENIED_EXCEEDS_DAILY_LIMIT`) while asserting `3` successes, `12` denials, `passport.reserved_minor == 30_000`, and `len(reservations) == 3`.
