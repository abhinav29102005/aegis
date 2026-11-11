# Open-Source Repository Research & Reuse Matrix

This document records the licensing, technical inspection, isolated test execution, and reuse decisions for all external repositories and official specifications researched prior to implementing AgentPay Nexus.

All temporary research clones were placed strictly outside tracked source directories (`/tmp/agentpay-research/`). No third-party code was copied from repositories lacking a clear permissive license.

---

## Summary Reuse Matrix

| Repository / Source | Availability | License | Stack | Isolated Test Result | Reuse Decision | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `google-agentic-commerce/AP2` | Available (cloned) | **Apache-2.0** | Python (`pydantic`, `cryptography`, `jwcrypto`, `sd-jwt`), Go | **186 passed, 2 failed** (`pytest code/sdk/python/ap2/tests` in `/tmp/ap2-venv`) | **Study & Align Protocol Semantics** (no verbatim copy needed) | Clean Pydantic mandate/cart/receipt concepts (`CheckoutMandate`, `PaymentMandate`, `PaymentReceipt`). Two intermediate KB-SD-JWT negative tests (`test_verify_rejects_aud_mismatch`, `test_verify_rejects_nonce_mismatch`) failed in upstream HEAD; we implement clean Nexus-native Pydantic contracts inspired by AP2 separation of Intent/Cart/Payment mandates without pulling unstable SD-JWT internals. |
| `prayagupa/payment-system` | Available (cloned) | **None** (no LICENSE file) | Python (`fastapi`, `sqlalchemy`, `psycopg`, `httpx`, `pydantic`) | **Not executed** (no license; would require installing service deps) | **Study Only — DO NOT COPY** | Absence of a LICENSE file prohibits copying or adapting source code. Studied architectural pattern: deterministic governance kernel (`allow / deny / escalate / transform`) sitting in front of service APIs so agents never hold DB credentials, and append-only JSONL/DB audit sinks. |
| `manishgh/agentic-payments` | Available (cloned) | **None** (no LICENSE file; README states *"Public licensing and package distribution are undecided"*) | Java 21, Python (`langgraph`, `temporalio`), TypeScript, PostgreSQL | **Not executed** (requires Java 21 + Temporal + Postgres + unclear license) | **Study Only — DO NOT COPY** | Explicit undecided licensing prohibits code reuse. Studied durable payment state machine ADRs: authority binding (immutable quote/merchant snapshot bound at approval), recoverable `PENDING_PROVIDER` states, and worker transaction ownership. |
| `sentient-agi/agentic-payments-bot` | Available (cloned) | **Apache-2.0** (`LICENSE-APACHE`) | TypeScript, Express, SQLite, `@paypal/paypal-server-sdk`, `viem` | **0 test files** in repository | **Study Only** | Targets Node/Express + Web3 (x402/EIP-3009) + SQLite, whereas AgentPay Nexus uses Python/FastAPI + PostgreSQL + Next.js. No tests exist to validate runtime correctness. |
| `fexx301/witness` | Available (cloned) | **MIT** | TypeScript, Node 22, `@anthropic-ai/sdk`, `@paypal/agent-toolkit`, `zod`, `vitest` | `npm run typecheck` **passed**; `npm test` **failed** (`ERR_MODULE_NOT_FOUND: Cannot find package 'vite'` under `vitest@^5.0.3`) | **Study Patterns (MIT)** — clean-room Python port of concepts | Valuable domain separation for agentic dispute investigation: distinguishing (1) did buyer authorize agent, (2) did agent follow instruction/policy, (3) did merchant deliver as ordered, plus deterministic citation verification. Reimplemented cleanly in Python for DisputeOS rather than mixing Node runtime into backend modules. |
| `dulch29/dispute-copilot` | Available (cloned) | **MIT** | Next.js 16, React 19, TypeScript, SQLite (`better-sqlite3`), `zod`, `vitest` | **Not executed** (Next.js/SQLite native deps; inspected source & tests) | **Study Patterns (MIT)** — clean-room Python port of concepts | Valuable deterministic adjudication patterns: strict evidence-quote validation, deterministic `FIGHT / ACCEPT / NEED_INFO` checklists, counterfactual fact dismissal, and SHA-256 payload hashing with single-use human approval gates. Reimplemented cleanly in Python/PostgreSQL for DisputeOS. |

---

## Detailed Inspection Notes

### 1. `google-agentic-commerce/AP2` (Apache-2.0)
- **Source Tree**: `code/sdk/python/ap2/{models,sdk}`, `code/sdk/python/ap2/tests/` (17 test files), `docs/`.
- **Dependencies**: `cryptography==46.0.5`, `jwcrypto==1.5.6`, `pydantic==2.12.5`, `sd-jwt==0.10.4`, `pytest==9.0.2`.
- **Isolated Test Run**:
  - Created `/tmp/ap2-venv` with Python 3.12 via `uv`.
  - Ran `pytest code/sdk/python/ap2/tests -q`: **186 passed, 2 failed** (`kb_sd_jwt_intermediate_tests.py::test_verify_rejects_aud_mismatch` and `test_verify_rejects_nonce_mismatch` did not raise `ValueError`).
