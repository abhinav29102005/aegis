# GhostPay — Hackathon Delivery Plan

## Goal

Build a trustworthy, read-only forensic companion for AgentPay Nexus:

> Explain why an agent payment was authorized, detect evidence tampering and policy drift, and show what a different policy would have changed.

This plan uses staged implementation, explicit trust boundaries, adversarial acceptance checks, evidence-led presentation, and a short demo structure. GhostPay remains a read-only forensic module. This is a proposed plan, not a claim that the acceptance criteria below already pass.

## Scope and ownership

GhostPay owns `modules/ghostpay/ghostpay/{replay,counterfactual,anomalies,provenance,timelines,api}` and its tests/documentation.

Guardian owns purchasing authorization, approvals, budgets, and payment orchestration. Shared teams own database infrastructure, the unified API/worker, and the dashboard. GhostPay supplies its router, integration interface, result contracts, fixtures, and presentation requirements to those teams.

Sandbox connection is deferred. Develop against clearly labeled synthetic records now; later consume verified Sandbox records supplied through the shared ledger. GhostPay must never create an order, capture a payment, change a budget, or reconcile provider state itself.

## Current verified baseline

- Replay, simulation, anomaly detection, provenance verification, timelines, and FastAPI routes exist.
- All 15 existing GhostPay tests passed during review.
- After pulling Guardian, 53 repository tests passed with `pytest --import-mode=importlib -q`.
- Ordinary combined pytest collection fails because module test packages collide; Guardian also has lint failures. These are repository integration issues, not evidence that GhostPay's 15 tests fail.
- GhostPay workspace/test-discovery/Makefile/lint wiring improvements exist locally and need inclusion in the eventual change set.
- Unified API, worker, and frontend remain scaffolds.

Confirmed gaps:

- Negative counterfactual amounts can yield ALLOW.
- JSON date overrides can cause HTTP 500; string UUID allowlists can produce incorrect denials.
- Same-tenant evidence assigned to another payment can count toward completeness and yield CONSISTENT.
- Unsupported policy versions are accepted without verification.
- Guardian denies expired quotes while GhostPay can allow them; approval-threshold equality also produces different outcomes.

## Design rules

1. Validate untrusted inputs before evaluation, including objects modified with Pydantic `model_copy`, which bypasses validation.
2. Keep deterministic policy separate from optional natural-language explanation.
3. Bind results to exact tenant, transaction, merchant, amount, currency, policy version, and relevant evidence.
4. Report missing evidence and unsupported behavior explicitly. A passing digest alone does not establish provenance or provider truth.
5. Preserve original records. Simulations operate on isolated copies and are visibly hypothetical.
6. Treat mocked, synthetic, imported Sandbox, and live-verified evidence as different evidence sources.
7. Finish each stage with relevant tests and recorded acceptance evidence. Test counts alone do not establish correctness.

## Stage 1 — Validate counterfactual inputs

Affected area: `counterfactual/simulator.py`, API request models, module tests.

- Define a typed override model or equivalent explicit validation for supported fields.
- Parse UUIDs, enums, timezone-aware datetimes, booleans, and integer money through canonical validation.
- Reject nonpositive purchase amounts, negative limits, unsupported fields, malformed identifiers, and invalid dates.
- Revalidate modified passport, merchant, proposal, and quote models before replay.
- Return controlled client errors, without exposing internal exceptions.

Done when:

- Negative/zero/fractional/invalid money cannot produce an eligible result.
- Equivalent UUID objects and JSON UUID strings behave identically.
- ISO datetime overrides work; malformed values produce a documented 4xx response.
- Original request remains unchanged on both success and failure.
- Regression tests cover `/simulate` and `/counterfactual`.

## Stage 2 — Establish policy parity with Guardian

Affected area: replay policy evaluation; coordinate any shared interface with Guardian owners.

- Agree on one versioned policy specification and historical evaluation inputs.
- Prefer an explicit shared deterministic interface over two independently evolving rule engines. Preserve module boundaries and historical replay behavior.
- Compare currency, quote expiry, passport status/expiry, merchant allowlisting, categories, limits, and approval-threshold boundaries.
- Define historical approval handling separately from initial authorization. Check approval identity, transaction/decision binding, merchant, amount, currency, quote hash, and validity at evaluation time.
- Report unsupported versions or unavailable historical inputs explicitly; do not silently certify consistency using current rules.
- Distinguish genuine drift from an evaluator/version mismatch.

Done when:

- A cross-module regression matrix produces matching outcomes/reasons for equivalent historical decision inputs.
- Expired quote and exact-threshold reproductions are resolved according to the agreed specification.
- Unsupported versions cannot receive an unqualified CONSISTENT result.
- No budget reservation, payment call, or record mutation occurs during replay.

## Stage 3 — Strengthen provenance and completeness

