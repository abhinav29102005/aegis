# AEGIS TypeScript SDK (`@aegis-platform/sdk`)

Official TypeScript & Edge-compatible SDK for **AEGIS (AgentPay Nexus)**: The Financial Black Box for AI Agents.

Provides deterministic spending governance (Guardian), counterfactual policy simulations and forensic replay (GhostPay), evidence provenance and dispute management (DisputeOS), and edge-ready webhook signature verification.

---

## Features

- **🛡️ Agent Spending Governance (Guardian):** Submit purchase proposals, evaluate deterministic spending passports, gate with human approval, and trigger PayPal sandboxed checkouts.
- **⏱️ Forensic Replay & Counterfactual Simulation (GhostPay):** Reconstruct cryptographic financial timelines, test "what-if" policy changes without side-effects, and detect Agent DNA drift.
- **⚖️ Dispute Investigation (DisputeOS):** Ingest evidence graphs, contradiction detection, grounded AI summaries, and human-approved dispute resolution.
- **🔐 Universal Webhook Verification (GAP-014):** Canonical `AEGIS-Signature: t=<unix>,v1=<hmac>` verification supporting both **Node.js** and **WebCrypto** (`globalThis.crypto.subtle`) for Edge runtimes (Cloudflare Workers, Next.js Edge Middleware, Vercel Edge).
- **🤖 Vercel AI SDK Middleware:** Pre-execution tool wrapper that intercepts agent purchase calls to enforce spending policies and approval gates deterministically.
- **⚡ Resilient HTTP Client:** Configurable AbortController timeouts, automatic exponential-backoff retries on transient 5xx/network errors, and pagination async iterators.
- **🚨 Robust Error Extraction (GAP-015):** Parses FastAPI `detail` strings, Pydantic validation error arrays (`[{ loc, msg, type }]`), and domain error envelopes into structured `AegisAPIError`s.

---

## Installation

```bash
npm install @aegis-platform/sdk
```

*(Requires Node.js >= 20 or any runtime with WebCrypto support)*

---

## Quickstart

### 1. Initialize Client

```typescript
import { AegisClient } from "@aegis-platform/sdk";

// Using an API Key (recommended for server-to-server and agent runtimes)
const client = new AegisClient({
  baseUrl: process.env.AEGIS_BASE_URL ?? "http://localhost:8000",
  apiKey: process.env.AEGIS_API_KEY,
  organizationId: process.env.AEGIS_ORG_ID,
  timeoutMs: 15000, // 15s request timeout
  maxRetries: 3,    // Auto-retry transient 500/502/503/504 errors
});
```

---

### 2. Submit a Purchase Proposal (Guardian)

```typescript
const proposal = await client.submitPurchaseProposal({
  agent_id: "7b4c9102-1234-4567-89ab-cdef01234567",
  passport_id: "8c5d0213-2345-5678-90bc-def012345678",
  merchant_id: "9d6e1324-3456-6789-01cd-ef0123456789",
  merchant_name: "OpenAI API Platform",
  merchant_category: "SOFTWARE",
  amount_minor: 4500, // $45.00
  currency: "USD",
  item_summary: "Tier 4 API Credit Top-Up",
  rationale: "Autonomous query batch processing for user research",
});

if (proposal.decision.outcome === "ALLOW") {
  console.log("Proposal ALLOWED. Payment intent ready:", proposal.payment_intent.id);
  // Initiate checkout
  const checkout = await client.initiateCheckout(proposal.payment_intent.id);
  console.log("Approval URL:", checkout.approval_url);
} else if (proposal.decision.outcome === "ESCALATE") {
  console.log("Proposal ESCALATED for human approval:", proposal.decision.explanation);
} else {
  console.error("Proposal DENIED:", proposal.decision.reason_codes);
}
```

---

### 3. Human Approval Gate

```typescript
// Approve proposal in AEGIS Console or via authorized operator
const approved = await client.approveProposal("pi-uuid-1234", {
  approver_id: "compliance@company.com",
  approved: true,
  comment: "Approved against Q4 LLM infrastructure budget",
});

console.log("Updated intent state:", approved.payment_intent.state); // CHECKOUT_READY
```

---

### 4. Vercel AI SDK Integration Middleware

Wrap any purchasing tool before model execution to govern spending deterministically:

```typescript
import { wrapAegisPurchasingTool } from "@aegis-platform/sdk/integrations/vercel-ai";
// or: import { wrapAegisPurchasingTool } from "@aegis-platform/sdk";

export const purchaseCreditsTool = wrapAegisPurchasingTool({
  client,
  agentId: "agent-uuid",
  passportId: "passport-uuid",
  approvalMode: "poll", // 'throw' | 'poll' | 'return_status'
  pollTimeoutMs: 60000,
  execute: async (args: { amount_minor: number; service: string }, context) => {
    // This code only runs if AEGIS policy outcome is ALLOW (or approved by a human)!
    console.log("Executing purchase under intent:", context.paymentIntent.id);
    return { orderId: "ord-987", status: "SUCCESS" };
  },
});
```

