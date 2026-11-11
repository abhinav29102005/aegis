# GhostPay (`modules/ghostpay/`)

**Branch:** `feature/ghostpay`
**Status:** Implemented and Verified (Forensic and Simulation Engine for AgentPay Nexus)

## Overview
GhostPay provides deterministic authorization replay, what-if counterfactual policy simulation, anomaly detection, provenance verification, and deterministic event timeline reconstruction for autonomous agent spending.

## Core Responsibilities & Components
```text
modules/ghostpay/
├── ghostpay/
│   ├── __init__.py
│   ├── replay/          # Deterministic policy & authorization replay engine (`ReplayEngine`)
│   ├── counterfactual/  # Non-mutating counterfactual policy simulation (`simulate_counterfactual`)
│   ├── anomalies/       # Authorization drift & anomaly detection (merchant substitution, amount spike, expired passport, quote mismatch)
│   ├── provenance/      # Evidence completeness & hash-chain/content-hash integrity verification
│   ├── timelines/       # Deterministic event timeline reconstruction (`build_timeline`)
│   └── api/             # FastAPI APIRouter (`prefix="/ghostpay"`, `create_ghostpay_router(...)` + `router`)
├── tests/               # 10 mandatory forensics & determinism scenarios + API tests
├── README.md
└── pyproject.toml
```

## Forensic & Determinism Invariants
1. **Replay Contract**: `ReplayEngine.replay(request: ReplayRequest) -> ReplayResult` deterministically reconstructs `timeline`, `original_outcome`, `recomputed_outcome`, `original_reason_codes`, `recomputed_reason_codes`, `changed_constraints`, `drift_detected`, `explanation`, `evidence_references`, `missing_evidence`, `anomalies`, `integrity_valid`, `consistency_status` (`CONSISTENT`, `DRIFT_DETECTED`, `INTEGRITY_FAILURE`, `INCOMPLETE_EVIDENCE`), and `executed_payment=False`.
2. **Deterministic Rules Only**: Recomputing authorization outcomes is 100% deterministic without delegating decisions to an LLM or fabricating missing evidence.
3. **Read-Only Guarantee**: Counterfactual overrides (`per_tx_limit_minor`, `total_budget_minor`, `allowed_merchant_ids`, `allow_unknown_merchants`, `human_approval_threshold_minor`, `passport_status`, `expires_at`, `merchant_override`, `amount_override_minor`) operate on isolated copies and NEVER mutate `request` or trigger payments (`executed_payment=False`).
4. **Integrity & Tenant Security**:
   - Multi-tenant isolation is strictly enforced via `assert_same_tenant` across all nested entities, raising `TenantIsolationError` on cross-tenant access.
   - Event hash chains are verified via `verify_financial_event_chain`, and evidence digests are verified via `compute_payload_hash`. Tampered records produce `integrity_valid=False` and `consistency_status="INTEGRITY_FAILURE"`.
   - Timeline events are deterministically sorted by `(sequence_number, occurred_at, str(id))`.
   - Missing required artifacts (`QUOTE`, `POLICY_DECISION`, `PAYPAL_CAPTURE` when `SUCCEEDED`) are reported explicitly in `missing_evidence` (`INCOMPLETE_EVIDENCE`).

## Mandatory Test Suite (`tests/`)
1. Identical inputs and policy version produce identical results (`CONSISTENT`).
2. Merchant substitution changes authorization outcome (`DRIFT_DETECTED`).
3. Amount increase above limit changes authorization outcome (`DRIFT_DETECTED`).
4. Expired passport prevents eligibility (`DENY`, `DENIED_PASSPORT_EXPIRED`).
5. Counterfactual policies do not mutate original records (`executed_payment=False`).
6. Missing evidence is explicitly reported (`missing_evidence` populated, `INCOMPLETE_EVIDENCE`).
7. Event ordering is deterministic even when input `events` are shuffled.
8. Cross-tenant evidence/record access is denied (`TenantIsolationError`).
9. Tampered event or evidence records fail integrity checks (`integrity_valid=False`, `INTEGRITY_FAILURE`).
10. Replay does not trigger payment execution (`executed_payment=False`).

## Running Verification & Tests
```bash
# Run pytest on ghostpay tests
PYTHONPATH=modules/ghostpay uv run pytest modules/ghostpay/tests -v

# Run ruff check on ghostpay
uv run ruff check modules/ghostpay
```
