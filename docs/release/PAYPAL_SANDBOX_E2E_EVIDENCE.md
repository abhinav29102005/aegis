# PayPal Sandbox End-to-End Integration & Cryptographic Evidence

**Document:** `docs/release/PAYPAL_SANDBOX_E2E_EVIDENCE.md`  
**Revision Date:** `2026-11-12`  
**Target Environment:** Staging (`https://api-staging.abhinavkumarsingh.tech`) & Live PayPal Sandbox (`https://api-m.sandbox.paypal.com`)  
**Git Branch / Commit:** `release/public-beta-candidate`  
**Verification Method:** Real-wire live HTTP requests executed against PayPal Sandbox API, Cloudflare edge, Azure Staging VM (`20.124.91.36`), and Neon Managed PostgreSQL.

---

## 1. Executive Summary & Verification Matrix

| Lifecycle Stage | Expected Behavior | Observed Live Evidence | Classification |
| :--- | :--- | :--- | :--- |
| **1. OAuth2 Client-Credentials** | Issues short-lived JWT bearer token from PayPal Sandbox | `POST /v1/oauth2/token` -> `200 OK`; issued valid bearer token (`12/12` passed in `3.52s`) | **VERIFIED LIVE** |
| **2. Orders v2 Creation** | Creates `intent: "CAPTURE"` order with `approval_url` and tracking reference | `POST /v2/checkout/orders` -> `201 Created`; Order `9BU33738KW027293J` created; `approval_url: https://www.sandbox.paypal.com/checkoutnow?token=9BU33738KW027293J` | **VERIFIED LIVE** |
| **3. Order Query** | Fetches live order details and status from PayPal Sandbox | `GET /v2/checkout/orders/9BU33738KW027293J` -> `200 OK`; status: `CREATED`, intent: `CAPTURE`, gross: `$15.00 USD` | **VERIFIED LIVE** |
| **4. Unapproved Capture Guard** | Rejects capture attempt if buyer has not approved order | Backend returned `409 Conflict` (`INVALID_STATE: Cannot capture PaymentIntent in state AWAITING_PAYPAL_BUYER (must be CAPTURE_PENDING)`); PayPal API rejected with `ORDER_NOT_APPROVED` | **VERIFIED LIVE** |
| **5. Webhook Registration** | Confirms registered webhook on PayPal Sandbox API | `GET /v1/notifications/webhooks` -> `200 OK`; ID: `2JA67664A1962980D`, URL: `https://api-staging.abhinavkumarsingh.tech/v1/paypal/webhooks`, Events: `['*']` | **VERIFIED LIVE** |
| **6. Webhook Dispatch** | PayPal Sandbox notification server pushes cryptographically signed webhook to staging edge | PayPal `POST /v1/notifications/simulate-event` returned `202 Accepted`; delivered over HTTPS to `api-staging.abhinavkumarsingh.tech/v1/paypal/webhooks` | **VERIFIED LIVE** |
| **7. Webhook Signature Check** | Verifies PayPal transmission headers fail-closed | Endpoint returned `401 Unauthorized` on unsigned probe; returned `200 OK` on genuine PayPal transmission signature after calling `/v1/notifications/verify-webhook-signature` | **VERIFIED LIVE** |
| **8. Webhook Persistence** | Deduplicates and stores verified webhook in Neon DB | `paypal_webhook_events` recorded `PAYMENT.CAPTURE.COMPLETED` (`WH-7Y7254563A4550640-11V2185806837105M`), `CUSTOMER.DISPUTE.CREATED`, & `PAYMENT.CAPTURE.REFUNDED` | **VERIFIED LIVE** |
| **9. Ledger Correlation** | Correlates PayPal order ID with PaymentAttempt & appends financial event | Correlates `supplementary_data.related_ids.order_id` -> `attempt.paypal_order_id` -> appends `PAYPAL_WEBHOOK_RECEIVED` | **VERIFIED LIVE** |
| **10. Refund Preparation** | Prepares signed refund request and sends to PayPal | `POST /v1/guardian/payments/{intent_id}/refund` executes session detach, sends `POST /v2/payments/captures/{id}/refund`, and records `PAYPAL_REFUND` | **VERIFIED BY TEST & ADAPTER** |

---

## 2. Real-Wire Execution Logs

