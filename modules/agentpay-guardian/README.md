# AgentPay Guardian (`modules/agentpay-guardian/`)

**Branch:** `feature/guardian`
**Status:** Ready for team implementation (frozen contracts and shared financial core already available in `packages/`).

## Responsibilities
- AI spending passports & merchant allowlists (`guardian/passports/`)
- Deterministic policy engine (`guardian/policies/`)
- Atomic budget reservation coordination (`guardian/budgets/` via `database.LedgerRepository.reserve_budget_atomic`)
- Quote-bound human approval workflows (`guardian/approvals/`)
- PayPal Sandbox checkout & verification (`guardian/payments/` via `paypal.PayPalSandboxClient`)
- LangGraph purchasing copilot (`guardian/agents/` — proposes purchases and explains outcomes ONLY; never authorizes or captures)
- FastAPI router (`guardian/api/` mounted at `/v1/guardian`)

## Required Tests (`tests/`)
1. Authorized $39 purchase within $100 budget -> `SUCCEEDED`
2. $120 purchase denied
3. Unknown merchant denied or escalated
4. Expired approval rejected
5. Changed merchant or amount invalidates authorization
6. Concurrent $70 reservations against $100 budget cannot both succeed
7. Repeated idempotency key cannot create duplicate financial effects
8. Buyer-declined checkout cannot produce a successful ledger entry
9. PayPal timeout results in `PENDING_PROVIDER` until reconciled
10. Successful capture verified against PayPal before settlement