---

### 5. Universal Webhook Signature Verification (GAP-014)

Verify outbound webhooks emitted by AEGIS. Works identically in **Node.js**, **Next.js Edge Middleware**, and **Cloudflare Workers**:

#### Next.js Route Handler / Edge Middleware:
```typescript
import { verifyAegisSignature } from "@aegis-platform/sdk";

export async function POST(req: Request) {
  const rawBody = await req.text();
  const signatureHeader = req.headers.get("AEGIS-Signature") ?? "";
  const secret = process.env.AEGIS_WEBHOOK_SECRET!;

  // Enforces 300s clock drift tolerance and constant-time HMAC-SHA256 comparison
  const isValid = await verifyAegisSignature(rawBody, signatureHeader, secret, 300);

  if (!isValid) {
    return new Response("Invalid signature or expired replay window", { status: 401 });
  }

  const payload = JSON.parse(rawBody);
  console.log("Received event:", payload.event_type);
  return new Response("OK", { status: 200 });
}
```

#### Node.js / Express (Sync):
```typescript
import { verifyAegisSignatureSync } from "@aegis-platform/sdk";

app.post("/webhooks/aegis", express.raw({ type: "application/json" }), (req, res) => {
  const isValid = verifyAegisSignatureSync(
    req.body,
    req.headers["aegis-signature"] as string,
    process.env.AEGIS_WEBHOOK_SECRET!
  );

  if (!isValid) return res.status(401).send("Unauthorized");
  res.sendStatus(200);
});
```

---

### 6. GhostPay Counterfactual Simulation & Replay

Simulate what would happen if spending limits were different, without modifying historical data:

```typescript
const simResult = await client.simulateByPayment(
  "intent-uuid-123",
  {
    per_tx_limit_minor: 2500, // tighten limit from $50.00 to $25.00
  },
  true, // persist as an investigation
  "policy-v1"
);

console.log("Original outcome:", simResult.original_outcome);     // ALLOW
console.log("Recomputed outcome:", simResult.recomputed_outcome); // DENY
console.log("Policy drift detected:", simResult.drift_detected);   // true
```

---

### 7. Pagination with Async Iterators

Effortlessly iterate across payments, audit events, and outbox DLQ items:

```typescript
for await (const payment of client.listPaymentsIterator({ state: "SUCCEEDED", maxItems: 100 })) {
  console.log(`Payment ${payment.id}: $${payment.amount_minor / 100} (${payment.currency})`);
}
```

---

### 8. Structured Error Handling (GAP-015)

```typescript
import { AegisAPIError, AegisPolicyViolationError, AegisApprovalRequiredError } from "@aegis-platform/sdk";

try {
  await client.submitPurchaseProposal(input);
} catch (err) {
  if (err instanceof AegisAPIError) {
    console.error(`HTTP ${err.statusCode}: ${err.message}`);
    console.error("Error Code:", err.errorCode);
    console.error("Pydantic Validation Errors:", err.validationErrors);
  } else if (err instanceof AegisPolicyViolationError) {
    console.warn("Policy Denied:", err.reasonCodes, err.violatedConstraints);
  } else if (err instanceof AegisApprovalRequiredError) {
    console.info("Needs Human Approval for intent:", err.intentId);
  }
}
```

---

## Canonical Types & Enums

All TypeScript definitions match canonical backend contracts:

- **Roles (6):** `Role` (`OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`)
- **Payment States (10+):** `PaymentState` (`CREATED`, `POLICY_CHECK`, `AWAITING_APPROVAL`, `CHECKOUT_READY`, `AWAITING_PAYPAL_BUYER`, `CAPTURE_PENDING`, `SUCCEEDED`, `FAILED`, `PENDING_PROVIDER`, `CANCELLED`)
- **Decision Outcomes:** `DecisionOutcome` (`ALLOW`, `DENY`, `ESCALATE`)
- **Passport Statuses:** `PassportStatus` (`ACTIVE`, `PAUSED`, `REVOKED`, `EXPIRED`)
- **Dispute Recommendations:** `DisputeRecommendation` (`CHALLENGE_WITH_EVIDENCE`, `OFFER_PARTIAL_OR_RETURN`, `ACCEPT_AND_REFUND`, `NEED_MORE_EVIDENCE`)

---

## Testing

```bash
npm test
```

Runs the Vitest suite (client methods, error parsing, retries, WebCrypto & Node crypto signature verification) and Node native tests.

---

## License

Apache-2.0
