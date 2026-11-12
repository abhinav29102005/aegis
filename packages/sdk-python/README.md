# AEGIS Python SDK (`aegis-sdk`)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![PEP 561 Compliant](https://img.shields.io/badge/typing-PEP%20561-green.svg)](https://peps.python.org/pep-0561/)

The official Python client library and AI agent authorization middleware for **AEGIS** — *The Financial Black Box for AI Agents*.

AEGIS enforces deterministic spending governance, tamper-evident financial audit trails, forensic counterfactual replay, and automated dispute resolution across AI agent workflows.

---

## Key Features

- **Dual Sync & Async Clients**: Complete feature parity between `AegisClient` and `AsyncAegisClient` covering 100% of AEGIS OpenAPI endpoints.
- **Strict Tenant & Non-Privileged Agent Governance**: Support for granular RBAC (Owner, Operator, Auditor, Agent Service) and restricted scoped API keys.
- **AI Framework Middleware**:
  - **LangChain & LangGraph**: Native `AegisSpendingTool` (`BaseTool` compatible) preventing direct payment credential access.
  - **OpenAI Tool Calling**: Canonical function tool specification and guard execution with `OpenAIPurchaseGuard`.
- **GAP-014 Canonical Webhook Verification**: Constant-time HMAC-SHA256 signature verifier (`verify_aegis_signature`) with replay tolerance window checking.
- **Enterprise Reliability & DX**:
  - Configurable timeouts (`httpx.Timeout`).
  - Automatic exponential backoff retries on transient errors (`429`, `502`, `503`, `504` and network disconnects).
  - Sync & Async pagination iterators (`paginate`, `paginate_async`).
  - Structured error parsing for FastAPI error shapes and Pydantic validation errors (`AegisAPIError`).
  - Full typing support (`py.typed` marker).

---

## Installation

```bash
pip install aegis-sdk
```

---

## Quickstart

### 1. Synchronous Client (`AegisClient`)

```python
from aegis_sdk import AegisClient

# Initialize client with base URL and credentials
with AegisClient(base_url="https://api.aegis.nexus", api_key="ak_live_...") as client:
    # Inspect current authenticated context
    me = client.me()
    print(f"Logged in as {me['email']} (Org: {me['active_tenant_id']})")
    
    # List spending passports
    passports = client.list_passports()
    for passport in passports:
        print(f"Passport {passport['id']}: Budget ${passport['total_budget_minor'] / 100:.2f}")
```

### 2. Asynchronous Client (`AsyncAegisClient`)

```python
import asyncio
from aegis_sdk import AsyncAegisClient

async def main():
    async with AsyncAegisClient(base_url="https://api.aegis.nexus", bearer_token="ey...") as client:
        # Check overview metrics
        metrics = await client.get_overview_metrics()
        print(f"Active Agents: {metrics['agents']['active']}")
        print(f"Available Budget: ${metrics['budget']['available_minor'] / 100:.2f}")

asyncio.run(main())
```

---

## Authentication & Organization Management

AEGIS supports both user session tokens (JWT) and service account API keys:

```python
from aegis_sdk import AegisClient

client = AegisClient(base_url="http://localhost:8000")

# Register a new organization and owner
reg = client.register(
    email="admin@acme.corp",
    password="SuperSecurePassword!123",
    full_name="Alice Owner",
    organization_name="Acme Corp",
    organization_slug="acme-corp",
)
# Token is automatically bound to the client session
print(f"Access Token: {reg['access_token']}")

# Switch active tenant
client.switch_org("00000000-0000-0000-0000-000000000001")

# Invite team members with RBAC roles
client.invite_member(
    email="bob@acme.corp",
    full_name="Bob Operator",
    password="InitialPassword!123",
    role="OPERATOR",
)

# Provision restricted API key for autonomous agents
sa = client.create_service_account(name="nightly-crawler-sa", role="AGENT_SERVICE")
api_key_meta = client.issue_api_key(name="crawler-key", service_account_id=sa["id"])
agent_key = api_key_meta["plaintext_key"]
```

---

## Guardian: Deterministic Spending Governance

Guardian enforces strict budget limits, category allowlists, and human approval gates before transactions can execute.

### Register Agent, Vendor & Passport

```python
# 1. Register purchasing agent
agent = client.create_agent(
    name="Procurement-Bot-v1",
    public_fingerprint="fp-ed25519-918237192",
    framework="langgraph",
)

# 2. Register approved vendor
merchant = client.create_merchant(
    name="FastCloud Services",
    domain="fastcloud.io",
    category="CLOUD_INFRASTRUCTURE",
    is_allowlisted=True,
)

# 3. Issue spending passport with hard controls
passport = client.create_passport(
    agent_id=agent["id"],
    total_budget_minor=50000,              # $500.00 total budget
    per_tx_limit_minor=10000,              # $100.00 per-transaction limit
    daily_limit_minor=20000,               # $200.00 daily velocity limit
    human_approval_threshold_minor=5000,   # >= $50.00 triggers human review
    allowed_merchant_ids=[merchant["id"]],
    allowed_categories=["CLOUD_INFRASTRUCTURE"],
)
```

### Propose Purchase & Human Review

