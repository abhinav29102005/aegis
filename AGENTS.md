# AgentPay Nexus — Agent Engineering Guidelines (`AGENTS.md`)

## Workspace Architecture

- `packages/contracts/`: Canonical Pydantic v2 contracts, state machine (`PaymentState`), deterministic quote hashing, and contract fixtures.
- `packages/security/`: Environment settings, HMAC-SHA256 signing, tenant isolation, and financial event hash-chain verification.
- `packages/database/`: SQLAlchemy 2.0 ORM, Alembic migrations, atomic budget reservations, transactional outbox, and tenant-scoped `LedgerRepository`.
- `packages/paypal/`: Isolated PayPal Sandbox Orders v2 client, webhook signature verification, and feature-flagged Disputes v1 client.
- `modules/agentpay-guardian/`: AI agent spending governance, deterministic policy engine, passport/budget/approval services, and LangGraph purchasing copilot.
- `modules/ghostpay/`: Deterministic replay, counterfactual policy simulation, anomaly detection, and evidence provenance timelines.
- `modules/disputeos/`: Dispute case management, evidence graph & contradiction detection, grounded AI summaries, and human-reviewed response drafts.
- `services/api/`: Unified versioned FastAPI service (`/v1/guardian`, `/v1/ghostpay`, `/v1/disputeos`, `/v1/paypal`, `/v1/audit-events`).
- `apps/web/`: Unified Next.js + TypeScript + Tailwind CSS dashboard.

## Rules for Coding Agents

1. **Do not bypass deterministic controls**: Never allow an LLM node or prompt to approve budgets, override policies, or invoke PayPal capture directly.
2. **Do not fabricate evidence or test results**: Report missing evidence explicitly; report unrun or credential-gated checks as `NOT VERIFIED`.
3. **Keep module boundaries clean**: Modules communicate through `packages/contracts` models and explicit service interfaces.
4. **Never commit secrets**: Load all keys from environment variables documented in `.env.example`.

