"""Comprehensive Critical Live Verification Suite for AEGIS Staging.

Tests every subsystem:
1. Infrastructure & Edge Health
2. Auth, Multitenancy & RBAC
3. Guardian Governance (Agents, Merchants, Spending Passports)
4. Guardian Policy Engine & Human Approval
5. Live PayPal Sandbox Orders v2 & Unapproved Capture Guard
6. GhostPay Replay & Investigations
7. DisputeOS Case Lifecycle, Evidence Upload & AI Analysis
8. Webhook Security & Fail-Closed Signature Enforcement
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import httpx

BASE_URL = os.getenv("AEGIS_STAGING_URL", "https://api-staging.abhinavkumarsingh.tech")

print("=" * 70, flush=True)
print("AEGIS CRITICAL SUBSYSTEM VERIFICATION SUITE — LIVE STAGING", flush=True)
print(f"Target Base URL: {BASE_URL}", flush=True)
print("=" * 70 + "\n", flush=True)

results: dict[str, str] = {}
transport = httpx.HTTPTransport(retries=3)

with httpx.Client(base_url=BASE_URL, transport=transport, timeout=30.0) as client:
    # -------------------------------------------------------------------------
    # 1. Infrastructure & Health
    # -------------------------------------------------------------------------
    t0 = time.time()
    h_resp = client.get("/health")
    r_resp = client.get("/ready")
    latency = int((time.time() - t0) * 1000)
    print(f"[1/8] INFRASTRUCTURE HEALTH: HTTP {h_resp.status_code} ({latency}ms)", flush=True)
    print(f"      /health -> {h_resp.json()}", flush=True)
    print(f"      /ready  -> {r_resp.json()}", flush=True)
    assert h_resp.status_code == 200, f"Health check failed: {h_resp.text}"
    assert r_resp.status_code == 200, f"Ready check failed: {r_resp.text}"
    assert r_resp.json().get("database") == "connected"
    assert r_resp.json().get("paypal_configured") is True
    results["Infrastructure"] = "PASS"

    # -------------------------------------------------------------------------
    # 2. Authentication & Multitenancy
    # -------------------------------------------------------------------------
    ts = uuid.uuid4().hex[:8]
    email = f"chief-auditor-{ts}@aegis-nexus.tech"
    password = "SuperSecurePassword123!@#"
    org_name = f"AEGIS Audit Org {ts}"
    org_slug = f"aegis-audit-{ts}"

    reg_resp = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Chief Auditor",
            "organization_name": org_name,
            "organization_slug": org_slug,
        },
    )
    print(f"\n[2/8] AUTHENTICATION & MULTI-TENANCY: HTTP {reg_resp.status_code}", flush=True)
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"
    reg_data = reg_resp.json()
    token = reg_data["access_token"]
    org_id = reg_data["active_tenant_id"]
    user_id = reg_data["user_id"]
    headers = {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}
    print(f"      Tenant ID: {org_id}", flush=True)
    print(f"      User ID:   {user_id}", flush=True)

    me_resp = client.get("/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    user_role = me_resp.json().get("role")
    user_email = me_resp.json().get("email")
    print(f"      /auth/me -> Role: {user_role} (Email: {user_email})", flush=True)
    results["Auth & Multitenancy"] = "PASS"

    # -------------------------------------------------------------------------
    # 3. AgentPay Guardian Governance Setup
    # -------------------------------------------------------------------------
    agent_resp = client.post(
        "/v1/guardian/agents",
        headers=headers,
        json={
            "name": "Live Autonomous Procurement Bot",
            "purpose": "Automated cloud compute autoscaling purchases",
            "framework": "langgraph",
            "public_fingerprint": f"sha256:{uuid.uuid4().hex}",
        },
    )
    assert agent_resp.status_code == 201, f"Create agent failed: {agent_resp.text}"
    agent_id = agent_resp.json()["id"]
    print(f"\n[3/8] GUARDIAN GOVERNANCE PROVISIONING:", flush=True)
    print(f"      Created Agent ID: {agent_id}", flush=True)

    merchant_resp = client.post(
        "/v1/guardian/merchants",
        headers=headers,
        json={
            "name": "Cloud Compute Staging Provider",
            "domain": "compute.staging.local",
            "category": "CLOUD_SERVICES",
            "is_allowlisted": True,
        },
    )
    assert merchant_resp.status_code == 201, f"Create merchant failed: {merchant_resp.text}"
    merchant_id = merchant_resp.json()["id"]
    print(f"      Created Merchant ID: {merchant_id}", flush=True)

    passport_resp = client.post(
        "/v1/guardian/passports",
        headers=headers,
        json={
            "agent_id": agent_id,
            "total_budget_minor": 500000,           # $5,000.00
            "per_tx_limit_minor": 150000,            # $1,500.00
            "daily_limit_minor": 200000,             # $2,000.00
            "human_approval_threshold_minor": 2500,  # $25.00 threshold
            "allowed_categories": ["CLOUD_SERVICES"],
            "allowed_merchant_ids": [merchant_id],
            "allow_unknown_merchants": False,
        },
    )
    assert passport_resp.status_code == 201, f"Create passport failed: {passport_resp.text}"
    passport_id = passport_resp.json()["id"]
    print(f"      Issued Spending Passport: {passport_id} (Budget: $5,000.00, Threshold: $25.00)", flush=True)
    results["Guardian Governance"] = "PASS"

    # -------------------------------------------------------------------------
    # 4. Spending Proposals & Policy Engine
    # -------------------------------------------------------------------------
    # Proposal 1: Auto-approved ($15.00 < $25.00 threshold)
    prop1_resp = client.post(
        "/v1/guardian/proposals",
        headers=headers,
        json={
            "agent_id": agent_id,
            "passport_id": passport_id,
            "merchant_id": merchant_id,
            "merchant_name": "Cloud Compute Staging Provider",
            "merchant_category": "CLOUD_SERVICES",
            "amount_minor": 1500,  # $15.00
            "currency": "USD",
            "item_summary": "Spot compute memory burst tier",
            "rationale": "High memory workload",
            "idempotency_key": f"prop1-{ts}",
        },
    )
    assert prop1_resp.status_code == 201, f"Proposal 1 failed: {prop1_resp.text}"
    prop1 = prop1_resp.json()["payment_intent"]
    p1_state = prop1.get("state")
    print(f"\n[4/8] POLICY ENGINE & HUMAN APPROVAL:", flush=True)
    print(f"      Proposal 1 ($15.00 < $25.00 threshold) -> State: {p1_state} (CHECKOUT_READY)", flush=True)
    assert p1_state == "CHECKOUT_READY"

    # Proposal 2: Exceeds threshold ($50.00 > $25.00 threshold) -> AWAITING_APPROVAL
    prop2_resp = client.post(
        "/v1/guardian/proposals",
        headers=headers,
        json={
            "agent_id": agent_id,
            "passport_id": passport_id,
            "merchant_id": merchant_id,
            "merchant_name": "Cloud Compute Staging Provider",
            "merchant_category": "CLOUD_SERVICES",
            "amount_minor": 5000,  # $50.00
            "currency": "USD",
            "item_summary": "Reserved instance compute cluster",
            "rationale": "Capacity baseline requirement",
            "idempotency_key": f"prop2-{ts}",
        },
    )
    assert prop2_resp.status_code == 201, f"Proposal 2 failed: {prop2_resp.text}"
    prop2 = prop2_resp.json()["payment_intent"]
    p2_state = prop2.get("state")
    print(f"      Proposal 2 ($50.00 > $25.00 threshold) -> State: {p2_state} (AWAITING_APPROVAL)", flush=True)
    assert p2_state == "AWAITING_APPROVAL"

    # Human Approval for Proposal 2
    appr_resp = client.post(
        f"/v1/guardian/proposals/{prop2['id']}/approve",
        headers=headers,
        json={
            "approver_id": user_id,
            "comment": "Approved by Chief Auditor in live verification",
        },
    )
    assert appr_resp.status_code == 200, f"Approve proposal failed: {appr_resp.text}"
    appr_state = appr_resp.json()["payment_intent"].get("state")
    print(f"      Human Approval Decided -> State: {appr_state}", flush=True)
    results["Policy & Human Approval"] = "PASS"

    # -------------------------------------------------------------------------
    # 5. Live PayPal Sandbox Orders v2 & Capture Guard
    # -------------------------------------------------------------------------
    intent_id = prop1["id"]
    chk_resp = client.post(
        f"/v1/guardian/payments/{intent_id}/checkout",
        headers=headers,
        json={"idempotency_key": f"chk-{ts}"},
    )
    assert chk_resp.status_code == 200, f"Checkout failed: {chk_resp.text}"
    chk = chk_resp.json()
    pp_order_id = chk["attempt"]["paypal_order_id"]
    approval_url = chk["approval_url"]
    print(f"\n[5/8] LIVE PAYPAL SANDBOX RAIL:", flush=True)
    print(f"      Created Live Order on PayPal: {pp_order_id}", flush=True)
    print(f"      Approval URL:                 {approval_url}", flush=True)
    assert pp_order_id and "sandbox.paypal.com" in approval_url

    # Premature capture attempt must be rejected
    cap_bad = client.post(
        f"/v1/guardian/payments/{intent_id}/capture",
        headers=headers,
        json={"attempt_id": chk["attempt"]["id"]},
    )
    print(f"      Premature Capture Attempt HTTP: {cap_bad.status_code} (Rejection confirmed)", flush=True)
    assert cap_bad.status_code in (400, 409, 422)
    results["PayPal Sandbcookie, or PayPal Sandbox login issue—not your AEGIS API, since your OAuth and order tests passed.

Try this in Brave:

Close the PayPal checkout and login tabs.

Open a new Private Window using Ctrl + Shift + N.

Open PayPal Sandbox Login.

Click the Brave Shields icon (lion icon) in the address bar and turn Shields off for this Sandbox site only.

Disable any VPN or browser extension that might interfere with login.

Refresh using Ctrl + Shift + R.

Sign in using the Sandbox Personal buyer account, not your real Gmail account.

PayPal confirms that Sandbox Personal accounts use their own generated email/password and simulated funds. 
￼
PayPal Developer
+1

If it still spins, try Firefox or Chrome in a fresh private window. You can also check PayPal Service Status for Sandbox incidents.
cookie, or PayPal Sandbox login issue—not your AEGIS API, since your OAuth and order tests passed.

Try this in Brave:

Close the PayPal checkout and login tabs.

Open a new Private Window using Ctrl + Shift + N.

Open PayPal Sandbox Login.

Click the Brave Shields icon (lion icon) in the address bar and turn Shields off for this Sandbox site only.

Disable any VPN or browser extension that might interfere with login.

Refresh using Ctrl + Shift + R.

Sign in using the Sandbox Personal buyer account, not your real Gmail account.

PayPal confirms that Sandbox Personal accounts use their own generated email/password and simulated funds. 
￼
PayPal Developer
+1

If it still spins, try Firefox or Chrome in a fresh private window. You can also check PayPal Service Status for Sandbox incidents.

Don't enter your real card details.

One thing I need to identify the exact problem: Is it spinning before the login form appears, or after you enter the Sandbox buyer email and password and click Log In?
Don't enter your real card details.

One thing I need to identify the exact problem: Is it spinning before the login form appears, or after you enter the Sandbox buyer email and password and click Log In?ox Rail"] = "PASS"

    # -------------------------------------------------------------------------
    # 6. GhostPay Forensics & Investigations
    # -------------------------------------------------------------------------
    inv_resp = client.post(
        "/v1/ghostpay/investigations",
        headers=headers,
        json={"trace_id": str(intent_id)},
    )
    assert inv_resp.status_code in (200, 201), f"Investigation failed: {inv_resp.text}"
    inv_data = inv_resp.json()
    inv_id = inv_data.get("investigation_id") or inv_data.get("id")
    print(f"\n[6/8] GHOSTPAY FORENSICS:", flush=True)
    print(f"      Created Investigation ID: {inv_id}", flush=True)
    print(f"      Trace Icookie, or PayPal Sandbox login issue—not your AEGIS API, since your OAuth and order tests passed.

Try this in Brave:

Close the PayPal checkout and login tabs.

Open a new Private Window using Ctrl + Shift + N.

Open PayPal Sandbox Login.

Click the Brave Shields icon (lion icon) in the address bar and turn Shields off for this Sandbox site only.

Disable any VPN or browser extension that might interfere with login.

Refresh using Ctrl + Shift + R.

Sign in using the Sandbox Personal buyer account, not your real Gmail account.

PayPal confirms that Sandbox Personal accounts use their own generated email/password and simulated funds. 
￼
PayPal Developer
+1

If it still spins, try Firefox or Chrome in a fresh private window. You can also check PayPal Service Status for Sandbox incidents.

Don't enter your real card details.

One thing I need to identify the exact problem: Is it spinning before the login form appears, or after you enter the Sandbox buyer email and password and click Log In?ntegrity Status:   {inv_data.get('trace_integrity_status')}", flush=True)
    print(f"      Timeline Verified Events: {len(inv_data.get('timeline', []))}", flush=True)
    for evt in inv_data.get("timeline", []):
        print(f"       -> Seq {evt.get('sequence_number')}: {evt.get('event_type')} ({evt.get('summary')[:50]}...)", flush=True)

    timeline_resp = client.get(f"/v1/ghostpay/timeline/by-payment/{intent_id}", headers=headers)
    assert timeline_resp.status_code == 200, f"Timeline failed: {timeline_resp.text}"
    timeline_entries = timeline_resp.json()
    print(f"      Timeline by Payment Intent: {len(timeline_entries)} events verified", flush=True)

    replay_resp = client.post(f"/v1/ghostpay/replay/by-payment/{intent_id}", headers=headers)
    assert replay_resp.status_code == 200, f"Replay failed: {replay_resp.text}"
    replay_data = replay_resp.json()
    print(f"      Replay Invariant Outcome:   Outcome={replay_data.get('outcome')}, Mismatch={replay_data.get('divergence_detected')}", flush=True)

    profile_resp = client.get(f"/v1/ghostpay/agents/{agent_id}/profile", headers=headers)
    assert profile_resp.status_code == 200, f"Profile failed: {profile_resp.text}"
    print(f"      Agent Behavior Profile:     {profile_resp.json().get('status', 'OK')}", flush=True)
    results["GhostPay Forensics"] = "PASS"
cookie, or PayPal Sandbox login issue—not your AEGIS API, since your OAuth and order tests passed.

Try this in Brave:

Close the PayPal checkout and login tabs.

Open a new Private Window using Ctrl + Shift + N.

Open PayPal Sandbox Login.

Click the Brave Shields icon (lion icon) in the address bar and turn Shields off for this Sandbox site only.

Disable any VPN or browser extension that might interfere with login.

Refresh using Ctrl + Shift + R.

Sign in using the Sandbox Personal buyer account, not your real Gmail account.

PayPal confirms that Sandbox Personal accounts use their own generated email/password and simulated funds. 
￼
PayPal Developer
+1

If it still spins, try Firefox or Chrome in a fresh private window. You can also check PayPal Service Status for Sandbox incidents.

Don't enter your real card details.

One thing I need to identify the exact problem: Is it spinning before the login form appears, or after you enter the Sandbox buyer email and password and click Log In?
    # -------------------------------------------------------------------------
    # 7. DisputeOS Case Lifecycle & AI Analysis
    # -------------------------------------------------------------------------
    case_resp = client.post(
        "/v1/disputeos/cases",
        headers=headers,
        json={
            "payment_intent_id": str(intent_id),
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "buyer_claim": "Buyer claims cloud spot compute instances were not provisioned during memory pressure.",
            "amount_minor": 1500,
            "currency": "USD",
            "source_type": "SYNTHETIC_DEMO",
            "is_synthetic": True,
        },
    )
    assert case_resp.status_code == 201, f"Case creation failed: {case_resp.text}"
    case_data = case_resp.json()
    case_id = case_data["id"]
    print(f"\n[7/8] DISPUTEOS CASE LIFECYCLE:", flush=True)
    print(f"      Created Dispute Case ID:  {case_id}", flush=True)

    ev_resp = client.post(
        f"/v1/disputeos/cases/{case_id}/evidence",
        headers=headers,
        json={
            "source_type": "DELIVERY_RECEIPT",
            "source_ref": f"azure-vm-telemetry-{ts}",
            "title": "Compute Instance Delivery Receipt & Telemetry",
            "content": {
                "instance_id": "spot-4x-a100",
                "uptime_seconds": 3600,
                "gpu_utilization_pct": 98.4,
                "status": "COMPLETED_DELIVERED",
            },
            "is_synthetic": True,
        },
    )
    assert ev_resp.status_code in (200, 201), f"Evidence upload failed: {ev_resp.text}"
    ev_data = ev_resp.json()
    ev_id = ev_data.get("evidence", {}).get("id") or ev_data.get("evidence_id")
    print(f"      Evidence Ingested ID:     {ev_id}", flush=True)

    analyze_resp = client.post(f"/v1/disputeos/cases/{case_id}/analyze", headers=headers)
    assert analyze_resp.status_code == 200, f"Dispute analysis failed: {analyze_resp.text}"
    analysis = analyze_resp.json().get("analysis", {})
    summary_text = analysis.get("grounded_summary", "Generated analysis")[:60]
    print(f"      Dispute AI Analysis:      Summary: {summary_text}...", flush=True)
    print(f"      Contradictions Detected:  {len(analysis.get('contradictions', []))}", flush=True)
    print(f"      Validated Citations:      {len(analysis.get('citations', []))}", flush=True)
    results["DisputeOS Lifecycle"] = "PASS"

    # -------------------------------------------------------------------------
    # 8. Webhook Security Verification
    # -------------------------------------------------------------------------
    wh_probe = client.post("/v1/paypal/webhooks", json={"event_type": "PAYMENT.CAPTURE.COMPLETED"})
    print(f"\n[8/8] WEBHOOK INTEGRITY & SIGNATURE ENFORCEMENT:", flush=True)
    print(f"      Unsigned Webhook Probe -> HTTP {wh_probe.status_code} (Unauthorized: Fail-Closed)", flush=True)
    assert wh_probe.status_code == 401
    results["Webhook Security"] = "PASS"

print("\n" + "=" * 70, flush=True)
print("ALL 8 CRITICAL SUBSYSTEM TESTS PASSED WITH 100% SUCCESS", flush=True)
for sub, res in results.items():
    print(f"  {sub:28}: {res}", flush=True)
print("=" * 70 + "\n", flush=True)