- **Architectural Takeaway**:
  - Distinct separation between user intent/constraints, merchant cart/quote snapshot, payment mandate, and receipt. Reflected in AgentPay Nexus `PurchaseProposal`, `QuoteSnapshot`, `AuthorizationDecision`, `ApprovalRecord`, and `PaymentAttempt`.

### 2. `prayagupa/payment-system` (No License)
- **Source Tree**: `agent_lifecycle_platform/` (kernel, policy, audit, auth), `services/{account,wallet,transfer}`, `audit_service/`, `tests/` (9 pytest files).
- **Dependencies**: `fastapi>=0.115`, `sqlalchemy>=2`, `psycopg[binary]>=3`, `httpx>=0.27`, `pydantic>=2`.
- **Limitations**: No `LICENSE` file; multi-service + Kubernetes layout exceeds hackathon scope.
- **Decision**: Zero code copied. Inspired our strict rule that LangGraph agents only invoke governed tools and never touch database connections or PayPal capture credentials directly.

### 3. `manishgh/agentic-payments` (No License — Undecided)
- **Source Tree**: `docs/adr/0001..0023`, `workflows/` (LangGraph + Temporal), `integrations/`, `specification/`, `ui/`.
- **Dependencies**: `langgraph==1.2.20`, `langgraph-checkpoint-sqlite==3.1.3`, `temporalio==1.35.0`, Java 21 (`pom.xml`).
- **Limitations**: Explicitly states *"Public licensing and package distribution are undecided"* and *"Conformance reports remain NOT_CERTIFIED"*. Heavy Temporal/Java 21 runtime unnecessary for Nexus.
- **Decision**: Zero code copied. Studied ADRs 0010–0018 on payment transaction boundaries, authority binding (binding approval hash to merchant + amount), and `PENDING_PROVIDER` recovery.

### 4. `sentient-agi/agentic-payments-bot` (Apache-2.0)
- **Source Tree**: `src/` (Express API, CLI, KMS providers, SQLite db), `SKILL.md`.
- **Dependencies**: TypeScript, Express 5, `better-sqlite3`, `@paypal/paypal-server-sdk`, `viem`, `stripe`.
- **Limitations**: Zero automated tests (`0` test files); heavily oriented toward crypto x402/EIP-3009 signing and local SQLite.
- **Decision**: Not reused. Nexus uses official PayPal Orders v2 REST API directly over `httpx` in `packages/paypal/` with PostgreSQL transactional outbox.

### 5. `fexx301/witness` (MIT)
- **Source Tree**: `src/` (`witness.ts`, `decide.ts`, `findings.ts`, `mandate.ts`, `paypal/`), `test/` (`witness.test.ts`, `docs.test.ts`), `eval/`.
- **Isolated Check**: `npm install` + `npm run typecheck` succeeded (`tsc --noEmit` exited 0); `npm test` failed because `vitest@^5.0.3` could not resolve `vite`.
- **Decision**: MIT-licensed design patterns studied for DisputeOS: 3-question agentic dispute taxonomy (authorization vs. instruction adherence vs. merchant fulfillment) and strict evidence-ID citation checking.

### 6. `dulch29/dispute-copilot` (MIT)
- **Source Tree**: `src/lib/{domain,ai,paypal,db}`, `tests/` (5 Vitest specs + 2 scripts), `evals/cases/`.
- **Limitations**: Next.js-coupled SQLite server codebase; we implement DisputeOS in Python so it shares canonical Pydantic contracts and PostgreSQL models with Guardian and GhostPay.
- **Decision**: MIT-licensed design patterns studied for DisputeOS: deterministic checklist evaluation, contradiction detection, counterfactual fact toggling, and SHA-256 human approval gate (`PAYPAL_DISPUTES_API_ENABLED` feature-flagged).

---

## Official PayPal Documentation References

- **PayPal Orders API v2**: `https://developer.paypal.com/docs/api/orders/v2/`
  - Server-side OAuth2 client credentials (`POST /v1/oauth2/token`).
  - Server-side order creation (`POST /v2/checkout/orders` with `intent: "CAPTURE"` and `PayPal-Request-Id` idempotency header).
  - Server-side order verification & capture (`GET /v2/checkout/orders/{id}`, `POST /v2/checkout/orders/{id}/capture`).
  - Never trust client-side JS SDK callbacks alone; always verify capture status (`COMPLETED`) server-side before transitioning to `SUCCEEDED`.
- **PayPal JavaScript SDK Checkout**: `https://developer.paypal.com/docs/checkout/`
  - Buyer approval runs in browser using public `NEXT_PUBLIC_PAYPAL_CLIENT_ID` only; server creates order and captures order.
- **PayPal Customer Disputes API v1**: `https://developer.paypal.com/docs/api/customer-disputes/v1/`
  - Feature-flagged (`PAYPAL_DISPUTES_API_ENABLED=false` by default) because sandbox accounts require explicit Disputes scope/permissions and synthetic disputes cannot be submitted to PayPal.
- **PayPal Webhook Signature Verification**: `POST /v1/notifications/verify-webhook-signature`
  - Verified server-side using `PAYPAL_WEBHOOK_ID` and incoming `PAYPAL-TRANSMISSION-*` headers.
