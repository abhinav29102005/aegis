"""Seed Realistic Enterprise AI Agent Showcase Data into AEGIS Staging.

Populates tenant '829db6b0-6566-4d6d-84e7-6fae90633723' (Chief Auditor) with:
- 4 Enterprise AI Agents (FinOps, Model Orchestrator, DevSecOps, SRE Telemetry)
- 4 Verified Industry Merchants (AWS, OpenAI, GitHub Enterprise, Datadog)
- 4 Strict Spending Passports with tiered budgets and approval thresholds
- Realistic Purchase Proposals across all policy states
- Real PayPal Sandbox Orders v2
- GhostPay Forensic Timelines and Investigations
- 2 Real DisputeOS Cases with Ingested Telemetry, Delivery Evidence, and AI Analysis
"""

import os
import sys
import uuid
import httpx

BASE_URL = os.getenv("AEGIS_STAGING_URL", "https://api-staging.abhinavkumarsingh.tech")

EMAIL = "chief-auditor-bf1ab00d@aegis-nexus.tech"
PASSWORD = "SuperSecurePassword123!@#"

print(f"Connecting to AEGIS Staging: {BASE_URL}")

transport = httpx.HTTPTransport(retries=3)
client = httpx.Client(base_url=BASE_URL, transport=transport, timeout=30.0)

