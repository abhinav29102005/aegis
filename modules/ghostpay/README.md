# GhostPay (`modules/ghostpay/`)

**Subsystem:** Forensic Intelligence, Policy Time Machine & Agent DNA  
**Package:** `agentpay-ghostpay` (`ghostpay`)  
**Branch:** `feature/ghostpay`  
**Status:** Hardened, Reconciled & Integration-Ready

---

## 1. Subsystem Architecture

GhostPay is the forensic digital twin and behavioral intelligence subsystem of **AEGIS (AgentPay Nexus)**. It provides deterministic authorization replay, strictly validated counterfactual policy simulation (`PolicyTimeMachine`), Agent DNA behavioral profiling, anomaly detection, provenance verification, and deterministic timeline reconstruction without ever possessing financial execution authority.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AGENTPAY NEXUS CORE                              │
│                                                                             │
│   ┌───────────────────────────┐           ┌─────────────────────────────┐   │
│   │    AGENTPAY GUARDIAN      │           │         DISPUTEOS           │   │
│   │ (Pre-Transaction Control) │           │ (External Dispute Defense)  │   │
│   │                           │           │                             │   │
│   │ • Spending Passports      │           │ • Dispute Case Files        │   │
│   │ • Deterministic Policy    │           │ • Evidence Graphs           │   │
│   │ • Atomic Budget Holds     │           │ • Contradiction Detection   │   │
│   │ • PayPal Capture Exec     │           │ • Merchant Response Packets │   │
│   └─────────────┬─────────────┘           └──────────────▲──────────────┘   │
│                 │ Emits Verified                         │ Ingests Evidence │
│                 │ Financial Evidence                     │ Bundles          │
│                 ▼                                        │                  │
│   ┌──────────────────────────────────────────────────────┴──────────────┐   │
│   │                               GHOSTPAY                              │   │
│   │                    (Post-Transaction Intelligence)                  │   │
│   │                                                                     │   │
│   │   ┌─────────────────────────────┐     ┌─────────────────────────┐   │   │
│   │   │     POLICY TIME MACHINE     │     │        AGENT DNA        │   │   │
│   │   │                             │     │                         │   │   │
│   │   │ • Historical Replay         │     │ • Behavioral Baselines  │   │   │
│   │   │ • Counterfactual Overrides  │     │ • Velocity & Novelty    │   │   │
│   │   │ • Drift Detection           │     │ • Cold-Start Handling   │   │   │
│   │   │ • Policy Comparison Matrix  │     │ • Non-Authoritative     │   │   │
│   │   └─────────────────────────────┘     └─────────────────────────┘   │   │
│   │                                                                     │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │                     FORENSIC INVESTIGATION                  │   │   │
│   │   │  • Cryptographic Hash-Chain Verification (HMAC-SHA256)      │   │   │
│   │   │  • Deterministic Event Timeline Reconstruction              │   │   │
│   │   │  • Evidence Provenance Graph & Digested Citations           │   │   │
│   │   │  • Strict Non-Authoritative Safeguard Recommendations       │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Module Separation of Concerns

1. **AgentPay Guardian (`modules/agentpay-guardian/`):** The authoritative gatekeeper. Evaluates proposals against passports, reserves funds atomically, interfaces with PayPal, and signs tamper-evident audit events into the financial ledger.
2. **GhostPay (`modules/ghostpay/`):** The read-only forensic twin. Ingests Guardian event streams and evidence records, verifies cryptographic provenance, recomputes policy outcomes under counterfactual constraints, and tracks agent behavioral drift. **GhostPay never executes payments, captures funds, reserves budgets, or alters Guardian decisions.**
3. **DisputeOS (`modules/disputeos/`):** The dispute resolution subsystem. Ingests complete evidence bundles exported by GhostPay to build rebuttal graphs and contest unauthorized disputes or merchant chargebacks.

---

## 2. Directory Structure

