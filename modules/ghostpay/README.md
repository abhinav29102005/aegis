# GhostPay (`modules/ghostpay/`)

**Branch:** `feature/ghostpay`
**Status:** Ready for team implementation (frozen contracts and security hash-chain helpers already available in `packages/`).

## Responsibilities
- Deterministic transaction timeline reconstruction (`ghostpay/timelines/`)
- Deterministic policy & authorization replay engine (`ghostpay/replay/`)
- Counterfactual policy simulation without mutating original records (`ghostpay/counterfactual/`)
- Authorization drift & anomaly investigation (`ghostpay/anomalies/`)
- Evidence provenance & hash-chain integrity checks (`ghostpay/provenance/` via `security.verify_financial_event_chain`)
- FastAPI router (`ghostpay/api/` mounted at `/v1/ghostpay`)

## Required Tests (`tests/`)
1. Identical inputs and policy version produce identical results
2. Merchant substitution changes authorization outcome
3. Amount increase above limit changes authorization outcome
4. Expired passport prevents eligibility
5. Counterfactual policies do not mutate original records
6. Missing evidence is explicitly reported
7. Event ordering is deterministic
8. Cross-tenant evidence access is denied (`TenantIsolationError`)
9. Tampered records fail integrity checks
10. Replay does not trigger payment execution (`executed_payment=False`)

