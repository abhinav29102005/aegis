# 03 — GhostPay Forensic Reliability Audit

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):** **UNIFIED POLICY PARITY (`1000/1000`), PG-BACKED SNAPSHOT/TRACE/DNA PERSISTENCE, AND FULL-LAYER RBAC COMPLETE & VERIFIED.**  
**Scope:** `modules/ghostpay/`, `services/api/aegis_api/adapters.py`, `packages/contracts/contracts/policy_v1.py`, `packages/database/`, `apps/web/src/app/ghostpay/`.

---

## 1. Resolution Matrix Across All Baseline & Sync Findings

| Component / Finding | Baseline (`1be376e`) | Integrated Status (`2026-11-12`) | Verified Evidence |
| :--- | :--- | :--- | :--- |
| **RBAC on `/v1/ghostpay/*` (`GAP-002`)** | **MISSING (`CRITICAL`)** | **CLOSED (GATEWAY + ROUTER)** | Gateway `app.py` wires `Permission.GHOSTPAY_READ`; internal `modules/ghostpay/ghostpay/api/router.py` enforces per-endpoint `GHOSTPAY_READ` / `GHOSTPAY_SIMULATE`; `test_rbac_negative_matrix.py` + `test_ghostpay_api.py` + `test_gateway_and_rate_limit.py` PASS. |
| **Legacy `timemachine/replay.py` & `forensics/*` Split-Brain (`GAP-013`)** | 2 conflicting replay/anomaly paths + volatile RAM stores | **CLOSED** | `3bbaeb6` deleted `ghostpay/timemachine/replay.py`, `forensics/{anomalies,provenance,timeline}.py`; `ReplayEngine` + `ProvenanceVerifier` + `anomalies/detector.py` are single canonical implementations. |
| **PG Backing for Snapshots, Traces, Investigations & Agent DNA (`GAP-013`)** | Process-RAM stores + naive subtraction | **CLOSED & VERIFIED** | M1 added `spending_passport_snapshots`, `ghostpay_traces`, `ghostpay_agent_dna_profiles` (`0003`); M2 wired `adapters.py` (`get_passport_snapshot_for_decision`, `save_ghostpay_trace`, `save_agent_dna_profile`) and GhostPay router (`GhostPayTraceAndDnaRepository`) into durable PG storage (`test_forensics_hardening.py`). |
| **`"policy-v1"` Semantic Parity (`GAP-011`)** | Guardian vs GhostPay diverged on boundaries | **CLOSED & VERIFIED** | Both modules execute canonical `contracts.policy_v1.evaluate_policy_v1`; **1,000-case property test (`test_forensics_hardening.py`) passed `1000/1000` (`0` mismatches)**! |
| **Partial Digest Cascade & False Positive Anomalies (`GAP-013`)** | 7-way 2-field digest; `DENY` flagged anomalous | **CLOSED & VERIFIED** | `ProvenanceVerifier` validates full canonical hashes across all chain nodes; canonical `evidence` hash in `adapters.py:761` (`compute_payload_hash`) verified across unit & E2E tests (`test_forensics_hardening.py`, `test_sdk_coverage.py`). |
| **Frontend Timeline & SDKs (`GAP-004`/`015`)** | UI fields `undefined`; missing GhostPay ops | **CLOSED & VERIFIED** | Next.js `/ghostpay` & `/ghostpay/replay/[id]` match canonical schema (`occurred_at`, `actor_type`, `actor_id`, `previous_event_hash`); Python & TS SDKs wrap `/v1/ghostpay/{health,traces,replay,counterfactual,simulate,agents,investigations}` cleanly (`98.0%` parity). |

---

## 2. Independent Investigator Question
> **"Can an independent investigator reconstruct why a financial decision occurred using only preserved records and documented policy versions?"**

**Current Answer (`2026-11-12` Integrated): YES (Verified on Local PG16 + Synthetic/Mocked Runs).**  
Every authorization records an immutable `spending_passport_snapshots` row (`0003`), every `FinancialEvent` is protected against `UPDATE`/`DELETE` at the PostgreSQL trigger layer (`trg_aegis_prevent_financial_event_mutation`), `GhostPay` shares the exact pure `contracts.policy_v1.evaluate_policy_v1` evaluator with Guardian (`1,000/1,000` zero-mismatch verified), traces/DNA/investigations persist across API restarts in PostgreSQL, and gateway + method-level RBAC prevents unauthorized access. Live multi-month production volume replay remains unbenchmarked (`NOT VERIFIED`).
