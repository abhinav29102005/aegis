# AEGIS RC1 — P0 PostgreSQL Deadlock Remediation Report

**Status:** **RESOLVED & VERIFIED ON POSTGRESQL 16**  
**Branch:** `fix/rc1-guardian-deadlock`  
**Audit Date:** `2026-11-12`  

---

## 1. Executive Summary

The RC1 P0 blocker — `psycopg.errors.DeadlockDetected` on concurrent `POST /v1/guardian/proposals` requests (`tests/concurrency/test_concurrency_harness.py::test_parallel_payment_proposal_idempotency` and `98.0%` failure rate under same-tenant load in `tests/load/load_benchmark.py`) — has been reproduced with PostgreSQL 16 lock diagnostics, eliminated at the root cause without adding global application mutexes or relaxing any financial invariant, and verified across **3 consecutive PG16 concurrency stress runs (`18 passed` × 3)**, **full regression (`354 passed, 3 skipped` on PG16)**, and **load testing (`0.0%` error rate at `c=10` and `c=25`)**.

---

## 2. Confirmed Root Cause & PostgreSQL Lock Diagnostics

### 2.1 Observed Deadlock Trace (`postgres:16-alpine`, `log_lock_waits=on`, `deadlock_timeout=100ms`)

Running `test_parallel_payment_proposal_idempotency` against PG16 captured the exact cycle between two concurrent transactions (`Process 115` and `Process 118`):

