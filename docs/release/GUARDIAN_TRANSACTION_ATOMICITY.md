# Guardian Transaction Atomicity Audit

- **Audited Paths:**
  - `modules/agentpay-guardian/guardian/domain/service.py` (`GuardianService.submit_proposal()`)
  - `services/api/aegis_api/routers/guardian_db.py` (`submit_proposal` & `_raise_http_for_guardian_error`)
  - `services/api/aegis_api/deps.py` (`get_db_session`)
  - `modules/agentpay-guardian/guardian/policies/engine.py` (`PolicyEngine`)
  - `modules/agentpay-guardian/guardian/budgets/coordinator.py` (`BudgetCoordinator`)
  - `packages/database/database/platform_repo.py` (`begin_nested()` webhook dedup)

## 1. End-to-End `submit_proposal()` Transaction Flow

1. **Step 0 — Serialization & Idempotency:** `GuardianService.submit_proposal()` acquires `acquire_proposal_idempotency_lock` and checks for an existing `PaymentIntent` matching `(tenant_id, idempotency_key)`.
2. **Nested Savepoint Persistence (`with session.begin_nested()`):** Persists `PurchaseProposalRow`, `QuoteSnapshotRow`, and `PaymentIntentRow` inside a savepoint so constraint conflicts or validation failures roll back cleanly inside the request transaction.
3. **Deterministic Policy Evaluation:** Appends `PROPOSAL_CREATED`, transitions to `POLICY_CHECK`, runs `PolicyEngine.evaluate()` (`contracts.policy_v1.evaluate_policy_v1`), and appends `POLICY_EVALUATED`.
4. **Outcome Branching & Atomic Budget Reservation:**
   - `DENY` -> transitions intent to `FAILED`, appends `PAYMENT_FAILED`, raises `PolicyDeniedError` (mapped by `guardian_db.py` to HTTP `403`).
   - `ESCALATE` -> persists `ApprovalRecord`, appends audit event, awaits human approval.
   - `ALLOW` -> invokes `BudgetCoordinator.reserve()`, which executes `LedgerRepository.reserve_budget_atomic()` (conditional SQL `UPDATE spending_passports ... WHERE total_budget_minor - spent_minor - reserved_minor >= amount_minor`), appends `BUDGET_RESERVED`, and converts `RepoInsufficientBudgetError` into `guardian.domain.exceptions.InsufficientBudgetError` (mapped by `guardian_db.py` to HTTP `409`).
5. **Outer Session Commit / Rollback Discipline:**
   - `guardian_db.py` calls `session.commit()` only on full handler completion.
   - `deps.py` `get_db_session()` commits on normal exit and executes `session.rollback()` on any raised exception (`HTTPException` / domain error), ensuring zero partial proposal, intent, reservation, or outbox rows leak on error or timeout.

## 2. SQLite Savepoint Bug Identified & Resolved

- Prior to our Phase 5 fix in `packages/database/database/session.py`, `sqlite+pysqlite` lacked `dbapi_conn.isolation_level = None` and an explicit `"begin"` event handler, causing `with session.begin_nested():` in `submit_proposal()` to auto-commit on SQLite even when outer `session.rollback()` ran afterward.
- Adding `dbapi_conn.isolation_level = None` and `@event.listens_for(engine, "begin")` (`BEGIN IMMEDIATE`) restored true outer-transaction rollback over `SAVEPOINT` blocks, verified by `test_forced_rollback_and_timeout_leave_no_partial_state` and `test_sqlite_nested_savepoint_rolled_back_by_outer_rollback`.

