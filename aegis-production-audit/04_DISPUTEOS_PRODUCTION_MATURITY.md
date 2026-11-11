# 04 — DisputeOS Production Maturity Audit

**Scope:** `modules/disputeos/`, `services/api/aegis_api/routers/disputeos_db.py`, `webhooks.py`, `packages/database/database/{orm.py,repository.py,storage.py}`, `packages/paypal/paypal/client.py`

---

## 1. Merchant Dispute Operations Readiness Verdict
**Verdict: NOT READY FOR A MERCHANT'S DISPUTE OPERATIONS TEAM.**

While DisputeOS implements strong conceptual safety primitives — deterministic citation checks against existing `EvidenceRecord` excerpts, missing-evidence checklists, `is_synthetic` submission blocking (`SyntheticSubmissionError -> 403`), `LocalObjectStorage` SHA-256 verification, and fail-closed `PAYPAL_DISPUTES_API_ENABLED` gating — **it does not transmit dispute responses to PayPal**, **lacks PayPal webhook ingestion and dispute deadlines/SLAs**, **permits invalid backward state regressions**, **omits any real LLM provider**, and **has broken evidence analysis rendering in the UI**.

---

## 2. Subsystem Evaluation & Evidence

### 2.1 Case Persistence & State Transitions (`HIGH`)
- **Dual routers:** `services/api/aegis_api/routers/disputeos_db.py` (mounted in unified API) is PostgreSQL-backed (`LedgerRepository`, `PlatformRepository`, `LocalObjectStorage`), whereas `modules/disputeos/disputeos/api/router.py` uses purely in-memory dicts and trusts unauthenticated `X-Tenant-Id` + spoofable `payload.approver_id` (`L325`).
- **Silent field drop on DB update (`packages/database/database/repository.py:858-893`):** `LedgerRepository.save_dispute_case` updates status/timestamps on existing rows but silently ignores changes to `paypal_dispute_id`, `reason`, `buyer_claim`, `amount_minor`, `is_synthetic`, or `source_type`. `save_evidence` (`L817-838`) drops updates to existing evidence records.
- **No `DisputeStatus` state machine guard (`modules/disputeos/disputeos/cases/service.py:236,358`):** `record_analysis` unconditionally sets `case.status = DisputeStatus.DRAFT_READY` even if the case is already `APPROVED_FOR_SUBMISSION`, `SUBMITTED`, or `RESOLVED`. `approve_for_submission` and `attach_evidence` also allow mutations on `SUBMITTED`/`RESOLVED` cases. `DisputeStatus.UNDER_INVESTIGATION` (`enums.py:167`) is dead/unused, and `mark_resolved` (`service.py:358`) has **no HTTP endpoint** in either router.
- **Partial FinancialEvent trail (`cases/service.py:114-131,182,240,306,353`):** `create_case`, `record_analysis`, and `approve_for_submission` emit hash-chained `FinancialEvent`s, whereas `attach_evidence`, `mark_submitted`, and `mark_resolved` emit **none**.

### 2.2 Deadlines, SLA Management & PayPal Webhook Sync (`HIGH` — `MISSING`)
- **Zero deadline tracking:** Neither `DisputeCase` (`contracts/models.py:476-506`), `DisputeCaseRow` (`orm.py:276-298`), nor `DisputeCaseMetadataRow` (`orm.py:455-465`) stores `response_due_by`, `seller_response_due_date`, or SLA escalation timers. In real PayPal/card disputes, missing the response deadline (`reply_by_date`) causes automatic loss of the claim.
- **No dispute webhook ingestion:** `services/api/aegis_api/routers/webhooks.py:161-220` only correlates PayPal webhooks against `PaymentAttemptRow` via `paypal_order_id` and ignores `CUSTOMER.DISPUTE.CREATED`, `CUSTOMER.DISPUTE.UPDATED`, and `CUSTOMER.DISPUTE.RESOLVED`.

### 2.3 Evidence Chain of Custody, Storage & Binding (`HIGH`)
- **Artifact cross-case IDOR within tenant (`services/api/aegis_api/routers/disputeos_db.py:267-362`):** `download_evidence_artifact` verifies `auth.tenant_id` on both `case_id` and `artifact_id`, **but never verifies `artifact.evidence_record_id` belongs to `case_id`**.
- **Incomplete `content_hash` scope (`modules/disputeos/disputeos/ingestion/normalizer.py:23-35,62-77`):** Hashes only `{source_type, source_ref, title, content}`, excluding `tenant_id`, `dispute_case_id`, `correlation_id`, `is_synthetic`, and `collected_at`. If a caller supplies a pre-populated `content_hash`, `normalize_evidence_record` accepts it without recomputing/verifying (`L62-77`), and downstream graph/detector/analyzer code never re-verifies `content_hash`.
- **Unenforced `retention_until` (`orm.py:464`, `platform_repo.py:444`):** Sets `+2555` days (~7 years) at upload, never enforces retention expiry, holds, or GDPR deletion. Artifacts are written directly into RAM via `await file.read()` (`disputeos_db.py:281-285`) before size check (`10 MB` cap).