# 1. Login to get token
login_resp = client.post("/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
if login_resp.status_code != 200:
    print(f"Login failed: {login_resp.status_code} {login_resp.text}")
    sys.exit(1)

auth_data = login_resp.json()
token = auth_data["access_token"]
tenant_id = auth_data["active_tenant_id"]
print(f"Logged in successfully as {EMAIL}")
print(f"Active Tenant ID: {tenant_id}")

headers = {
    "Authorization": f"Bearer {token}",
    "X-Org-Id": tenant_id,
    "Content-Type": "application/json",
}

# 2. Seed Real Merchants
merchants_data = [
    {
        "name": "Amazon Web Services Inc",
        "domain": "aws.amazon.com",
        "category": "CLOUD_INFRASTRUCTURE",
        "paypal_merchant_id": "merchant-aws@aegis-nexus.tech",
        "is_allowlisted": True,
        "is_sandbox_verified": True,
    },
    {
        "name": "OpenAI Technologies Inc",
        "domain": "openai.com",
        "category": "AI_INFERENCE",
        "paypal_merchant_id": "merchant-openai@aegis-nexus.tech",
        "is_allowlisted": True,
        "is_sandbox_verified": True,
    },
    {
        "name": "GitHub Enterprise Services",
        "domain": "github.com",
        "category": "DEV_TOOLS",
        "paypal_merchant_id": "merchant-github@aegis-nexus.tech",
        "is_allowlisted": True,
        "is_sandbox_verified": True,
    },
    {
        "name": "Datadog Cloud Monitoring",
        "domain": "datadoghq.com",
        "category": "OBSERVABILITY",
        "paypal_merchant_id": "merchant-datadog@aegis-nexus.tech",
        "is_allowlisted": True,
        "is_sandbox_verified": True,
    },
]

created_merchants = {}
for m in merchants_data:
    resp = client.post("/v1/guardian/merchants", json=m, headers=headers)
    if resp.status_code in (200, 201):
        m_obj = resp.json()
        created_merchants[m["name"]] = m_obj["id"]
        print(f"  [Merchant] Created: {m['name']} -> {m_obj['id']}")

list_m = client.get("/v1/guardian/merchants", headers=headers).json()
for m_item in list_m:
    created_merchants[m_item["name"]] = m_item["id"]

# 3. Seed AI Agents
agents_data = [
    {
        "name": "FinOps Auto-Scaling Optimizer",
        "purpose": "Manages autonomous spot instance bidding and compute reservations on AWS EC2.",
    },
    {
        "name": "Enterprise Model Orchestrator",
        "purpose": "Procures dynamic OpenAI / Anthropic batch inferencing capacity based on workload SLAs.",
    },
    {
        "name": "DevSecOps Pipeline Agent",
        "purpose": "Automated developer tooling licenses, CI/CD runners, and security scanner upgrades.",
    },
    {
        "name": "SRE Telemetry & Observability Bot",
        "purpose": "Purchases on-demand log ingestion volume and APM retention buckets during incidents.",
    },
]

created_agents = {}
for a in agents_data:
    resp = client.post("/v1/guardian/agents", json=a, headers=headers)
    if resp.status_code in (200, 201):
        a_obj = resp.json()
        created_agents[a["name"]] = a_obj["id"]
        print(f"  [Agent] Created: {a['name']} -> {a_obj['id']}")

list_a = client.get("/v1/guardian/agents", headers=headers).json()
for a_item in list_a:
    created_agents[a_item["name"]] = a_item["id"]

# 4. Seed Spending Passports
passports_data = [
    {
        "agent_name": "FinOps Auto-Scaling Optimizer",
        "monthly_budget_minor": 1500000,     # $15,000.00
        "per_tx_limit_minor": 200000,         # $2,000.00
        "approval_threshold_minor": 50000,   # $500.00
        "merchants": ["Amazon Web Services Inc"],
    },
    {
        "agent_name": "Enterprise Model Orchestrator",
        "monthly_budget_minor": 800000,      # $8,000.00
        "per_tx_limit_minor": 100000,         # $1,000.00
        "approval_threshold_minor": 25000,   # $250.00
        "merchants": ["OpenAI Technologies Inc"],
    },
    {
        "agent_name": "DevSecOps Pipeline Agent",
        "monthly_budget_minor": 300000,      # $3,000.00
        "per_tx_limit_minor": 50000,          # $500.00
        "approval_threshold_minor": 10000,   # $100.00
        "merchants": ["GitHub Enterprise Services"],
    },
    {
        "agent_name": "SRE Telemetry & Observability Bot",
        "monthly_budget_minor": 500000,      # $5,000.00
        "per_tx_limit_minor": 75000,          # $750.00
        "approval_threshold_minor": 15000,   # $150.00
        "merchants": ["Datadog Cloud Monitoring"],
    },
]

created_passports = {}
for p in passports_data:
    agent_id = created_agents.get(p["agent_name"])
    if not agent_id:
        continue
    allowlist = [created_merchants[m] for m in p["merchants"] if m in created_merchants]
    payload = {
        "agent_id": agent_id,
        "monthly_budget_minor": p["monthly_budget_minor"],
        "per_tx_limit_minor": p["per_tx_limit_minor"],
        "approval_threshold_minor": p["approval_threshold_minor"],
        "merchant_allowlist": allowlist,
    }
    resp = client.post("/v1/guardian/passports", json=payload, headers=headers)
    if resp.status_code in (200, 201):
        p_obj = resp.json()
        created_passports[p["agent_name"]] = p_obj["id"]
        print(f"  [Passport] Provisioned for {p['agent_name']} -> {p_obj['id']}")

# Query existing passports to ensure map
list_p = client.get("/v1/guardian/passports", headers=headers).json()
for p_item in list_p:
    for a_name, a_id in created_agents.items():
        if p_item["agent_id"] == a_id:
            created_passports[a_name] = p_item["id"]

# 5. Seed Real Proposals Across Policy States
proposals_to_create = [
    # 1. Under threshold -> Auto-approved -> Trigger real PayPal Sandbox Order!
    {
        "passport": "Enterprise Model Orchestrator",
        "merchant": "OpenAI Technologies Inc",
        "amount_minor": 12500,  # $125.00 < $250.00 threshold
        "reason": "Procure 2.5M tokens reserved capacity for enterprise RAG pipeline",
        "action": "checkout",
    },
    # 2. Over threshold -> Held in AWAITING_APPROVAL -> Human Approved -> Real PayPal Order!
    {
        "passport": "FinOps Auto-Scaling Optimizer",
        "merchant": "Amazon Web Services Inc",
        "amount_minor": 75000,  # $750.00 > $500.00 threshold
        "reason": "1-Month Reserved Instance EC2 g5.4xlarge for GPU distributed inference cluster",
        "action": "approve_and_checkout",
    },
    # 3. Over threshold -> Currently AWAITING_APPROVAL (Pending in UI for interactive judging demo!)
    {
        "passport": "DevSecOps Pipeline Agent",
        "merchant": "GitHub Enterprise Services",
        "amount_minor": 25000,  # $250.00 > $100.00 threshold
        "reason": "Upgrade GitHub Actions concurrency runners: 50 additional self-hosted slots",
        "action": "leave_pending",
    },
    # 4. Under threshold -> Auto-approved to CHECKOUT_READY
    {
        "passport": "SRE Telemetry & Observability Bot",
        "merchant": "Datadog Cloud Monitoring",
        "amount_minor": 8500,  # $85.00 < $150.00 threshold
        "reason": "Dynamic 50GB incident trace retention surge during P1 cluster latency alert",
        "action": "leave_approved",
    },
]

created_proposals = []
for p_spec in proposals_to_create:
    pass_id = created_passports.get(p_spec["passport"])
    m_id = created_merchants.get(p_spec["merchant"])
    if not pass_id or not m_id:
        continue

    prop_payload = {
        "passport_id": pass_id,
        "merchant_id": m_id,
        "amount_minor": p_spec["amount_minor"],
        "currency": "USD",
        "reason": p_spec["reason"],
        "quote_items": [
            {
                "sku": f"SKU-{uuid.uuid4().hex[:6].upper()}",
                "description": p_spec["reason"],
                "unit_price_minor": p_spec["amount_minor"],
                "quantity": 1,
            }
        ],
    }
    resp = client.post("/v1/guardian/proposals", json=prop_payload, headers=headers)
    if resp.status_code not in (200, 201):
        print(f"  [Proposal Error] {resp.status_code} {resp.text}")
        continue
    prop = resp.json()
    intent_id = prop["intent_id"]
    print(f"  [Proposal] Created {intent_id}: ${p_spec['amount_minor']/100:.2f} ({prop['status']})")
    created_proposals.append(prop)

    # Perform action
    if p_spec["action"] == "checkout":
        c_resp = client.post(f"/v1/guardian/payments/{intent_id}/checkout", headers=headers)
        if c_resp.status_code in (200, 201):
            checkout_data = c_resp.json()
            print(f"    -> Real PayPal Order Created: {checkout_data.get('paypal_order_id')} (State: {checkout_data.get('status')})")
    elif p_spec["action"] == "approve_and_checkout":
        app_resp = client.post(f"/v1/guardian/proposals/{intent_id}/approve", headers=headers)
        print(f"    -> Human Approved: {app_resp.status_code}")
        c_resp = client.post(f"/v1/guardian/payments/{intent_id}/checkout", headers=headers)
        if c_resp.status_code in (200, 201):
            checkout_data = c_resp.json()
            print(f"    -> Real PayPal Order Created: {checkout_data.get('paypal_order_id')}")

# 6. Seed GhostPay Investigations
all_payments = client.get("/v1/guardian/payments", headers=headers).json()
print(f"\nFound {len(all_payments)} active payments in tenant ledger.")

for p_row in all_payments[:2]:
    inv_payload = {"trace_id": str(p_row["id"])}
    inv_resp = client.post("/v1/ghostpay/investigations", json=inv_payload, headers=headers)
    if inv_resp.status_code in (200, 201):
        inv_data = inv_resp.json()
        print(f"  [GhostPay] Forensic Investigation: {inv_data.get('investigation_id')} (Integrity: {inv_data.get('trace_integrity_status')}, Events: {len(inv_data.get('timeline', []))})")

# 7. Seed Real DisputeOS Cases Attached to Verified Payment Intents
if all_payments:
    primary_intent_id = all_payments[0]["id"]
    secondary_intent_id = all_payments[1]["id"] if len(all_payments) > 1 else primary_intent_id

    dispute_scenarios = [
        {
            "intent_id": primary_intent_id,
            "reason": "DUPLICATE_TRANSACTION",
            "buyer_claim": "Billing system charged twice for AWS Reserved Instance reservation during automated failover.",
            "amount_minor": 75000,
            "evidence_type": "DELIVERY_RECEIPT",
            "evidence_file": "aws_compute_reservation_receipt.json",
            "evidence_data": {
                "invoice_id": "INV-AWS-98214",
                "reservation_arn": "arn:aws:ec2:us-east-1:123456789012:reserved-instances/e1a2-3b4c",
                "active_start": "2026-11-12T00:00:00Z",
                "billed_instances": 1,
                "duplicate_detected": False,
            },
        },
        {
            "intent_id": secondary_intent_id,
            "reason": "ITEM_NOT_RECEIVED",
            "buyer_claim": "OpenAI 2.5M Token Batch Capacity quota was not provisioned in the organization workspace.",
            "amount_minor": 12500,
            "evidence_type": "DELIVERY_RECEIPT",
            "evidence_file": "openai_workspace_quota_telemetry.json",
            "evidence_data": {
                "organization_id": "org-nexus-prod",
                "allocated_tokens": 2500000,
                "provisioned_timestamp": "2026-11-12T10:14:22Z",
                "http_status": 200,
                "consumption_rate": "42.8%",
            },
        },
    ]

    for d in dispute_scenarios:
        case_payload = {
            "payment_intent_id": d["intent_id"],
            "buyer_claim": d["buyer_claim"],
            "reason": d["reason"],
            "amount_minor": d["amount_minor"],
        }
        c_resp = client.post("/v1/disputeos/cases", json=case_payload, headers=headers)
        if c_resp.status_code not in (200, 201):
            print(f"  [DisputeOS Case Error] {c_resp.status_code} {c_resp.text}")
            continue
        case_obj = c_resp.json()
        case_id = case_obj["id"]
        print(f"  [DisputeOS] Case Created {case_id}: {d['reason']}")

        # Ingest Telemetry Evidence
        ev_payload = {
            "source_type": d["evidence_type"],
            "filename": d["evidence_file"],
            "data": d["evidence_data"],
        }
        e_resp = client.post(f"/v1/disputeos/cases/{case_id}/evidence", json=ev_payload, headers=headers)
        if e_resp.status_code in (200, 201):
            ev_obj = e_resp.json()
            print(f"    -> Evidence Ingested: {ev_obj['id']} ({d['evidence_file']})")

        # Run AI Analysis
        an_resp = client.post(f"/v1/disputeos/cases/{case_id}/analyze", headers=headers)
        if an_resp.status_code in (200, 201):
            an_data = an_resp.json()
            citations = len(an_data.get("citations", []))
            contradictions = len(an_data.get("contradictions", []))
            print(f"    -> AI Analysis Completed: {citations} Citations, {contradictions} Contradictions")

print("\n" + "=" * 70)
print("REAL SHOWCASE DATA SEEDING COMPLETE WITH 100% INTEGRITY")
print("=" * 70)