```text
modules/ghostpay/
├── ghostpay/
│   ├── __init__.py               # Combined hardened + Policy Time Machine & Agent DNA exports
│   ├── errors.py                 # OverrideValidationError, UnsupportedPolicyVersionError, ReplayExecutionForbiddenError
│   ├── repository.py             # Read-only GhostPayReplayRepository Protocol for DB handoff
│   ├── replay/                   # Policy version registry (registry.py) & deterministic ReplayEngine (engine.py)
│   ├── counterfactual/           # Strict Pydantic v2 override validator (validator.py) & non-mutating simulator
│   ├── anomalies/                # Authorization drift, currency, policy-version, & forensic anomaly detection
│   ├── provenance/               # Evidence completeness, correlation binding, & hash-chain integrity verification
│   ├── timelines/                # Deterministic event timeline reconstruction (`build_timeline`)
│   ├── testing.py                # Isolated test trace and baseline generation utilities
│   ├── domain/
│   │   ├── exceptions.py         # GhostPayError, IntegrityError, CrossTenantAccessError, etc.
│   │   ├── models.py             # PaymentTrace, InvestigationReport, ReplayRequest converter
│   │   └── service.py            # GhostPayService (orchestrates ingestion, replay, DNA, reporting)
│   ├── ingestion/
│   │   ├── validation.py         # TraceValidator (tenant isolation, hash-chain, sequence checks)
│   │   └── adapter.py            # TraceIngestionAdapter (event deduplication and trace assembly)
│   ├── forensics/
│   │   ├── timeline.py           # Deterministic timeline reconstruction (build_timeline)
│   │   ├── provenance.py         # ProvenanceGraph & evidence digest verification
│   │   └── anomalies.py          # Trace-level anomaly detector (merchant, amount, quote drift)
│   ├── timemachine/
│   │   ├── policies.py           # CounterfactualPolicy specification model
│   │   ├── replay.py             # PolicyTimeMachine (deterministic re-evaluation with side-effect blocks)
│   │   ├── comparison.py         # PolicyComparisonReport (matrix evaluation)
│   │   └── recommendations.py    # Safeguard recommendations generation
│   ├── agentdna/
│   │   ├── features.py           # AgentFeatureVector extraction (with strict data leakage cutoff)
│   │   ├── profiles.py           # AgentBehaviorProfile builder & metric aggregation
│   │   ├── detector.py           # AgentDNADetector (velocity, amount, merchant novelty, denial rate)
│   │   └── explanations.py       # Human-interpretable explanation formatting
│   ├── integrations/
│   │   ├── guardian.py           # GuardianTraceAdapter (maps Guardian artifacts into PaymentTrace)
│   │   └── disputeos.py          # DisputeOSEvidenceBundle export for DisputeOS case files
│   └── api/
│       ├── models.py             # IngestTraceRequest, ReplayCompareRequest, AnalyzeAgentRequest
│       └── router.py             # FastAPI APIRouter (prefix="/ghostpay")
├── tests/
│   ├── conftest.py               # Fixtures, test harnesses, and baseline generators
│   ├── test_agent_dna.py         # Scenarios T14 - T20 (Agent DNA verification)
│   ├── test_ghostpay.py          # Legacy compatibility scenarios 1 - 10
│   ├── test_ghostpay_api.py      # FastAPI route verification (direct synchronous test execution)
│   ├── test_ingestion.py         # Scenarios T01 - T06 (Ingestion, deduplication, tamper detection)
│   ├── test_integrations.py      # DisputeOS export, provider safety, Guardian adapter
│   ├── test_security.py          # Tenant isolation, zero side-effects, 12-adversarial-scenario matrix
│   ├── test_time_machine.py      # Scenarios T07 - T13 (Policy Time Machine evaluation)
│   └── test_timeline.py          # Timeline reconstruction and provenance graph
├── README.md                     # Architecture, Threat Model, API, and Runbook
└── pyproject.toml                # name = "agentpay-ghostpay", workspace dependency definitions
```

---

## 3. Threat Model & Security Boundaries

### Non-Negotiable Invariants

1. **Zero Financial Side Effects (`executed_payment = False`):**
   `PolicyTimeMachine` and `GhostPayService` are structurally incapable of mutating financial ledger state. Methods attempting payment capture (`capture_payment`), budget holds (`reserve_budget`), or reservation releases (`release_reservation`) raise `IllegalSideEffectError`. All replay outputs hardcode `executed_payment = False`.
2. **Deterministic Governance Only:**
   Policy re-evaluation uses exact arithmetic and Boolean rules identical to Guardian's deterministic engine. No Large Language Model (LLM) or neural network ever participates in authorization decisions.
3. **No Agent DNA Authority Over Decisions:**
   Agent DNA produces statistical behavioral anomaly indicators (`NORMAL`, `ANOMALY_DETECTED`, `INSUFFICIENT_HISTORY`). Every Agent DNA report includes the immutable notice:
   > *"Authorization: No change. Guardian remains authoritative."*
4. **Tenant Isolation:**
   Every API endpoint, service method, and trace adapter validates `tenant_id` boundaries. Ingesting traces, fetching timelines, running counterfactual simulations, or viewing investigations across tenant IDs immediately fails with `CrossTenantAccessError` / `TenantIsolationError` (HTTP 403).
