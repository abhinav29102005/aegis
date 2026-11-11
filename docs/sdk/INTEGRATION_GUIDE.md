# AEGIS Developer & SDK Integration Guide

AEGIS exposes typed Python (`aegis-sdk`) and TypeScript (`@aegis-platform/sdk`) clients backed by the versioned FastAPI control plane (`/v1/*`).

---

## 1. Quickstart with Python SDK (`aegis-sdk`)

```python
from aegis_sdk import AegisClient, verify_webhook_signature

client = AegisClient(base_url="http://localhost:8000")

# 1. Authenticate as an organization owner / admin (or pass api_key="aegis_dev_...")
session = client.login(email="owner@acme.test", password="StrongPassword123!")

# 2. Register agent, allowlisted merchant, and Spending Passport
agent = client.create_agent(
    name="cloud-procurement-bot",
    purpose="Provision GPU and compute credits",
    framework="langgraph",
)
merchant = client.create_merchant(
    name="Acme Compute Cloud",
    domain="compute.acme.example",
    category="CLOUD_COMPUTE",
    is_allowlisted=True,
    is_sandbox_verified=True,
)
passport = client.create_passport(
    agent_id=agent["id"],
    total_budget_minor=50_000,            # $500.00
    per_tx_limit_minor=15_000,            # $150.00
    daily_limit_minor=30_000,             # $300.00
    human_approval_threshold_minor=10_000,# $100.00 escalation threshold
    allowed_merchant_ids=[merchant["id"]],
    allowed_categories=["CLOUD_COMPUTE"],
    allow_unknown_merchants=False,
)

# 3. Issue a scoped AGENT_RUNTIME API key for autonomous workers
issued = client.issue_api_key(name="runtime-worker", role="AGENT_RUNTIME")
agent_client = AegisClient(base_url="http://localhost:8000", api_key=issued["plaintext_key"])

# 4. Submit an idempotent spend proposal
res = agent_client.submit_proposal(
    agent_id=agent["id"],
    passport_id=passport["id"],
    merchant_id=merchant["id"],
    merchant_name=merchant["name"],
    merchant_category="CLOUD_COMPUTE",
    amount_minor=4_500,                   # $45.00 -> ALLOW -> CHECKOUT_READY
    currency="USD",
    item_summary="GPU Compute Hours",
    rationale="Batch training run",
    idempotency_key="proposal-run-2026-001",
)
intent_id = res["payment_intent"]["id"]

# 5. Inspect read-only forensic replay in GhostPay (executed_payment=False)
replay = client.replay_payment(intent_id)
assert replay["executed_payment"] is False
assert replay["consistency_status"] == "CONSISTENT"
```

---

## 2. Quickstart with TypeScript SDK (`@aegis-platform/sdk`)

```ts
import { AegisClient, verifyWebhookSignature } from "@aegis-platform/sdk";

const client = new AegisClient({
  baseUrl: "http://localhost:8000",
  apiKey: process.env.AEGIS_API_KEY,
  orgId: process.env.AEGIS_ORG_ID,
});

const proposal = await client.submitProposal({
  agent_id: agentId,
  passport_id: passportId,
  merchant_id: merchantId,
  merchant_name: "Acme Compute Cloud",
  merchant_category: "CLOUD_COMPUTE",
  amount_minor: 4500,
  currency: "USD",
  item_summary: "GPU Compute Hours",
  line_items: [{ sku: "GPU-1", description: "Compute", quantity: 1, unit_price_minor: 4500 }],
  rationale: "Scheduled batch inference",
  idempotency_key: "ts-proposal-001",
});

const replay = await client.replayPayment(proposal.payment_intent.id);
const simulation = await client.simulatePayment(proposal.payment_intent.id, {
  per_tx_limit_minor: 2000,
});
```

---

## 3. Verifying Signed Outbound Webhooks

Every outbound webhook emitted by `services/worker` includes the `AEGIS-Signature` header formatted as `t=<unix_seconds>,v1=<hex_hmac_sha256>` computed over `f"{timestamp}.{raw_body}"`.

- **Python**:
  ```python
  ok = verify_webhook_signature(
      secret=os.environ["AEGIS_WEBHOOK_SECRET"],
      payload=raw_request_bytes,
      signature_header=request.headers["AEGIS-Signature"],
      max_age_seconds=300,
  )
  ```
- **TypeScript / Node.js**:
  ```ts
  const valid = verifyWebhookSignature(
    process.env.AEGIS_WEBHOOK_SECRET!,
    rawRequestBody,
    req.headers["aegis-signature"],
    300,
  );
  ```

---

## 4. LangGraph / Tool Integration Pattern

When wrapping AEGIS inside an AI agent tool:
1. Supply an `AGENT_RUNTIME` API key (`proposals:write`, `payments:read`) — never grant `FINANCE_ADMIN` or `approvals:decide` permissions to an agent runtime key.
2. Always generate a deterministic `idempotency_key` per purchase step so retries do not create duplicate proposals.
3. Inspect `decision.outcome`:
   - `ALLOW`: Intent enters `CHECKOUT_READY`.
   - `ESCALATE`: Intent enters `AWAITING_APPROVAL`; agent pauses until a human approves in the AEGIS Console (`POST /v1/guardian/proposals/{id}/approve`).
   - `DENY`: Intent enters `REJECTED`; return policy `reason_codes` to the caller without retry loops.