```python
# Agent proposes a purchase (under an AGENT_SERVICE API key)
agent_client = AegisClient(api_key=agent_key)
proposal = agent_client.submit_purchase_proposal(
    agent_id=agent["id"],
    passport_id=passport["id"],
    merchant_id=merchant["id"],
    merchant_name="FastCloud Services",
    amount_minor=7500,  # $75.00 -> Triggers human review gate
    item_summary="Kubernetes Node Expansion",
    rationale="Traffic spike handled during flash sale",
)

intent = proposal["payment_intent"]
if intent["state"] == "AWAITING_APPROVAL":
    print("Proposal held for human review.")

    # Human operator reviews and approves via the dashboard/API
    client.approve_proposal(
        intent["id"],
        approver_id="alice@acme.corp",
        comment="Approved: Traffic spike verified on Datadog.",
        approved=True,
    )
```

---

## GhostPay: Forensic Replay & Counterfactual Simulation

GhostPay provides read-only historical transaction reconstruction, policy simulations, and Agent DNA profiling.

```python
# 1. Replay transaction deterministically (verifies cryptographic hash chain)
replay = client.replay_by_payment(intent["id"])
assert replay["executed_payment"] is False  # Invariant: Replay NEVER touches payment gateways
assert replay["integrity_valid"] is True

# 2. Run counterfactual policy simulation ("What if our per-tx limit was $50?")
sim = client.simulate_by_payment(
    intent["id"],
    overrides={"per_tx_limit_minor": 5000},
)
print(f"Original Outcome: {sim['original_outcome']}")       # APPROVE
print(f"Counterfactual Outcome: {sim['recomputed_outcome']}") # DENY

# 3. Retrieve event timeline
timeline = client.get_replay_timeline(intent["id"])
for event in timeline:
    print(f"[{event['timestamp']}] {event['source_type']}: {event['summary']}")
```

---

## DisputeOS: Evidence Graph & Case Resolution

DisputeOS structures transaction evidence, checks for buyer/merchant contradictions, and compiles grounded dispute responses.

```python
# 1. Seed or create dispute case
demo_case = client.seed_demo_case()
case_id = demo_case["case"]["id"]

# 2. Attach evidence record
client.attach_evidence(
    case_id,
    source_type="DELIVERY_RECEIPT",
    source_ref="tracking://ups/1Z9999999999999999",
    title="Signed UPS Delivery Receipt",
    content={"carrier": "UPS", "signed_by": "J. Doe", "timestamp": "2026-11-10T14:30:00Z"},
)

# 3. Upload evidence document artifact
with open("invoice.pdf", "rb") as f:
    client.upload_evidence_artifact(
        case_id,
        file_content=f.read(),
        filename="invoice.pdf",
        content_type="application/pdf",
        title="Original Merchant Invoice",
    )

# 4. Run automated grounding analysis
analysis = client.run_case_analysis(case_id)
print(f"Contradiction detected: {analysis['analysis']['contradictions']}")

# 5. Generate human-reviewable report
report = client.get_case_report(case_id)
print(report["markdown_report"])
```

---

## GAP-014 Canonical Webhook Verification

AEGIS signs outbound webhook payloads using an `AEGIS-Signature` HTTP header containing a timestamp and HMAC-SHA256 signature.

```python
from aegis_sdk import verify_aegis_signature

raw_body = b'{"event":"payment.captured","amount_minor":2500}'
signature_header = "AEGIS-Signature: t=1700000000,v1=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
signing_secret = "whsec_..."

is_valid = verify_aegis_signature(
    raw_body=raw_body,
    signature_header=signature_header,
    secret=signing_secret,
    tolerance_seconds=300,  # Rejects replays older than 5 minutes
)

if not is_valid:
    raise ValueError("Invalid or expired AEGIS webhook signature")
```

---

## Agent Framework Middleware Helpers

### LangChain / LangGraph Integration

```python
from aegis_sdk import AegisClient
from aegis_sdk.integrations import create_aegis_spending_tool

# Initialize with restricted AGENT_SERVICE credentials
agent_client = AegisClient(api_key="ak_agent_...")

# Create LangChain compatible tool
spending_tool = create_aegis_spending_tool(
    client=agent_client,
    agent_id="00000000-0000-0000-0000-000000000001",
    passport_id="00000000-0000-0000-0000-000000000002",
)

# Register with agent / LangGraph tool nodes
tools = [spending_tool]
```

### OpenAI Function Calling Guard

```python
from aegis_sdk import AegisClient
from aegis_sdk.integrations import OpenAIPurchaseGuard

client = AegisClient(api_key="ak_agent_...")
guard = OpenAIPurchaseGuard(
    client=client,
    agent_id="00000000-0000-0000-0000-000000000001",
    passport_id="00000000-0000-0000-0000-000000000002",
)

# Provide tool spec to OpenAI chat completion
tools = [guard.tool_spec]

# When model triggers tool call:
result = guard.execute(tool_call.function.arguments)
print(f"Payment State: {result['payment_intent']['state']}")
```

---

## Reliability & Pagination

### Automatic Retry & Timeout Configuration

```python
import httpx
from aegis_sdk import AegisClient

# Configurable timeout and backoff retries
client = AegisClient(
    timeout=httpx.Timeout(30.0, connect=10.0),
    max_retries=4,
    backoff_factor=0.25,
)
```

### Seamless Pagination

Endpoints supporting `limit` and `offset` can be traversed using the `paginate` generator:

```python
from aegis_sdk import AegisClient, paginate

client = AegisClient(...)

# Automatically fetches and yields individual events page-by-page
for event in paginate(lambda limit, offset: client.list_audit_events(limit=limit, offset=offset), limit=100):
    print(f"Event: {event['event_type']} - {event['id']}")
```

---

## License

Apache-2.0