### 2.4 Evidence Graph, Contradictions & LLM Grounding (`HIGH`)
- **Over-connected evidence graph (`modules/disputeos/disputeos/evidence/graph.py:82-98`):** Connects every node in stage `i` to every node in next present stage `i+1` (Cartesian product) regardless of `payment_intent_id`, timestamps, or causality.
- **Narrow rule-based detection (`modules/disputeos/disputeos/evidence/detector.py:116-120`):** Only detects missing tracking/delivery on 4 literal reason substrings (`NOT_RECEIVED`, `NOT RECEIVED`, `DELIVERY`, `MERCHANDISE`) and checks only 3 contradiction heuristics (tracking `DELIVERED` vs buyer message keywords; quote/capture amount vs case amount; `POLICY_DECISION=DENY` vs capture). Does not validate card AVS/CVV, IP/device telemetry, subscription cancellation proofs, or `SIGNIFICANTLY_NOT_AS_DESCRIBED` evidence packets.
- **No real LLM client exists (`analyzer.py`, `pyproject.toml`):** `DisputeAnalyzer` defaults to `llm_reviewer=None` (regex + template strings). Injected test fakes verify behavior if a custom `LLMReviewerProtocol` is passed, **no OpenAI or Google Gemini integration exists anywhere in `modules/disputeos/`**.
- **Bypassable `CitationValidator` & `llm_summary` (`citations.py:70-75`, `analyzer.py:378-401`):** `CitationValidator` checks only substring containment (`excerpt.lower() in searchable.lower()`). An LLM citing `"USD"` or `"status"` can attach any fabricated claim narrative, and arbitrary `llm_summary` text passes unverified once `>= 1` candidate claim passes. (Conversely `draft_response_text` ignores `llm_summary` completely.)

### 2.5 PayPal Disputes v1 Submission Safety (`CRITICAL`)
- **Simulated submission marked as `SUBMITTED` (`disputeos/paypal/adapter.py:47-83`, `disputeos_db.py:510`):** `PayPalSandboxClient` (`packages/paypal/paypal/client.py:406-428`) only implements read-only `list_disputes()`. `DisputePayPalAdapter.submit_dispute_response` performs zero PayPal HTTP calls and returns `{"status": "APPROVED_PAYLOAD_READY", "submitted": False}`, yet `disputeos_db.py:510` calls `svc.mark_submitted(...)`, permanently transitioning the case to `DisputeStatus.SUBMITTED` without transmitting any evidence to PayPal!
- **Missing prerequisites (`disputeos_db.py`):** Submission does not require `case.paypal_dispute_id` to be present and has no idempotency key.

---

## 3. Remediation Requirements Before Merchant Operations Use
1. **P0 — Fix dishonest submission transition:** Refuse marking `DisputeStatus.SUBMITTED` unless PayPal `/v1/customer/disputes/{id}/provide-evidence` (or accept-claim) actually succeeds over HTTP; add PayPal `provide_evidence` / `accept_claim` client methods in `packages/paypal`.
2. **P1 — Enforce `DisputeStatus` state machine:** Reject backward transitions once `APPROVED_FOR_SUBMISSION`/`SUBMITTED`/`RESOLVED`; expose `POST /v1/disputeos/cases/{id}/resolve`; emit `FinancialEvent` on `attach_evidence`, `mark_submitted`, and `mark_resolved`.
3. **P1 — Add response deadlines & PayPal dispute webhook sync:** Parse `CUSTOMER.DISPUTE.*` webhooks in `webhooks.py`, persist `seller_response_due_date`, surface SLA countdowns/alerts in API & UI, and enforce artifact-to-case ownership in `download_evidence_artifact`.
4. **P1 — Fix UI schema contract & evidence integrity:** Include `tenant_id`, `dispute_case_id`, `is_synthetic` in `content_hash` with strict verification; build real provider-abstracted `LLMReviewer` adapters with claim-to-excerpt semantic alignment and token/prompt provenance logging; align `disputes/[id]/page.tsx` with `DisputeAnalysis`.