5. **No Data Leakage in Historical Baselines:**
   When constructing an agent baseline profile, any trace with timestamp $\ge$ the target transaction's timestamp or matching the target transaction ID is strictly excluded. The target transaction cannot participate in its own baseline.
6. **Cryptographic Provenance Guarantees:**
   - Financial event hash-chains are validated using SHA-256 HMAC linkage (`event_hash` depends on `previous_event_hash`, `occurred_at_iso`, and `payload`).
   - Evidence records verify cryptographic content digests against canonical payload digests.
   - Any broken link, tampered hash, or missing sequence flags the trace status as `TAMPERED`, `INCOMPLETE`, or `CONFLICTING`.

---

## 4. Feature Reference

### Policy Time Machine

Reconstructs historical authorization states and re-evaluates decisions against hypothetical policy adjustments.

- **Supported Overrides (`CounterfactualPolicy`):**
  - `per_tx_limit_minor`: Transaction spending limit in minor units (e.g., cents).
  - `total_budget_minor`: Maximum total allowable budget.
  - `daily_limit_minor`: Daily spending velocity threshold.
  - `human_approval_threshold_minor`: Escalation threshold requiring human sign-off.
  - `allowed_merchant_ids`: Allowlisted merchant UUID collection.
  - `allowed_categories`: Allowlisted merchant categories.
  - `allow_unknown_merchants`: Boolean policy switch for unlisted merchants.
  - `passport_status`: Status override (`ACTIVE`, `SUSPENDED`, `REVOKED`, `EXPIRED`).
  - `expires_at`: Passport expiration override.
  - `amount_override_minor`: Counterfactual transaction amount.
  - `merchant_override`: Counterfactual merchant identity.
- **Drift Detection:**
  Detects when a historical `ALLOW` flips to `DENY` (or vice-versa), identifies specific violated constraints, and generates safeguard recommendations (e.g., `"Lower per-tx limit to $25.00"`).

### Agent DNA

Builds statistical profiles of autonomous purchasing agents to distinguish normal operational patterns from compromised or hallucinated agent behavior.

- **Feature Vectors:**
  - `mean_amount_minor`, `max_amount_minor`, `amount_variance`: Expenditure statistics.
  - `transaction_count`: Historical observation volume.
  - `known_merchants`, `known_categories`: Entity familiarity sets.
  - `hourly_frequency`: Time-of-day purchase distribution.
  - `denial_rate`: Historical authorization rejection ratio.
- **Detection Heuristics:**
  - **Amount Spikes:** Transaction amount exceeding $\mu + 3\sigma$ (or $> 2.0\times$ historical maximum).
  - **Merchant Novelty:** Interaction with a merchant not present in the agent's baseline history.
  - **Denial Velocity:** Elevated denial frequency (> 30% of recent attempts denied).
  - **Cold-Start Handling:** Agents with fewer than `min_samples = 3` transactions return status `INSUFFICIENT_HISTORY` with zero false-positive anomaly score.

### Forensic Investigations & DisputeOS Integration

- **Timeline Reconstruction:**
  Merges `FinancialEvent` sequences and `EvidenceRecord` entries into a single chronological timeline sorted by `(sequence_number, occurred_at)`.
- **Structured Findings:**
  Every `InvestigationReport` strictly categorizes findings into:
  - `verified_facts`: Cryptographically verified events and receipts.
  - `deterministic_policy_outcomes`: Concrete policy rule evaluations.
  - `statistical_anomaly_signals`: Agent DNA baseline indicators.
  - `ai_explanations`: Contextual natural language explanations.
- **DisputeOS Evidence Bundle:**
  Exports a self-contained `DisputeOSEvidenceBundle` containing verified PayPal capture receipts, quote snapshots, timeline stages, and digital signatures ready for dispute filing.

---

## 5. API Reference

