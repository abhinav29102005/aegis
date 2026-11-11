# 03 — GhostPay Forensic Reliability Audit

**Scope:** `modules/ghostpay/` (all submodules & 10 test suites), `services/api/aegis_api/adapters.py`, `services/api/aegis_api/app.py:152-155`, `packages/database/database/repository.py`

---

## 1. Key Capabilities & Persistence Architecture Audit

| Component / Route | Implementation Status | Storage Backend | Findings Summary |
| :--- | :--- | :--- | :--- |
| Hardened `ReplayEngine` (`/replay`, `/simulate`, `/counterfactual`, `*-by-payment/*`) | **PARTIALLY IMPLEMENTED** | Stateless / PostgreSQL (`adapters.py`) | Strict override validator (`extra="forbid"`, tenant check), `executed_payment=False`, fail-closed policy version registry (`policy-v1` only). Diverges semantically from Guardian! |
| Legacy `PolicyTimeMachine` (`/replay/compare`, `POST /investigations`) | **PARTIALLY IMPLEMENTED (RISKY)** | Process RAM (`_IN_MEMORY` / `svc`) | Still wired into live router (`router.py:306,456`); unhardened `model_copy`, ignores `policy_version`, breaks `"currency"` key (`policies.py:50` vs `currency_override`). |
| Trace Ingestion & Agent DNA (`/traces/*`, `/agents/{id}/profile|analyze`) | **PARTIALLY IMPLEMENTED (NON-DURABLE)** | **In-Memory Only** (`GhostPayService`) | Lost on restart; repeats inflate `agent_history`; training window leaks future timestamps; missing cross-entity tenant checks in `ingestion/validation.py:23-49`. |
| Forensic Investigations (`GET` vs `POST /investigations`) | **BROKEN SPLIT-BRAIN** | `GET` = PostgreSQL; `POST` = RAM | `POST /investigations` writes to RAM; `GET /investigations` reads `ghostpay_investigations` table and **never sees `POST` items**! |
| RBAC Enforcement on `/v1/ghostpay/*` | **MISSING (`CRITICAL`)** | N/A | `aegis_api/app.py:152-155` passes `require_tenant_id` (auth only) instead of `require_permission(Permission.GHOSTPAY_READ/SIMULATE)`. |

---

## 2. Independent Investigator Question
> **"Can an independent investigator reconstruct why a financial decision occurred using only preserved records and documented policy versions?"**

**Answer: NO** — an independent investigator can **only** rely on GhostPay when handed an explicit, unmodified synthetic `ReplayRequest` payload matching GhostPay's narrow rules. Across live DB-persisted transactions (`*-by-payment/*`), reconstruction fails or can lie for five concrete reasons:

### Reason 1 — `"policy-v1"` Semantic Divergence Between Guardian and Both GhostPay Evaluators (`CRITICAL`)
| Rule | Guardian `PolicyEngine.evaluate` (`guardian/policies/engine.py`) | GhostPay Hardened (`ghostpay/replay/engine.py`) | GhostPay Legacy (`ghostpay/timemachine/replay.py`) |
| :--- | :--- | :--- | :--- |
| Human approval threshold | `amount_minor > threshold` (`L129`) | **`>= threshold` (`L108`)** | `> threshold` (`L105`) |
| Daily spend limit | **Ignored (`0` checks)** | Enforced against single tx (`L78-79`) | Enforced against single tx (`L78-80`) |
| Global `merchant.is_allowlisted` | Allowed even if not in passport list (`L110-112`) | **Ignored** (only checks passport ID list `L85`) | Allowed if in either |
| `quote.expires_at` & Currency | Enforced (`L65-70, L89-90`) | **Ignored** | Ignored |
| `allowed_categories` matching | `merchant.category` only (`L122`) | `merchant` **OR** `proposal` missing (`or` `L96-100`) | `and` (`L97`) — passes if one matches! |
| Inactive passport code | Distingushes `EXPIRED` vs `REVOKED`/`PAUSED` (`L73-77`) | Collapses all to `DENIED_AGENT_SUSPENDED` (`L55-56`) | Collapses |

Result: Boundary transactions can pass in Guardian and falsely trigger `AUTHORIZATION_DRIFT` under GhostPay `"policy-v1"`, or vice versa.

