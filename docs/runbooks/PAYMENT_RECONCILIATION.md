# Runbook: Financial Ledger Reconciliation & Concurrency Invariants

**Document:** `docs/runbooks/PAYMENT_RECONCILIATION.md`  
**Revision Date:** `2026-11-12`  
**Scope:** `LedgerRepository`, `GuardianService`, `PaymentCoordinator`, `OutboxWorker`  

---

## 1. Concurrency & Locking Architecture

To prevent deadlocks and double-spending across concurrent requests, AEGIS enforces strict advisory transaction serialization:

### Advisory Lock Dimensions
1. **Proposal Idempotency Lock:**
   ```sql
   SELECT pg_advisory_xact_lock(hashtext(tenant_id::text), hashtext(idempotency_key));
   ```
   Acquired at the start of `GuardianService.submit_proposal()` inside the active transaction. Serializes multiple concurrent attempts using the same idempotency key, preventing TOCTOU races during intent creation.

2. **Financial Event Ledger Lock:**
   ```sql
   SELECT pg_advisory_xact_lock(hashtext(tenant_id::text), hashtext(correlation_id::text));
   ```
   Acquired in `LedgerRepository.append_financial_event()`. Replaces the earlier broad `SELECT tenants.id ... FOR UPDATE` row lock, eliminating table-level contention between concurrent proposals of the same tenant while preserving strict linear event sequence numbers per `correlation_id`.

---

## 2. Invariant Verification Checklist

Every valid payment must satisfy the following invariant rules:

1. **No Capture Before Buyer Approval:**
   A `PaymentIntent` cannot transition to `CAPTURED` or `SETTLED` unless an authentic buyer approval is recorded and the attempt is in `CAPTURE_PENDING`.

2. **Atomic Reservation:**
   When a proposal is submitted, the budget reservation (`amount_minor`) is deducted from the spending passport's remaining budget in the same transaction that inserts the intent.

3. **Clean Release on Decline or Failure:**
   If a proposal is declined (`request.approved = False`) or checkout fails, the reserved budget is immediately released back to the passport (`DECLINED` event).

4. **Append-Only Immutability:**
   Every financial state transition produces a row in `financial_events`. PostgreSQL trigger `trg_aegis_prevent_financial_event_mutation` raises an exception on any attempted `UPDATE` or `DELETE`.

5. **Idempotent Refund:**
   Refunds require an authenticated capture ID. A refund transition updates attempt status and records `PAYPAL_REFUND`, ensuring the same capture cannot be refunded twice.

---

## 3. Daily Ledger Balancing Query

Run this query against Neon PostgreSQL to verify ledger balance:

```sql
SELECT 
    tenant_id,
    COUNT(id) AS total_events,
    MAX(sequence_number) AS max_sequence,
    SUM(CASE WHEN event_type = 'PAYPAL_CAPTURE' THEN (payload->>'amount_minor')::numeric ELSE 0 END) AS total_captured_minor,
    SUM(CASE WHEN event_type = 'PAYPAL_REFUND' THEN (payload->>'amount_minor')::numeric ELSE 0 END) AS total_refunded_minor
FROM financial_events
GROUP BY tenant_id;
```

