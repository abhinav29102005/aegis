# Contributing to AgentPay Nexus

Thank you for contributing to **AgentPay Nexus — The Financial Digital Twin for Agentic Commerce**.

## Development Workflow

1. Shared contracts live in `packages/contracts/` and are frozen across feature branches unless coordinated through the integration branch (`integration/nexus`).
2. Module isolation:
   - `modules/agentpay-guardian/` (`feature/guardian`)
   - `modules/ghostpay/` (`feature/ghostpay`)
   - `modules/disputeos/` (`feature/disputeos`)
3. Never commit secrets, `.env` files, or real PayPal credentials.
4. All financial state changes must preserve tenant isolation, deterministic policy evaluation, and append-only event integrity.
5. Run all backend tests (`uv run pytest`) and frontend checks (`npm run lint && npm run typecheck`) before opening a pull request.