- **Process 115** (won `uq_payment_intent_tenant_idemp` insert first) executed:
  ```sql
  SELECT tenants.id FROM tenants WHERE tenants.id = $1::UUID FOR UPDATE
  ```
  inside `LedgerRepository.append_financial_event()`, blocking on tuple `(0,1)` of `tenants` waiting for `ShareLock` on `transaction 751` (held by Process 118 because Process 118's earlier inserts into `purchase_proposals` / `quote_snapshots` acquired FK `FOR KEY SHARE` on the referenced `tenants` row).
- **Process 118** executed:
  ```sql
  INSERT INTO payment_intents (...) VALUES (...)
  ```
  blocking on `uq_payment_intent_tenant_idemp` waiting for `ShareLock` on `transaction 746` (held by Process 115).

### 2.2 Two Distinct Deadlock Triggers from the Same Anti-Pattern

1. **Parallel Identical-Key Proposals (`test_parallel_payment_proposal_idempotency`):** Both transactions acquire `FOR KEY SHARE` on `tenants` via `purchase_proposals` / `quote_snapshots` FK inserts; Winner inserts `payment_intents` (holding unique-index lock) and then upgrades its `tenants` lock to `FOR UPDATE` in `append_financial_event()`; Loser blocks on `uq_payment_intent_tenant_idemp` while still holding `FOR KEY SHARE` on `tenants`.
2. **Parallel Distinct-Key Proposals for the Same Tenant (`load_benchmark.py`, `98.0%` error rate):** Tx1 and Tx2 both insert `purchase_proposals` / `quote_snapshots` / `payment_intents` (both holding `FOR KEY SHARE` on `tenants`), and then both attempt `SELECT tenants.id ... FOR UPDATE` in `append_financial_event()`, creating a classic `FOR KEY SHARE -> FOR UPDATE` lock-upgrade deadlock even when `idempotency_key`s are completely distinct.

---

## 3. Principled Concurrency Fix & Lock Acquisition Order

### 3.1 Implemented Changes

1. **Decoupled Sequence/Hash-Chain Locking from `tenants` Row Locks ([`packages/database/database/repository.py`](../../packages/database/database/repository.py)):**
   - Replaced `SELECT tenants.id ... FOR UPDATE` in `LedgerRepository.append_financial_event()` with a transaction-scoped PostgreSQL advisory lock:
     `_acquire_pg_xact_advisory_lock("fin_event_seq", f"{tenant_id}:{correlation_id}")` (`SELECT pg_advisory_xact_lock(:lock_id)` using a deterministic signed 64-bit SHA-256 key).
   - **Why `(tenant_id, correlation_id)`:** `FinancialEventRow.sequence_number` and `previous_event_hash` form a per-correlation hash chain (`uq_financial_event_corr_seq`), not a global single-row counter across unrelated tenant payments. Advisory locking on `(tenant_id, correlation_id)` preserves strict monotonic sequencing and tamper-evident hash-chain integrity while eliminating all `tenants` table/row/FK lock contention between concurrent distinct proposals.
2. **Idempotency-Key Transaction Serialization ([`packages/database/database/repository.py`](../../packages/database/database/repository.py), [`modules/agentpay-guardian/guardian/domain/service.py`](../../modules/agentpay-guardian/guardian/domain/service.py)):**
   - Added `LedgerRepository.acquire_proposal_idempotency_lock(tenant_id, idempotency_key)` using `_acquire_pg_xact_advisory_lock("proposal_idemp", f"{tenant_id}:{idempotency_key}")`.
   - `GuardianService.submit_proposal()` acquires this narrow advisory lock **before** `get_intent_by_idempotency()`, serializing only concurrent retries sharing the exact same `(tenant_id, idempotency_key)` while allowing distinct proposals for the same or different tenants to proceed in parallel.
   - `DuplicateIntentError` is raised cleanly if a serialized retry carries a different `quote_hash` or `amount_minor`.
3. **Explicit Commit Boundary in API Router ([`services/api/aegis_api/routers/guardian_db.py`](../../services/api/aegis_api/routers/guardian_db.py)):**
   - `submit_proposal()` explicitly calls `session.commit()` before returning `ProposalSubmissionResponse` so database state and transaction-scoped advisory locks are committed before HTTP response bytes are sent.

### 3.2 Canonical Lock Acquisition Order

1. `pg_advisory_xact_lock("proposal_idemp", tenant_id:idempotency_key)` (at start of `submit_proposal()`)
2. Read-only validation of `AgentIdentity`, `Merchant`, `SpendingPassport`, and `get_intent_by_idempotency()`
3. `PurchaseProposalRow`, `QuoteSnapshotRow`, `PaymentIntentRow`, `AuthorizationDecisionRow` inserts (FK `FOR KEY SHARE` on parent rows; no `FOR UPDATE` upgrade on `tenants`)
4. Atomic conditional SQL budget reservation (`UPDATE spending_passports SET reserved_minor = reserved_minor + :amt WHERE id = :id AND tenant_id = :tid AND status = 'ACTIVE' AND (reserved_minor + spent_minor + :amt) <= total_budget_minor`)
5. `pg_advisory_xact_lock("fin_event_seq", tenant_id:correlation_id)` inside `append_financial_event()` -> `FinancialEventRow` + atomic `OutboxEventRow` insert
6. `session.commit()` releasing all row and advisory xact locks atomically

---

## 4. Verification & Benchmark Evidence

### 4.1 Expanded Concurrency Stress Suite (PG16, 3 Consecutive Runs)

Command: `uv run pytest -v tests/concurrency/` against isolated `postgres:16-alpine` (`0003_prod_hardening`):

- **Run 1:** `18 passed in 4.92s`
- **Run 2:** `18 passed in 4.98s`
- **Run 3:** `18 passed in 4.90s`

Scenarios covered in [`tests/concurrency/test_concurrency_harness.py`](../../tests/concurrency/test_concurrency_harness.py), [`tests/concurrency/test_rc1_financial_invariants.py`](../../tests/concurrency/test_rc1_financial_invariants.py), and [`tests/concurrency/test_rc1_deadlock_stress.py`](../../tests/concurrency/test_rc1_deadlock_stress.py):
- `2`, `10`, `50`, and `100` concurrent identical proposals -> converge on 1 `PaymentIntent`, 1 `BudgetReservation`, exact `reserved_minor`, valid hash chain, 0 deadlocks.
- `25` concurrent distinct idempotency keys for the same tenant -> `25/25` succeed, 0 deadlocks.
- Multi-tenant parallel burst (`2` tenants × `15` concurrent proposals) -> strict tenant isolation, 0 deadlocks.
- Conflicting payload sharing an idempotency key -> exactly 1 succeeds, conflicting retry raises `DuplicateIntentError`.
- Concurrent budget exhaustion (`$300` ceiling, `15 × $100` concurrent proposals) -> exactly `3` approved, `12` denied (`INSUFFICIENT_BUDGET`), `reserved_minor == 30000`.
- Forced rollback & PostgreSQL `statement_timeout` -> zero partial intents, reservations, events, or outbox rows.
- Concurrent `OutboxWorker.process_outbox_batch(limit=10)` polling during `20` parallel proposal submissions -> 0 worker errors, 0 deadlocks.

### 4.2 Load Benchmark Before vs. After (`tests/load/load_benchmark.py`, PG16 + Single-Worker Uvicorn, `RATE_LIMIT_RPM=10000`)

| Endpoint | Conc | Reqs | Before RPS / Err% | After RPS / Err% | After p50 (ms) | After p95 (ms) | After p99 (ms) |
|---|---:|---:|---|---|---:|---:|---:|
| `POST /v1/guardian/proposals` | 10 | 50 | `1.78` / `98.0%` (`201:1, 500:29, 0:20`) | **`63.35` / `0.0%` (`201:50`)** | `124.48` | `325.18` | `364.85` |
| `POST /v1/guardian/proposals` | 25 | 50 | `1.39` / `98.0%` (`201:1, 500:36, 0:13`) | **`60.96` / `0.0%` (`201:50`)** | `306.40` | `690.58` | `776.33` |
| `GET /health` | 10 / 25 | 50 | `1188.59` / `1281.95` (`0.0%`) | `1378.21` / `1483.37` (`0.0%`) | `6.18` / `10.76` | `11.76` / `30.34` | `15.73` / `31.86` |
| `GET /v1/guardian/payments/{id}` | 10 / 25 | 50 | `343.23` / `294.35` (`0.0%`) | `339.42` / `268.00` (`0.0%`) | `28.49` / `74.77` | `37.19` / `141.30` | `40.30` / `152.78` |
| `POST /v1/ghostpay/replay/by-payment/{id}` | 10 / 25 | 50 | `122.25` / `117.82` (`0.0%`) | `112.94` / `123.32` (`0.0%`) | `78.58` / `169.94` | `136.83` / `275.56` | `143.15` / `289.16` |
| `GET /v1/disputeos/cases` | 10 / 25 | 50 | `220.69` / `207.46` (`0.0%`) | `300.49` / `238.96` (`0.0%`) | `30.97` / `86.05` | `44.67` / `139.82` | `52.16` / `141.46` |

### 4.3 Full Repository Checks

- `uv run ruff check .`: `All checks passed!`
- Full PG16 `uv run pytest -q`: **`354 passed, 3 skipped, 3 warnings in 30.72s`**
- TypeScript SDK (`packages/sdk-typescript`): `typecheck` passed, `35 + 3 = 38 passed`
- Next.js Web (`apps/web`): `typecheck` passed, `eslint` `0 errors` (`4 warnings`), `3 passed`

---

## 5. Remaining Concurrency Considerations & External Scope

- `pg_advisory_xact_lock` provides cross-process serialization on PostgreSQL; SQLite test/dev sessions fall back to SQLite's database-level write lock.
- External provider verification (live PayPal Sandbox credentials) and live VPS deployment remain `BLOCKED / NOT VERIFIED` in this offline environment.