All routes are mounted under the `/ghostpay` prefix.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/ghostpay/health` | Service health status. |
| `POST` | `/ghostpay/traces/ingest` | Ingest and validate a financial payment trace. |
| `GET` | `/ghostpay/traces/{trace_id}` | Retrieve normalized trace by UUID. |
| `GET` | `/ghostpay/traces/{trace_id}/timeline` | Retrieve chronological timeline for trace. |
| `POST` | `/ghostpay/replay` | Deterministically replay a transaction. |
| `POST` | `/ghostpay/replay/compare` | Evaluate multiple counterfactual policies against a trace. |
| `POST` | `/ghostpay/simulate` | Simulate counterfactual policy on a `ReplayRequest`. |
| `POST` | `/ghostpay/timeline` | Standalone timeline reconstruction from raw events. |
| `GET` | `/ghostpay/agents/{agent_id}/profile` | Retrieve historical Agent DNA profile. |
| `POST` | `/ghostpay/agents/{agent_id}/analyze` | Perform statistical anomaly detection for target trace. |
| `POST` | `/ghostpay/investigations` | Generate comprehensive investigation report. |
| `GET` | `/ghostpay/investigations/{id}` | Retrieve existing investigation report. |
| `GET` | `/ghostpay/investigations/{id}/evidence` | Export `DisputeOSEvidenceBundle` for DisputeOS. |

### Sample Request: Counterfactual Policy Simulation (`POST /ghostpay/simulate`)

```json
{
  "request": {
    "tenant_id": "00000000-0000-4000-8000-000000000001",
    "correlation_id": "aaaa1111-1111-4000-8000-000000000001",
    "payment_intent": { ... },
    "proposal": { ... },
    "quote_snapshot": { ... },
    "recorded_passport": { ... },
    "recorded_merchant": { ... },
    "recorded_decision": { ... },
    "events": [ ... ],
    "evidence_records": [ ... ]
  },
  "overrides": {
    "per_tx_limit_minor": 1000
  }
}
```

### Sample Response: Replay Result

```json
{
  "request_id": "c1f7b7f1-7980-451e-af54-d0324bd8a9d1",
  "payment_intent_id": "aaaa4444-4444-4000-8000-000000000001",
  "original_outcome": "ALLOW",
  "recomputed_outcome": "DENY",
  "recomputed_reason_codes": [
    "DENIED_EXCEEDS_PER_TX_LIMIT"
  ],
  "drift_detected": true,
  "changed_constraints": [
    "recomputed_outcome: ALLOW -> DENY",
    "per_tx_limit_minor: 7500 -> 1000"
  ],
  "consistency_status": "DRIFT_DETECTED",
  "executed_payment": false,
  "timeline": [ ... ]
}
```

---

## 6. Verification & Test Suite

The test suite covers all 20 mandatory scenarios:

### Ingestion & Integrity Scenarios
- **T01:** Valid Guardian event stream reconstructs expected timeline.
- **T02:** Tampered financial event is rejected or quarantined.
- **T03:** Duplicate identical event ingestion is idempotent.
- **T04:** Conflicting duplicate event produces `IntegrityError`.
- **T05:** Missing event sequence number is explicitly detected.
- **T06:** Cross-tenant trace access is strictly denied (`CrossTenantAccessError`).

### Policy Time Machine Scenarios
- **T07:** Original allowed purchase becomes denied under stricter per-tx limit.
- **T08:** Merchant substitution is rejected under alternative allowlist.
- **T09:** Lowered approval threshold triggers human escalation requirement.
- **T10:** Missing historical budget state returns `INCOMPLETE_EVIDENCE`.
- **T11:** Replaying identical trace and policy produces 100% deterministic results.
- **T12:** Replay engine cannot invoke PayPal capture, reserve budget, or mutate state.
- **T13:** Multi-policy comparison matrix produces independent evaluations.

### Agent DNA Scenarios
- **T14:** Stable historical purchasing behavior produces normal profile (`is_anomaly = False`).
- **T15:** Previously unseen merchant produces merchant novelty anomaly signal.
- **T16:** Abnormally large transaction produces amount deviation signal ($\mu + 3\sigma$).
- **T17:** Repeated denied attempts produce behavioral velocity anomaly.
- **T18:** Insufficient historical observations return `INSUFFICIENT_HISTORY` (cold start).
- **T19:** Evaluated transaction is strictly excluded from its own baseline.
- **T20:** Agent DNA anomaly score never alters Guardian's authoritative decision.

### Execution Command

```powershell
uv run pytest modules/ghostpay/tests -v
```

---

## 7. Known Limitations & Future Roadmap

1. **In-Memory History Cache:**  
   The current prototype stores baseline traces in a tenant-partitioned memory cache (`GhostPayService.agent_history`). In Milestone G2, this will persist to PostgreSQL via `packages/database/` using tenant-scoped indexes.
2. **Cold Start Heuristics:**  
   The `min_samples = 3` threshold prevents false positives for new agents. Future releases will introduce organization-level peer baselines for zero-shot anomaly detection.
3. **DisputeOS Automated Feedback:**  
   Dispute settlement webhooks from PayPal will feed back into GhostPay to continuously refine counterfactual risk scoring.
