# Runbook: PayPal Webhook Operations & Signature Verification

**Document:** `docs/runbooks/PAYPAL_WEBHOOK_OPERATIONS.md`  
**Revision Date:** `2026-11-12`  
**Service:** `services/api/aegis_api/routers/webhooks.py`  
**Endpoint:** `POST https://api-staging.abhinavkumarsingh.tech/v1/paypal/webhooks`  

---

## 1. Webhook Lifecycle & Architecture

```
[ PayPal Sandbox / Live Webhook Dispatcher ]
                     │ (Outbound HTTPS POST with PayPal Headers)
                     ▼
      [ Cloudflare Edge Proxy (TLS Termination) ]
                     │
                     ▼
    [ Azure VM Nginx -> FastAPI :8000 (/v1/paypal/webhooks) ]
                     │
                     ├─► 1. Extract Headers: PAYPAL-AUTH-ALGO, PAYPAL-CERT-URL,
                     │      PAYPAL-TRANSMISSION-ID, PAYPAL-TRANSMISSION-SIG,
                     │      PAYPAL-TRANSMISSION-TIME
                     │
                     ├─► 2. Authenticated Signature Verification:
                     │      Calls PayPal REST API /v1/notifications/verify-webhook-signature
                     │      with configured PAYPAL_WEBHOOK_ID.
                     │      If verification fails -> HTTP 401 Unauthorized (Fail-Closed).
                     │
                     ├─► 3. Deduplication Check:
                     │      Checks paypal_webhook_events table in Neon DB.
                     │      If event_id already exists -> HTTP 200 {"verified": true, "deduplicated": true}
                     │
                     └─► 4. Order Correlation & Event Ledger:
                            Matches resource.supplementary_data.related_ids.order_id
                            with PaymentAttemptRow.paypal_order_id.
                            Appends FinancialEventType.PAYPAL_WEBHOOK_RECEIVED.
```

---

## 2. Inbound Webhook Inspection

To inspect recent incoming PayPal webhooks:

### Via API Logs on Azure VM
```bash
sudo docker compose logs --tail=100 api | grep -E "paypal/webhooks|verify-webhook-signature"
```

### Via Direct Neon Database Query
```sql
SELECT 
    event_id, 
    event_type, 
    resource_id, 
    payload_hash, 
    received_at 
FROM paypal_webhook_events 
ORDER BY received_at DESC 
LIMIT 20;
```

---

## 3. Troubleshooting & Failure Modes

| Symptom | Cause | Remediation |
| :--- | :--- | :--- |
| **HTTP 401 on Webhook** | Missing or invalid PayPal transmission headers, or incorrect `PAYPAL_WEBHOOK_ID`. | Check `.env` for `PAYPAL_WEBHOOK_ID=2JA67664A1962980D`. Verify that incoming request headers are passed by Nginx without stripping. |
| **HTTP 400 on Webhook** | Malformed JSON payload. | Inspect request body in logs; ensure payload is a valid JSON dictionary. |
| **Webhook Delivery Delayed** | PayPal Sandbox experiencing queuing. | PayPal guarantees retries with exponential backoff for up to 72 hours. Staging idempotency deduplicates when delivered. |
| **Unmatched Order ID** | Webhook received for an order created outside AEGIS. | The event is recorded in `paypal_webhook_events` for auditing, but no internal `PaymentAttempt` is modified (`matched_payment_intent_id: null`). |

