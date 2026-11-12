# 04 — DisputeOS Production Maturity Audit

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **STORAGE, DEADLINE COLUMNS & PAYPAL WEBHOOK HOOK ADDED (`M1`); UI/SDK FIXED (`M3`); CORE DISPUTE SUBMISSION & REAL LLM BLOCKED ON COMPUTER 2 (`work/m2` UNPUSHED).**

---

## 1. Merchant Dispute Operations Readiness Verdict (`498043e`)
**Verdict: NOT READY FOR A MERCHANT'S DISPUTE OPERATIONS TEAM (Waiting on M2).**

- **Resolved in M1 + M3 Sync:**
  - `packages/database` (`repository.py`, `0003`): Fixed silent dropped updates in `save_dispute_case` and `save_evidence` (`GAP-020`); added `response_due_by`, `resolved_at`, `resolution_outcome`, `external_status` columns, `llm_invocation_logs`, `paypal_webhook_events`, streaming 10MB-capped uploads, S3/R2 WORM storage backend, and retention/GDPR erasure helpers.
  - `services/api/aegis_api/routers/webhooks.py` (`M1`): Added idempotent `record_paypal_webhook_once` and lazy dispatch hook for `CUSTOMER.DISPUTE.*` events calling `disputeos.paypal.webhook_handler.handle_paypal_dispute_webhook` cleanly when M2 lands.
  - `apps/web/src/app/disputes/` + `packages/sdk-*` (`M3`): Fixed `DisputeAnalysis` rendering (`grounded_summary`, `generated_with_llm`, `citations`, `contradictions`), added SLA countdown UI, non-synthetic `POST /cases`, `/resolve` modal, `/report` export button, and SDK methods.
  - **Prompt-Injection Test (`M3`):** `tests/adversarial/test_security_adversarial.py::test_prompt_injection_resistance_on_dispute_analyzer` PASSES against deterministic `DisputeAnalyzer`.
- **Remaining Blockers (Unchanged from Baseline — Waiting on M2):**
  1. **`GAP-009` (`CRITICAL`):** `DisputePayPalAdapter.submit_dispute_response` (`disputeos/paypal/adapter.py`) is still a local no-op while `disputeos_db.py:510` marks cases `DisputeStatus.SUBMITTED`. No live PayPal `POST /v1/customer/disputes/{id}/provide-evidence` call exists yet!
  2. **`GAP-017` (`HIGH`):** Missing monotonic `DisputeStatus` state guard, missing `POST /v1/disputeos/cases/{id}/resolve` endpoint, missing `artifact.evidence_record_id == case_id` check in `download_evidence_artifact` (`disputeos_db.py`), incomplete `normalizer.py` `content_hash`, Cartesian `evidence/graph.py`, narrow 4-substring `detector.py`, and missing `disputeos.paypal.webhook_handler`.
  3. **`GAP-019` (`P2`):** `DisputeAnalyzer` still has zero live OpenAI / Gemini / Anthropic `httpx` implementation (`LLM_PROVIDER=deterministic` only), and `CitationValidator` remains naive substring matching.
