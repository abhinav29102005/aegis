# RC1 Remediation Evidence Audit

- **Branch:** `fix/rc1-guardian-deadlock`
- **Audited Baseline HEAD:** `5c95e76`
- **Prior Remediation Commit Audited:** `377e52e` (`fix(guardian,db): eliminate RC1 PostgreSQL deadlock via advisory xact locks`)
- **Audit Verdict:** `REMEDIATION_DESIGN_SOUND_PG16_UNVERIFIED` (PostgreSQL 16 unavailable on audit host; three SQLite fallback issues identified and resolved locally)

## 1. Scope of Prior Commit `377e52e`

Commit `377e52e` modified 11 files (`662` insertions, `72` deletions), including:
- `packages/database/database/repository.py` (`+29` lines / diff)
- `modules/agentpay-guardian/guardian/domain/service.py` (`+5` lines)
- `services/api/aegis_api/routers/guardian_db.py` (`+1` line)
- `tests/concurrency/test_rc1_deadlock_stress.py` (`461` lines)
- `docs/release/RC1_GUARDIAN_DEADLOCK_REMEDIATION.md`, `docs/release/RC1_FINAL_SIGN_OFF.md`, `docs/release/RC1_LOAD_TEST_BASELINE.md`, and audit index files under `aegis-production-audit/`.

Historical docs (`docs/release/RC1_GUARDIAN_DEADLOCK_REMEDIATION.md` and `docs/release/RC1_FINAL_SIGN_OFF.md`) record the historical PostgreSQL 16 deadlock cycle (`DeadlockDetected`) between concurrent same-tenant `submit_proposal()` calls and the introduction of PostgreSQL transaction-scoped advisory locks via `_acquire_pg_xact_advisory_lock`.

## 2. Verification Baseline on `5c95e76` (Pre-Edit)

Running checks on unmodified `5c95e76` established:

1. **Lint (`ruff`):** `uv run ruff check packages/database/database/repository.py modules/agentpay-guardian/guardian/domain/service.py services/api/aegis_api/routers/guardian_db.py tests/concurrency/` -> `All checks passed!`
2. **Core package/module suites:** `uv run pytest -q packages/contracts/tests packages/database/tests modules/agentpay-guardian/tests modules/ghostpay/tests` -> `173 passed, 1 skipped` (`test_alembic_migrations_upgrade_and_downgrade_postgres` skipped because `AEGIS_TEST_POSTGRES_URL` / PG16 was unset).
3. **Concurrency suite on SQLite fallback (`tests/concurrency/`):** `15 passed, 3 failed`:
   - `test_forced_rollback_and_timeout_leave_no_partial_state` — Failed because `PurchaseProposalRow` persisted after `session.rollback()` under SQLite due to `packages/database/database/session.py` lacking `isolation_level = None` and explicit `"begin"` handling before `SAVEPOINT` (`session.begin_nested()`).
   - `test_hash_chain_monotonicity_under_concurrent_appends` — Failed on SQLite with `sqlite3.IntegrityError: UNIQUE constraint failed: financial_events.correlation_id, financial_events.sequence_number` because SQLite ignores `with_for_update()` and `_acquire_pg_xact_advisory_lock` and allowed overlapping `DEFERRED` reads before insert.
   - `test_concurrent_budget_exhaustion` — Failed because SQLite serialized transactions left threads 4..15 observing `available=0` / `daily_spent=30000` in Layer 1 `PolicyEngine.evaluate()`, raising `PolicyDeniedError` instead of reaching Layer 2 `InsufficientBudgetError`, whereas the test asserted all 12 rejections must be `InsufficientBudgetError`.

## 3. PostgreSQL 16 Execution Evidence Status

- Live PostgreSQL 16 verification remains **NOT VERIFIED** (`BLOCKED`) on this Windows host because no PostgreSQL 16 instance, client binary, or container runtime is present.
- All code changes in this audit preserve `377e52e` advisory locking untouched while resolving the three SQLite/test/CI defects cleanly.