Affected area: `provenance/verifier.py`, `timelines/builder.py`, anomaly reporting.

- Validate payment-intent and correlation associations in addition to tenant ownership.
- Check relationships among proposal, quote, passport, recorded decision, approval, events, and evidence.
- Unrelated evidence must not satisfy required artifacts or appear as supporting evidence.
- Clearly distinguish full-content hashes from legacy partial-payload digests. Do not claim fields excluded from a digest were verified.
- Test chain gaps, duplicates, changed payloads, missing events, and the declared boundary of partial chains.
- Preserve current status priority: integrity failure, incomplete evidence, drift, then consistency. Coordinate any contract changes first.

Done when:

- Another payment's evidence cannot make a request complete.
- Cross-tenant entities are rejected and same-tenant relationship mismatches are reported.
- Tampered covered content fails verification; legacy verification limits are visible.
- Shuffled events produce stable ordering and deterministic supporting evidence references.

## Stage 4 — Deliver the integration contract

GhostPay deliverable; shared API wiring remains a team dependency.

- Document existing `/ghostpay/replay`, `/simulate`, `/counterfactual`, `/timeline`, and `/health` routes, mounted under `/v1` by the unified application.
- Specify authenticated tenant context supplied by the host application. A caller-selected tenant header alone is not authentication.
- Define a read-only assembly interface for loading canonical replay records by payment identifier through repository/service interfaces.
- Clearly label caller-supplied replay payloads as analysis inputs rather than authenticated ledger records.
- Define controlled validation, missing-record, tenant, and unsupported-policy responses.
- Provide synthetic fixtures and sample JSON requests/results; mark synthetic payment states visibly.

Done when:

- The host can assemble and replay one canonical transaction without fabricating missing records.
- Integration tests exercise the mounted router, tenant context, and read-only behavior.
- Health is described as liveness, not evidence that PayPal or a database is ready.

## Stage 5 — Supply a small forensic demo

Use an evidence-first casebook presentation; dashboard implementation belongs to the frontend team unless separately assigned.

Minimum view:

- Transaction identity, merchant, amount/currency, policy version, and evidence-source label.
- Original versus recomputed decision and reason codes.
- Event timeline, evidence references, integrity status, and missing artifacts.
- Anomaly explanations tied to actual records.
- Counterfactual controls for transaction limit, merchant, and amount.
- A persistent “Simulation — no payment executed” label for hypothetical results.

Three-minute script:

1. **0:00–0:40:** Open a labeled synthetic $39 purchase and explain its recorded authorization.
2. **0:40–1:15:** Replay it; show supporting evidence and a consistent timeline.
3. **1:15–2:00:** Simulate a $30 transaction limit; show the hypothetical denial and unchanged original records.
4. **2:00–2:40:** Open a deliberately tampered or incomplete fixture; show integrity failure or missing evidence.
5. **2:40–3:00:** Explain the PayPal connection: GhostPay will analyze the verified Sandbox transaction record once the integration team supplies it.

Do not describe fixture playback as a completed Sandbox payment.

## Stage 6 — Verification and handoff

- Add targeted regression tests for each reproduced issue and a policy-parity matrix.
- Test invalid API overrides, tenant isolation, wrong-payment evidence, unsupported versions, approvals, chain corruption, repeatability, and non-mutation.
- Repair combined test discovery with the repository owners; add Guardian to the default Makefile test target.
- Run GhostPay tests and lint, then repository tests. Record separate outcomes if unrelated modules still fail checks.
- Update GhostPay README with startup commands, supported versions, known limitations, and integration examples.
- Supply the demo fixtures, route contract, acceptance results, and remaining dependencies for handoff.

Useful commands from repository root:

```sh
uv sync --python 3.12
uv run pytest modules/ghostpay/tests -v
uv run ruff check modules/ghostpay
uv run pytest --import-mode=importlib -q
uv run ruff check packages modules
git diff --check
```

The import-mode command currently avoids the known collection collision; it does not mean the default test command has been repaired.

## Definition of done for the GhostPay team

- [ ] Typed overrides handle JSON inputs and reject invalid values safely.
- [ ] Replay matches the agreed historical Guardian policy specification.
- [ ] Unsupported versions and missing historical context are explicit.
- [ ] Evidence and events are bound to the correct transaction and tenant.
- [ ] Integrity claims accurately describe what was verified.
- [ ] Simulations never mutate originals or execute financial actions.
- [ ] Regression and integration checks pass, with results recorded.
- [ ] A reproducible synthetic demo and frontend handoff exist.
- [ ] Later Sandbox-backed replay is tracked separately as NOT VERIFIED until executed.

## Deferred work

PayPal credentials/checkout integration, payment worker implementation, full dashboard development, natural-language purchasing, additional commerce verticals, and autonomous agents are outside this GhostPay plan. Optional AI explanations come after deterministic correctness and must cite existing evidence without changing verdicts.
