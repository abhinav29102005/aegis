# SQLite Savepoint Atomicity Fix (`packages/database/database/session.py`)

- **Component:** `packages/database/database/session.py::create_db_engine`
- **Status:** `VERIFIED_ON_SQLITE`

## 1. Defect Reproduced on `5c95e76`

`tests/concurrency/test_rc1_deadlock_stress.py::test_forced_rollback_and_timeout_leave_no_partial_state` failed on SQLite fallback because `PurchaseProposalRow` remained persisted after outer `session.rollback()` executed following `with session.begin_nested():` inside `GuardianService.submit_proposal()`.

## 2. Root Cause Analysis

1. `create_db_engine()` previously configured `sqlite3` `PRAGMA` settings (`foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`) on `"connect"`, leaving Python `sqlite3`'s default implicit transaction behavior (`isolation_level=""`) intact and without a SQLAlchemy `"begin"` listener.
2. When SQLAlchemy opened `SAVEPOINT` via `session.begin_nested()` without first issuing an explicit outer `BEGIN`, SQLite treated nested savepoints in autocommit mode so inner `RELEASE SAVEPOINT` auto-committed `PurchaseProposalRow` immediately, bypassing subsequent `session.rollback()`.
3. Merely emitting `BEGIN` (`DEFERRED`) exposed a second SQLite concurrency hazard: `packages/database/tests/test_database.py::test_concurrent_70_dollar_reservations_against_100_dollar_budget` failed with `sqlite3.OperationalError: database is locked` (`SQLITE_BUSY`) because two threads acquiring `SHARED` read locks in `DEFERRED` transactions cannot upgrade to write locks without an immediate deadlock error (bypassing `busy_timeout`).

## 3. Durable Remediation Implemented

In `packages/database/database/session.py` (`is_sqlite` branch of `create_db_engine`):
- Set `dbapi_conn.isolation_level = None` in `_set_sqlite_pragma` before running the connection `PRAGMA`s.
- Added `@event.listens_for(engine, "begin")` (`_do_sqlite_begin`) executing `conn.exec_driver_sql("BEGIN IMMEDIATE")`.

This guarantees:
- Explicit SQLAlchemy outer transactions wrap every `session.begin_nested()` `SAVEPOINT`, so outer `session.rollback()` rolls back all savepoint-released writes.
- Write-intent locks are acquired cleanly at transaction start (`BEGIN IMMEDIATE`), honoring `busy_timeout` instead of hitting `SHARED` -> `RESERVED` lock upgrade `SQLITE_BUSY` failures.

## 4. Verification Observed

- `tests/concurrency/test_rc1_deadlock_stress.py::test_forced_rollback_and_timeout_leave_no_partial_state`: `PASSED`
- `packages/database/tests/test_database.py::test_sqlite_nested_savepoint_rolled_back_by_outer_rollback`: `PASSED`
- `packages/database/tests/test_database.py::test_concurrent_70_dollar_reservations_against_100_dollar_budget`: `PASSED`
- `packages/database/tests/test_database.py::test_alembic_migrations_upgrade_and_downgrade_sqlite`: `PASSED`

