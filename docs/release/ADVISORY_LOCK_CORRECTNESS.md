# Advisory Lock Correctness Audit (`pg_advisory_xact_lock`)

- **Audited Code:** `packages/database/database/repository.py`, `modules/agentpay-guardian/guardian/domain/service.py`, `packages/database/database/orm.py`
- **Live PostgreSQL 16 Verification:** `NOT VERIFIED` (`BLOCKED` — PG16 unavailable on audit host)

## 1. Lock Primitives Inspected

1. `_acquire_pg_xact_advisory_lock` (`packages/database/database/repository.py`):
   - Acquires PostgreSQL transaction-scoped advisory locks (`pg_advisory_xact_lock`) keyed by domain namespace and key string, automatically released at transaction commit or rollback (preventing session/connection-pool lock leaks).
   - No-op on non-PostgreSQL dialects (SQLite).
2. `acquire_proposal_idempotency_lock` (`packages/database/database/repository.py`):
   - Invoked at Step 0 of `GuardianService.submit_proposal()` (`modules/agentpay-guardian/guardian/domain/service.py`) before proposal/quote/intent persistence and before `append_financial_event()`.
   - Serializes concurrent requests carrying the same `(tenant_id, idempotency_key)` on PostgreSQL so duplicate retries converge on the original `PaymentIntent` without triggering lock-order inversion against `tenants` row locks.
3. `append_financial_event` (`packages/database/database/repository.py`):
   - Uses advisory lock key `("fin_event_seq", f"{tenant_id}:{correlation_id}")` combined with `FinancialEventRow.with_for_update()` to allocate monotonic per-`correlation_id` `sequence_number` values matching `uq_financial_event_corr_seq` on `("correlation_id", "sequence_number")`.

## 2. Schema Constraint Alignment

- `uq_payment_intent_tenant_idemp`: unique constraint on `(tenant_id, idempotency_key)` aligns with `acquire_proposal_idempotency_lock`.
- `uq_budget_reservation_intent`: unique constraint on `payment_intent_id` prevents duplicate reservations per intent.
- `uq_financial_event_corr_seq`: unique constraint on `("correlation_id", "sequence_number")` aligns with `("fin_event_seq", f"{tenant_id}:{correlation_id}")` serialization.
- `uq_idemp_tenant_op_key`: unique constraint on idempotency records.

## 3. SQLite vs. PostgreSQL Concurrency Behavior

- On PostgreSQL 16, advisory locks (`pg_advisory_xact_lock`) and `SELECT ... FOR UPDATE` enforce per-key / per-row mutual exclusion without blocking unrelated tenants or correlation IDs. Multi-tenant and distinct-key PostgreSQL throughput and zero-deadlock execution remain `NOT VERIFIED` pending PG16 execution.
- On SQLite, `pg_advisory_xact_lock` and `FOR UPDATE` are no-ops; with `BEGIN IMMEDIATE` enabled in `packages/database/database/session.py`, write transactions serialize cleanly at transaction start in dev/test runs, preventing sequence collisions on concurrent `append_financial_event` calls without relaxing `uq_financial_event_corr_seq`.

