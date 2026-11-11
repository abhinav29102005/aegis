# Team Handoff Guide — Remaining Work

This repository is pre-configured with frozen canonical contracts (`packages/contracts/`), shared security/database/PayPal core (`packages/{security,database,paypal}`), CI (`.github/workflows/ci.yml`), Docker Compose (`docker-compose.yml`), and a complete **DisputeOS** module (`modules/disputeos/`).

## Remaining Assignments

### 1. AgentPay Guardian (`feature/guardian` -> `modules/agentpay-guardian/`)
- Implement `guardian/{agents,domain,policies,passports,budgets,approvals,payments,api}/` and all 10 required tests.
- Use `LedgerRepository` (`packages/database`) for atomic reservations (`reserve_budget_atomic`) and `PayPalSandboxClient` (`packages/paypal`) for checkout/capture/reconciliation.
- Never allow an LLM node to authorize spend or capture payments.

### 2. GhostPay (`feature/ghostpay` -> `modules/ghostpay/`)
- GhostPay implementation and deployment kit are complete. See `modules/ghostpay/STATUS.md`, `plan.md`, and `DEPLOYMENT.md` for verified checks and operating limits.
- Consume historical `ReplayRequest` snapshots and return deterministic `ReplayResult` without mutating original records or executing payments. Initial authorization replay uses Guardian's public policy-v1 interface.
- Verified event chains, full-content evidence digests, and transaction bindings are implemented. Unified ledger snapshot production, shared dashboard mounting, public server setup, and later Sandbox acceptance remain integration responsibilities.

### 3. Unified API & Worker (`integration/nexus` -> `services/api/`, `services/worker/`)
- Mount `/v1/guardian`, `/v1/ghostpay`, `/v1/disputeos`, `/v1/paypal`, `/v1/audit-events`.
- Implement outbox polling & `PENDING_PROVIDER` reconciliation worker.

### 4. Unified Frontend (`integration/nexus` -> `apps/web/`)
- Initialize Next.js + TypeScript + Tailwind CSS app using `packages/contracts/schemas/contracts.schema.json`.
- Build `/dashboard`, `/agents`, `/passports`, `/payments`, `/payments/[id]`, `/ghostpay`, `/ghostpay/replay/[id]`, `/disputes`, `/disputes/[id]`, `/audit`, `/settings`.
- Use PayPal JS SDK with `NEXT_PUBLIC_PAYPAL_CLIENT_ID` only.

## Branch Rules
1. Do **not** modify `packages/contracts/` on feature branches without coordinating on `integration/nexus`.
2. Run `make test` and `make lint` before opening a PR against `integration/nexus`.