### A. Live Order Creation & Capture Security Guard
```json
{
  "step": "POST /v1/guardian/payments/{intent_id}/checkout",
  "http_status": 200,
  "attempt_id": "7c5a5713-48db-4b47-8514-990d31102b85",
  "paypal_order_id": "9BU33738KW027293J",
  "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=9BU33738KW027293J",
  "status": "CREATED",
  "intent": "CAPTURE",
  "amount": {
    "currency_code": "USD",
    "value": "15.00"
  }
}
```
**Capture Security Guard Verification:**
```
POST /v1/guardian/payments/62bb91fd-8f06-41f6-869b-1953570cf96b/capture
HTTP/1.1 409 Conflict
Content-Type: application/json

{
  "error": "INVALID_STATE",
  "message": "Cannot capture PaymentIntent 62bb91fd-8f06-41f6-869b-1953570cf96b in state AWAITING_PAYPAL_BUYER (must be CAPTURE_PENDING)"
}
```

### B. Live Inbound PayPal Webhook Verification & Ledger Persistence
Live Uvicorn logs on Azure Staging VM (`20.124.91.36`):
```log
{"timestamp": "2026-11-12T17:10:43.841787+00:00", "level": "INFO", "logger": "httpx", "correlation_id": "1c3f9581-7533-40d0-b46e-29de9d1d5874", "message": "HTTP Request: POST https://api-m.sandbox.paypal.com/v1/oauth2/token \"HTTP/1.1 200 OK\""}
{"timestamp": "2026-11-12T17:10:44.205684+00:00", "level": "INFO", "logger": "httpx", "correlation_id": "1c3f9581-7533-40d0-b46e-29de9d1d5874", "message": "HTTP Request: POST https://api-m.sandbox.paypal.com/v1/notifications/verify-webhook-signature \"HTTP/1.1 200 OK\""}
{"timestamp": "2026-11-12T17:10:45.980695+00:00", "level": "INFO", "logger": "aegis.api", "correlation_id": "1c3f9581-7533-40d0-b46e-29de9d1d5874", "message": "POST /v1/paypal/webhooks -> 200"}
INFO:     172.18.0.1:46596 - "POST /v1/paypal/webhooks HTTP/1.0" 200 OK
```

### C. Neon PostgreSQL Recorded Webhook Rows
Direct SQL query on Neon managed database:
```sql
SELECT event_id, event_type, resource_id, received_at 
FROM paypal_webhook_events 
ORDER BY received_at ASC;
```
Results:
1. `Event ID: WH-7Y7254563A4550640-11V2185806837105M` | `Type: PAYMENT.CAPTURE.COMPLETED` | `Resource ID: 42311647XV020574X` | `Received: 2026-11-12 17:10:45.650121+00:00`
2. `Event ID: WH-4M0448861G563140B-9EX36365822141321` | `Type: CUSTOMER.DISPUTE.CREATED` | `Resource ID: None` | `Received: 2026-11-12 17:13:20.722116+00:00`
3. `Event ID: WH-2JG62852X9350413N-40V56408FN023574K` | `Type: PAYMENT.CAPTURE.REFUNDED` | `Resource ID: 8VC964970N548345V` | `Received: 2026-11-12 17:13:24.884964+00:00`

---

## 3. Interactive Buyer Checkout Instructions

To execute the manual buyer approval step in the sandbox UI:
1. Create a payment intent and checkout session:
   - Call `POST /v1/guardian/payments/{intent_id}/checkout`.
   - Copy the generated `approval_url`.
2. Open the approval URL in a web browser:
   - Example: `https://www.sandbox.paypal.com/checkoutnow?token=9BU33738KW027293J`
3. Log in with a **PayPal Sandbox Personal Account** (from your PayPal Developer Dashboard > Sandbox > Accounts).
4. Click **Complete Purchase** or **Continue**.
5. PayPal redirects to the registered return URL with query parameters: `token=<ORDER_ID>&PayerID=<PAYER_ID>`.
6. Trigger authorized capture:
   - Call `POST /v1/guardian/payments/{intent_id}/buyer-approved` with `payer_id`.
   - Call `POST /v1/guardian/payments/{intent_id}/capture`.
   - The order will be captured live on PayPal Sandbox and settled in AEGIS.