### Reason 2 — Mutable In-Place Passport State & Lossy Balance Reconstruction (`HIGH`)
- `LedgerRepository.update_passport_policy` (`packages/database/database/repository.py:228-260`) overwrites `SpendingPassportRow` in place (limits, threshold, allowlists, `status = REVOKED`) with **no immutable `spending_passport_snapshots` history table**. Replaying a month-old payment after revoking a passport or tightening limits evaluates it against *today's* passport!
- `SqlAlchemyGhostPayRepository._build_replay_request` (`services/api/aegis_api/adapters.py:89-104`) tries to roll back `spent_minor` and `reserved_minor` by subtracting *only the target intent's own amount*. Any concurrent/subsequent transactions remain baked into `spent_minor`, causing false insufficient-budget drift on historical replays. Notice `AuthorizationDecision.policy_inputs` (`repository` / `orm`) exists in schema yet `adapters.py` fails to restore the full decision-time snapshot from it.

### Reason 3 — Evidence Digest Cascading & Unverified Provider Records (`HIGH`)
- `verify_evidence_digest` (`modules/ghostpay/ghostpay/provenance/verifier.py:22-71`) uses a 7-way fallback cascade accepting partial 2-field hashes (e.g., `{quote_hash, amount_minor}` for `QUOTE`, leaving `currency`/`merchant_id`/`line_items` inside `ev.content` unhashed and mutable without failing digest check).
- Neither `provenance/verifier.py` nor legacy `forensics/provenance.py` cross-checks `PaymentAttempt`, `PayPal` capture verification hashes (`VerifiedPayPalCapture`), `BudgetReservation`, or `FinancialEvent.payload` values against the actual `PaymentIntent`/`AuthorizationDecision` fields.
- Legacy `forensics/provenance.py:218-222` fails to enforce `ev.correlation_id == request.correlation_id`.

### Reason 4 — Synthetic Payload Fabrication & Event Sorting Divergence (`HIGH`)
- `PaymentTrace.to_replay_request` (`ghostpay/domain/models.py:75-111`) synthesizes fake `PurchaseProposal` (`reconstructed-{trace_id}`) and `PaymentIntent` (`CREATED`) objects when missing instead of failing closed (`INSUFFICIENT_EVIDENCE` is only emitted in `PolicyTimeMachine.replay_trace` for missing budget).
- Legacy `forensics/timeline.py:126` sorts by `(occurred_at, sequence_number)`, rewrites `sequence_number = idx` (hiding gaps), and compares hashes via `==` instead of `hmac.compare_digest` — while hardened `timelines/builder.py` & `security/hashing.py` sort by `(sequence_number, occurred_at, str(id))`.

### Reason 5 — Disconnected Anomaly Rules & False Positives (`HIGH`)
- `timemachine/recommendations.py` maps legacy codes (`"HIGH_RISK_AMOUNT"`, `"UNCERTAIN_PROVIDER_STATE"`), while hardened `anomalies/detector.py` emits `MERCHANT_SUBSTITUTION`, `AMOUNT_SPIKE`, `EXPIRED_PASSPORT`, etc. — so recommendations never trigger on hardened anomaly results!
- `anomalies/detector.py:44,50-57,60-71` does not check whether the transaction was already `DENY` in `recorded_decision`, flagging legitimately denied policy blocks as security anomalies (high false-positive rate).

---

## 3. Missing Hardening & Remediation Priority
1. **P0 — Enforce GhostPay RBAC** (`Permission.GHOSTPAY_READ`, `Permission.GHOSTPAY_SIMULATE`) in `services/api/aegis_api/app.py:152-155` & `router.py`.
2. **P0 — Delete legacy split engines**: Remove `PolicyTimeMachine.replay`, `forensics/{provenance,timeline,anomalies}.py` duplicates; route `/replay/compare` and `/investigations` through hardened `ReplayEngine` + `validate_tenant_isolation` + PostgreSQL `PlatformRepository`.
3. **P1 — Unify `"policy-v1"`**: Extract a single shared pure evaluator function in a shared contract/policy package (or Guardian/GhostPay shared module) and persist full immutable `policy_inputs` / `spending_passport_snapshots` at decision time so `adapters.py` never guesses balances.
4. **P1 — Harden provenance & Agent DNA**: Remove 2-field partial digest fallbacks (`provenance/verifier.py`), persist traces/Agent DNA in PostgreSQL with idempotent `trace_id` dedup and proper cutoff filtering on window metadata (`agentdna/profiles.py:64-70`).

