# Runbook: Incident Response & Containment

**Version:** 1.0.0  
**Effective Date:** November 12, 2026  
**Service:** AEGIS Control Plane (`services/api`), Background Worker (`services/worker`), and Forensic Engine

---

## 1. Severity Classification & Response Matrix

| Severity | Definition & Impact | Response SLA | Incident Commander |
| :--- | :--- | :--- | :--- |
| **SEV-1 (Critical)** | Active unauthorized financial spend, runaway AI agent loop, cryptographic hash-chain corruption, cross-tenant isolation breach, or complete API control plane outage. | **< 15 minutes** | VP Engineering / Head of Security |
| **SEV-2 (High)** | Worker outbox stalled, webhook dead-letter backlog > 500 events, payment provider capture timeout rate > 5%, or PostgreSQL connection exhaustion. | **< 1 hour** | Lead Backend Engineer / On-Call SRE |
| **SEV-3 (Medium)** | Individual payment state sync lag, isolated dispute upload failures, or transient rate-limiting spikes. | **< 4 hours** | On-Call Application Engineer |
| **SEV-4 (Low)** | Non-blocking cosmetic dashboard bugs, minor telemetry delays, or documentation discrepancies. | **Next business day** | Product Engineering Team |

---

## 2. Emergency Containment Playbooks (Phase 2: Immediate Containment)

### Playbook A: Runaway AI Agent / Rogue Spend Loop
If an autonomous agent begins spamming proposals, making unauthorized merchant calls, or attempting to exhaust budget limits:

1. **Suspend the Agent via API**:
   ```bash
   curl -X POST "https://api.aegis.internal/v1/guardian/agents/${AGENT_ID}/suspend" \
     -H "Authorization: Bearer ${OPERATOR_JWT}" \
     -H "Content-Type: application/json" \
     -d '{"reason": "SEV-1 containment: abnormal spend velocity"}'
   ```
   *Direct SQL Emergency Fallback:*
   ```sql
   UPDATE agent_rows
   SET status = 'SUSPENDED', updated_at = NOW()
   WHERE id = '550e8400-e29b-41d4-a716-446655440000';
   ```

2. **Revoke the Agent's Spending Passport**:
   ```bash
   curl -X POST "https://api.aegis.internal/v1/guardian/passports/${PASSPORT_ID}/revoke" \
     -H "Authorization: Bearer ${OPERATOR_JWT}" \
     -H "Content-Type: application/json" \
     -d '{"reason": "Immediate security revocation"}'
   ```
   *Effect*: Automatically zeroes remaining allocation and forces all incoming proposals to fail-closed with `DENIED_PASSPORT_REVOKED`.

3. **Revoke Compromised API Key**:
   ```bash
   curl -X POST "https://api.aegis.internal/v1/orgs/api-keys/${KEY_ID}/revoke" \
     -H "Authorization: Bearer ${ADMIN_JWT}"
   ```

---

### Playbook B: Payment Intent Lock / Stuck Provider Capture
If transactions are stuck in `CAPTURE_PENDING` or `PENDING_PROVIDER`:

1. **Inspect Stuck Intents**:
   ```sql
   SELECT id, agent_id, merchant_name, amount_minor, state, updated_at
   FROM payment_intent_rows
   WHERE state IN ('CAPTURE_PENDING', 'PENDING_PROVIDER')
     AND updated_at < NOW() - INTERVAL '15 minutes';
   ```

2. **Trigger Worker Outbox Reconciliation Loop**:
   ```bash
   # In worker container or via CLI:
   docker exec -it aegis_worker python -m aegis_worker.reconcile --stuck-window 900
   ```

3. **Release Uncaptured Reservations**:
   ```sql
   -- Release held budget for cancelled/expired intents safely:
   UPDATE budget_reservation_rows
   SET status = 'RELEASED', released_at = NOW()
   WHERE status = 'HELD'
     AND payment_intent_id IN (
       SELECT id FROM payment_intent_rows WHERE state IN ('FAILED', 'CANCELLED', 'EXPIRED')
     );
   ```

---

## 3. Forensic Investigation & Evidence Preservation (Phase 3)

### 3.1. Reconstruct Decision State in GhostPay
Execute a read-only deterministic replay of the contested transaction:
```bash
curl -X POST "https://api.aegis.internal/v1/ghostpay/replay/by-payment/${INTENT_ID}" \
  -H "Authorization: Bearer ${AUDITOR_JWT}" \
  -H "Content-Type: application/json"
```
**Verify Verification Output:**
- Ensure `executed_payment` is `false`.
- If `consistency_status == "CONSISTENT"`, the transaction conformed to registered policies at authorization time.
- If `consistency_status == "AUTHORIZATION_DRIFT"`, review drift fields in `mismatched_fields`.

### 3.2. Validate Hash-Chain Integrity
Query the event stream for the correlation ID:
```bash
curl "https://api.aegis.internal/v1/audit-events?correlation_id=${CORRELATION_ID}" \
  -H "Authorization: Bearer ${AUDITOR_JWT}"
```
Verify that every `event_hash` successfully chains to `previous_event_hash` from genesis `0000000000000000000000000000000000000000000000000000000000000000`.

---

## 4. Remediation & Recovery (Phase 4)

1. **Verify Ledger Balance Equivalence**:
   ```sql
   SELECT 
       agent_id,
       SUM(amount_minor) FILTER (WHERE status = 'CAPTURED') AS total_captured,
       SUM(amount_minor) FILTER (WHERE status = 'HELD') AS total_held
   FROM budget_reservation_rows
   GROUP BY agent_id;
   ```
2. **Rotate Affected Secrets & Service Accounts**:
   - Issue new API keys with scoped `AGENT_SERVICE` roles.
   - Rotate database credentials if privilege escalation was detected.
3. **Re-enable Suspended Services**:
   - Once threat actors or runaway loops are mitigated, restore agent status from `SUSPENDED` to `ACTIVE`.

---

## 5. Post-Mortem Template (Phase 5)

Within 48 hours of resolving a SEV-1 or SEV-2 incident, complete and distribute the post-mortem report:

```markdown
# Incident Post-Mortem: [INCIDENT TITLE]

- **Date:** YYYY-MM-DD
- **Severity:** SEV-[1|2]
- **Duration:** [HH:MM]
- **Lead Responder:** [Name]

## 1. Summary
[High-level summary of the incident and financial impact]

## 2. Root Cause
[Technical root cause analysis: code bug, policy misconfiguration, provider API timeout]

## 3. Timeline (UTC)
- **HH:MM** - Anomaly detected via alert [Name]
- **HH:MM** - Incident triage and SEV classification
- **HH:MM** - Agent suspended / Passport revoked
- **HH:MM** - GhostPay replay completed
- **HH:MM** - Full recovery and validation

## 4. Corrective Actions
| Action Item | Owner | Target Date | Status |
| :--- | :--- | :--- | :--- |
| Add velocity rate limiter to AgentPay Guardian | Backend Lead | YYYY-MM-DD | OPEN |
| Expand webhook DLQ alerting threshold | SRE | YYYY-MM-DD | OPEN |
```
