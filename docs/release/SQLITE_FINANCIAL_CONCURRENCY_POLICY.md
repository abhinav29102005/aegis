# SQLite Financial Concurrency Policy

- **Status:** `ACTIVE_POLICY` (Non-production dev/test-only backend)
- **PostgreSQL 16 Requirement:** Staging and production financial deployments **MUST** run on PostgreSQL 16. SQLite is explicitly unsupported for multi-writer or production workloads.

## 1. Concurrency Semantics Boundary

| Primitive / Mechanism | PostgreSQL 16 (Production) | SQLite (`sqlite+pysqlite`, Dev/Test) |
| --- | --- | --- |
| `pg_advisory_xact_lock(...)` | Enforced per-key across sessions (`repository.py`) | Intentional dialect no-op |
| `SELECT ... FOR UPDATE` | Enforced row-level lock (`with_for_update()`) | Dialect no-op |
| Append-only `financial_events` trigger | PostgreSQL DB trigger (migration `0003` / `orm.py`) | Not enforced in SQLite |
| Concurrent writer isolation | MVCC + row/advisory locks + `READ COMMITTED` | Coarse local file write lock via `BEGIN IMMEDIATE` |

## 2. Hash-Chain Sequence Integrity Without Weakened Constraints

- On `5c95e76`, `tests/concurrency/test_rc1_financial_invariants.py::test_hash_chain_monotonicity_under_concurrent_appends` failed on SQLite with `sqlite3.IntegrityError: UNIQUE constraint failed: financial_events.correlation_id, financial_events.sequence_number` because `DEFERRED` transactions allowed concurrent threads to read the same `MAX(sequence_number)` before inserting.
- We preserved `uq_financial_event_corr_seq` (`("correlation_id", "sequence_number")`) untouched and did **not** add process-local Python mutexes in `LedgerRepository`.
- Instead, configuring `BEGIN IMMEDIATE` on SQLite transactions in `packages/database/database/session.py` makes SQLite acquire its single-writer lock before reading `MAX(sequence_number)`, so `test_hash_chain_monotonicity_under_concurrent_appends` passes deterministically (`12/12` monotonic events, valid hash chain, tamper detection verified) on local dev/test SQLite runs as well.

## 3. Settings Audit Note (`packages/security/security/settings.py`)

- Audited `NexusSettings.validate_security_posture()`: DB password validation skips URLs whose scheme starts with `sqlite`.
- Existing unit tests in `services/api/tests/test_gateway_and_rate_limit.py` and `services/api/tests/test_webhooks_api.py` construct `NexusSettings(app_env="production", database_url="sqlite:///...")` to test production CORS/SSRF controls without PostgreSQL, so `validate_security_posture()` was left compatible with those unit suites. Production deployment gates MUST enforce `postgresql+psycopg://` via environment validation and CI/CD checklists.

