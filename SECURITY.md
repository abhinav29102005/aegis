# Security Policy

## Reporting a Vulnerability

Please report security issues privately to the maintainers rather than opening a public issue containing exploit details.

## Non-Negotiable Security Invariants

1. **Deterministic Authorization Only**: AI/LLM agents may propose purchases and explain outcomes, but may never authorize spend, reserve budget, or execute captures directly.
2. **PayPal Isolation**: `packages/paypal/` is isolated from LangGraph and LLM modules. PayPal `CLIENT_SECRET` must only reside in server environment variables and never in `NEXT_PUBLIC_*` variables or browser bundles.
3. **Verified Settlement**: A payment intent transitions to `SUCCEEDED` only after server-side PayPal capture verification (`status == COMPLETED` and matching currency/amount).
4. **Timeout Safety**: PayPal timeouts transition intents to `PENDING_PROVIDER` until reconciled via `GET /v2/checkout/orders/{id}` or verified webhooks.
5. **Tenant Isolation**: Every financial record, replay request, evidence item, and dispute case is scoped by `tenant_id` and fails closed on mismatch.
6. **Human-in-the-Loop Disputes**: DisputeOS drafts grounded reports and requires explicit human approval before any external submission. `PAYPAL_DISPUTES_API_ENABLED` defaults to `false`.

