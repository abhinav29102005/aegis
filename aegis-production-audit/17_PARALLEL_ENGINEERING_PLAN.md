# 17 — Git-Safe Parallel Engineering Plan (5 Agents + Integration Owner)

**Purpose:** Enable Horizon 1 & Horizon 2 workstreams to run in parallel without recreating prior `feature/ghostpay` divergence or contract drift regressions.

---

## 1. Strict Workspace & Ownership Boundaries

| Agent / Role | Suggested Branch | Exclusive Write Scope (Directory Ownership) | Forbidden Direct Edits |
| :--- | :--- | :--- | :--- |
| **Integration Owner (Principal / Human Lead)** | `integration/nexus` | `packages/contracts/`, root `pyproject.toml`, `uv.lock`, `packages/security/security/{auth,settings}.py`, `packages/database/database/{orm.py,alembic/*}`, `.github/workflows/`, `docker-compose.yml` | Never allows unreviewed contract changes outside PRs to `integration/nexus` |
| **Agent A — Financial Correctness & PSP Integrations** | `work/h1-guardian-paypal` | `packages/paypal/`, `modules/agentpay-guardian/`, `services/api/aegis_api/routers/guardian_db.py` | `apps/web/`, `modules/ghostpay/`, `orm.py` (request schema changes via Integration Owner) |
| **Agent B — Security, DB Lifecycle, Worker & Infra** | `work/h1-platform-infra` | `services/api/aegis_api/{app.py,deps.py,rate_limit.py,logging_config.py,routers/auth_orgs.py,routers/webhooks.py,routers/overview.py}`, `services/worker/`, `packages/database/database/{repository.py,platform_repo.py,storage.py,session.py}`, `Dockerfiles` | `modules/*`, `apps/web/`, `packages/sdk-*` |
| **Agent C — Frontend & Developer Platform** | `work/h1-web-sdks` | `apps/web/`, `packages/sdk-python/`, `packages/sdk-typescript/`, `docs/sdk/` | `services/*`, `modules/*`, `packages/database/` |
| **Agent D — Investigations & Dispute Intelligence** | `work/h1-ghostpay-disputeos` | `modules/ghostpay/`, `modules/disputeos/`, `services/api/aegis_api/{adapters.py,routers/disputeos_db.py}` | `packages/paypal/` (coordinate PayPal dispute client methods cleanly via contract PR), `apps/web/` |
| **Agent E — QA, E2E & Security Regression** | `work/h1-qa-e2e` | `tests/{adversarial,concurrency,e2e,integration}/`, `apps/web/tests/` | Production runtime business logic in `packages/`, `modules/`, `services/` |

---

## 2. Anti-Drift & Conflict-Prevention Rules

1. **Contract-First Sequencing (Gate 0):** Before Agent C fixes `apps/web` / SDKs or Agent A/D unify `policy-v1`, Integration Owner lands ONE PR on `integration/nexus` freezing any enum/setting/Alembic updates (`QuoteSnapshot._populate_hash`, `Auth/Settings` env aliases, `outbox_events` lease column, `spending_passport_snapshots` table, canonical webhook header `AEGIS-Signature: t=,v1=`).
2. **Branch Hygiene:** All agents branch cleanly from `integration/nexus` (`1be376e` + Gate 0), rebase or fast-forward merge daily against `integration/nexus`, and NEVER commit edits directly onto `main`.
3. **One Lockfile Owner:** Agents never run `uv lock` or edit root `pyproject.toml` on feature branches unless Integration Owner requests it; dependency changes are queued in PR notes.
4. **Remote Reconciliation Check Before Work Starts:** Reconcile the 2 unmerged commits on `origin/feature/ghostpay` (`c6c1cab`, `2a243e1`) onto `integration/nexus` (via read-only diff inspection first) so no contributor code is overwritten.

---

## 3. Recommended Merge Sequence
1. **Batch 0 (Integration Owner):** Align `NexusSettings` env names, export `contracts.schema.json`, add DB migrations (`outbox_events.locked_at`, `spending_passport_snapshots`, `dispute_response_due_by`), resolve `origin/feature/ghostpay` (`2a243e1`).
2. **Batch 1 (Agent B — Security & Worker Foundation):** Merge GhostPay RBAC (`app.py`), `ADMIN != OWNER`, SSRF guard, rate-limit key fix, error sanitization, DLQ/worker lease hardening, Dockerfile `USER`.
3. **Batch 2 (Agent A — Guardian & PayPal):** Merge `approved=False` fix, `payment_intent_id` approval binding, pre-capture state validation, currency exponents, shared `PolicyEngine` pure module.
4. **Batch 3 (Agent D — GhostPay & DisputeOS):** Merge legacy `timemachine/forensics` retirement, DB-backed traces/Agent DNA/investigations, DisputeOS state guard & real PayPal `provide-evidence` integration.
5. **Batch 4 (Agent C — Frontend & SDKs):** Merge fixed Next.js contracts, `HttpOnly` auth/timeout handling, pagination, SDK parity + `detail` parser + synced `INTEGRATION_GUIDE.md`.
6. **Batch 5 (Agent E — Full Verification):** Run Playwright E2E, 20-worker PG16 concurrency stress, RBAC x Role matrix, SSRF checks, live PayPal Sandbox E2E, and Compose boot smoke check before tagging Staging RC1.

