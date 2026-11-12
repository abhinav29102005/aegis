# 03 — GhostPay Forensic Reliability Audit

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **GATEWAY RBAC & DB STORAGE READY (`M1`); CORE MODULE REFACTOR BLOCKED ON COMPUTER 2 (`work/m2` UNPUSHED).**  
**Scope:** `modules/ghostpay/`, `services/api/aegis_api/adapters.py`, `services/api/aegis_api/app.py` (M1), `packages/database/` (M1), `apps/web/src/app/ghostpay/` (M3).

---

## 1. What M1 + M3 Already Fixed vs What Awaits M2

| Component / Finding | Baseline (`1be376e`) | Current Status (`498043e`) | Evidence |
| :--- | :--- | :--- | :--- |
| **RBAC on `/v1/ghostpay/*` (`GAP-002`)** | **MISSING (`CRITICAL`)** | **FIXED AT API GATEWAY (`M1`)** *(Internal router RBAC still awaits M2)* | `services/api/aegis_api/app.py` enforces `require_permission(Permission.GHOSTPAY_READ)` on the mounted GhostPay router; M3's `test_rbac_negative_matrix` + M1's `test_gateway_and_rate_limit` verify `VIEWER`/`AGENT_SERVICE` receive `403`. *(Note: method-level `GHOSTPAY_SIMULATE` on simulate/ingest inside `ghostpay/api/router.py` awaits M2.)* |
| **PG Backing Tables for Traces, Agent DNA & Snapshots (`GAP-013`)** | Missing in ORM | **ADDED IN DB (`M1`)** | `packages/database` `0003` migration + `PlatformRepository`/`LedgerRepository` implement `spending_passport_snapshots`, `ghostpay_traces`, `ghostpay_agent_dna_profiles`, `save_passport_snapshot`, `get_passport_snapshot_for_decision`, `save_ghostpay_trace`, `list_ghostpay_traces`, `save_agent_dna_profile`, `get_agent_dna_profile` (verified by `test_platform_repo.py`). |
| **Frontend Timeline & Agent DNA UI (`GAP-004`/`022`)** | Timeline fields `undefined`; no DNA UI | **FIXED IN UI & SDKS (`M3`)** | `apps/web` `ghostpay` & `ghostpay/replay/[id]` updated to `occurred_at`, `actor_type`, `actor_id`, `previous_event_hash` + `POST /investigations` & Agent DNA panel; Python & TS SDKs wrap GhostPay endpoints. |
| **Legacy `timemachine/replay.py` & `forensics/*` Split-Brain (`GAP-013`)** | 2 conflicting engines + RAM `/traces` & `POST /investigations` | **STILL OPEN (`M2` UNPUSHED)** | `modules/ghostpay/` & `services/api/aegis_api/adapters.py` remain at `1be376e` — `POST /investigations`, `/traces/*`, `/agents/*` still write to process RAM and `adapters.py` still does naive balance subtraction without reading `spending_passport_snapshots`. |
| **`"policy-v1"` Semantic Divergence (`GAP-011`)** | Guardian vs GhostPay disagree | **STILL OPEN (`M2` UNPUSHED)** | Shared `contracts.policy_v1` not yet implemented. |
| **Partial Digest Cascade, Synthetic Fallback & Anomaly False Positives (`GAP-013`)** | 7-way 2-field digest cascade; synthetic intent fabrication; `DENY` anomalies | **STILL OPEN (`M2` UNPUSHED)** | `provenance/verifier.py`, `domain/models.py`, `anomalies/detector.py`, `agentdna/profiles.py` still unchanged. |

---

## 2. Independent Investigator Question
> **"Can an independent investigator reconstruct why a financial decision occurred using only preserved records and documented policy versions?"**

**Current Answer (`498043e`): STILL PARTIAL / NO (Waiting on M2).**  
M1 closed the BFLA security hole at the FastAPI router mount (`GAP-002`), added immutable `financial_events` PostgreSQL triggers (`GAP-020`), added `spending_passport_snapshots` + `ghostpay_traces` + `ghostpay_agent_dna_profiles` tables/repos (`0003`), and M3 repaired the GhostPay replay timeline UI & Agent DNA panel. **However**, until Computer 2 pushes `work/m2-financial-forensics-ai` to wire `adapters.py`/`ghostpay` into those snapshot/trace repos, retire legacy `timemachine/forensics`, and unify `"policy-v1"` with Guardian, live historical DB replays can still diverge on boundaries and restart loses RAM-backed traces/investigations.
