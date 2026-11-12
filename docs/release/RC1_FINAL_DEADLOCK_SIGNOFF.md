# RC1 Final Deadlock & Concurrency Release Sign-Off

- **Release Target:** AEGIS RC1 (`fix/rc1-guardian-deadlock`)
- **Final Release Gate Verdict:** **`BLOCKED`**

## 1. Gate Criteria Assessment

| Criterion | Status | Evidence / Basis |
| --- | --- | --- |
| PG advisory xact lock design (`377e52e`) audited | `PASSED` | Verified `acquire_proposal_idempotency_lock`, `_acquire_pg_xact_advisory_lock`, `append_financial_event`, and `GuardianService.submit_proposal()` ordering (`ADVISORY_LOCK_CORRECTNESS.md`, `GUARDIAN_TRANSACTION_ATOMICITY.md`) |
| Live PostgreSQL 16 deadlock stress (`[2, 10, 50, 100]` tiers, multi-tenant, distinct keys, rollback/timeout, concurrent worker) | `NOT VERIFIED` (`BLOCKED`) | PostgreSQL 16 unavailable on audit host (`POSTGRES16_ENVIRONMENT_REPORT.md`) |
| Live PostgreSQL 16 trigger & Alembic upgrade/downgrade tests | `NOT VERIFIED` (`BLOCKED`) | Skipped locally (`test_postgres_financial_event_immutability_trigger_and_concurrent_seq`, `test_postgres_migrations_upgrade_and_downgrade` / `test_postgres_migrations_concurrency_and_restart_persistence`) |
| SQLite fallback savepoint atomicity (`test_forced_rollback_and_timeout_leave_no_partial_state` + nested savepoint test) | `PASSED` | Fixed in `packages/database/database/session.py` (`isolation_level = None` + `BEGIN IMMEDIATE`); `18/18` concurrency tests & `test_sqlite_nested_savepoint_rolled_back_by_outer_rollback` pass |
| Concurrent financial event hash-chain monotonicity (`test_hash_chain_monotonicity_under_concurrent_appends`) | `PASSED_ON_SQLITE` / `PG16_NOT_VERIFIED` | Fixed cleanly via SQLite `BEGIN IMMEDIATE` without weakening `uq_financial_event_corr_seq` (`SQLITE_FINANCIAL_CONCURRENCY_POLICY.md`) |
| Concurrent budget exhaustion ceiling (`test_concurrent_budget_exhaustion`) | `PASSED_ON_SQLITE` / `PG16_NOT_VERIFIED` | Classifies Layer 1 `PolicyDeniedError` & Layer 2 `InsufficientBudgetError`; asserts `reserved_minor == 30_000` & `3` reservations (`BUDGET_EXHAUSTION_SEMANTICS.md`) |
| CI PG16 concurrency wiring | `FIXED` | Concurrency fixtures now honor `AEGIS_TEST_POSTGRES_URL` set in `.github/workflows/ci.yml` |
| Full local Python regression suite & Ruff lint | `PARTIAL_FAIL` (Worker TCP test) | `uv run ruff check .` passed; `354 passed, 3 skipped`; pre-existing failure in `services/worker/tests/test_worker.py::test_worker_healthcheck_cli_and_loop_resilience` on Windows (`130.12s > 30.00s` heartbeat window during `127.0.0.1:1` retry) |

## 2. Release Blocking Conditions

AEGIS RC1 **MUST NOT** be declared production-ready until:
1. A live PostgreSQL 16 environment (e.g., GitHub Actions CI or Linux host with PostgreSQL 16) runs Alembic `upgrade head`/`downgrade base`/`upgrade head` cleanly, passes `packages/database/tests/test_database.py` (including PG triggers) and `services/api/tests/test_postgres_integration.py`, and passes all 18 tests in `tests/concurrency/` against PostgreSQL 16 with zero `DeadlockDetected` errors.
2. `services/worker/tests/test_worker.py::test_worker_healthcheck_cli_and_loop_resilience` is verified passing on the Linux/CI release target (or `connect_timeout` is bounded).
