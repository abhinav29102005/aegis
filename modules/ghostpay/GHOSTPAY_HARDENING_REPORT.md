# GhostPay Hardening & Integration Readiness Report

- **Module:** `modules/ghostpay/`
- **Branch:** `feature/ghostpay`
- **Hardening Implementation Commit:** `3c65b9abaf82d5657c70550a0a5ef7361f47e31c` (`3c65b9a`)
- **Baseline Commit:** `0dd78b087882b83bcdf70b3eddcb84e0f44e749e` (`0dd78b0`)

---

## 1. Original Issues Identified

1. **P0 — Unsafe Pydantic v2 Overrides (`ghostpay/counterfactual/simulator.py`)**:
   - `simulate_counterfactual()` applied overrides via `model_copy(update=...)`, bypassing Pydantic v2 validators.
   - ISO datetime strings in `expires_at` stayed `str`, risking `TypeError` during timestamp comparisons.
   - UUID strings in `allowed_merchant_ids` bypassed `UUID` coercion, silently breaking merchant allowlist checks.
   - `dict` values in `merchant_override` risked skipping strict model validation and tenant checks.
   - Unknown fields, negative monetary values, invalid currencies, invalid enum values, and immutable field mutations lacked explicit allowlist/immutability guards.
2. **P0 — Replay Silently Ignored `counterfactual_overrides` (`ghostpay/replay/engine.py`)**:
   - `ReplayEngine.replay()` (`POST /ghostpay/replay`) silently ignored non-empty `ReplayRequest.counterfactual_overrides`.
3. **P0 — Policy Version Integrity (`ghostpay/replay/engine.py`)**:
   - `ReplayRequest.policy_version` was echoed directly to `ReplayResult.policy_version` without an evaluator registry, accepting arbitrary/unsupported version strings and silently returning `CONSISTENT` even if recorded artifacts declared a different `policy_version`.
4. **P0 — Dev Header Auth & Category Allowlist Boundary (`ghostpay/api/router.py`, `ghostpay/replay/engine.py`)**:
   - `X-Tenant-Id` header fallback had no environment gate against non-dev deployments.
   - Category allowlist check used `and` (`merchant_cat not in allowed_cats and proposal_cat not in allowed_cats`), allowing mismatched `proposal.merchant_category` to mask a disallowed `merchant.category`.
5. **P1 — Cross-Correlation Binding & Workspace Handoff (`ghostpay/provenance/verifier.py`)**:
   - Events/evidence needed explicit correlation-ID binding checks against `request.correlation_id`.
   - No documented read-only repository `Protocol` or root workspace/CI integration patch existed on the branch.

---

## 2. Root Causes

- `BaseModel.model_copy(update=...)` in Pydantic v2 explicitly skips field and model validators.
- `ReplayEngine.replay()` had no guard on `request.counterfactual_overrides` and no policy-version registry lookup.
- Raising `TypeError` inside Pydantic v2 `@field_validator` functions escapes `ValidationError` wrapping unless `ValueError` or `PydanticCustomError` is raised.
- FastAPI closure dependencies with `from __future__ import annotations` cannot resolve local closure callables via stringified `Annotated[UUID, Depends(local_fn)]` annotations unless evaluated eagerly without deferred annotations.

---

## 3. Files Modified & Added (`modules/ghostpay/`)

### Added Files
- `modules/ghostpay/ghostpay/errors.py` — Domain exceptions (`GhostPayError`, `OverrideValidationError`, `UnsupportedPolicyVersionError`, `ReplayExecutionForbiddenError`).
- `modules/ghostpay/ghostpay/replay/registry.py` — Explicit policy evaluator registry (`DEFAULT_POLICY_VERSION`, `SUPPORTED_POLICY_VERSIONS`, `register_policy_evaluator`, `get_registered_policy_versions`, `resolve_policy_evaluator`).
- `modules/ghostpay/ghostpay/counterfactual/validator.py` — Strict Pydantic v2 counterfactual validator (`ALLOWED_OVERRIDE_FIELDS`, `IMMUTABLE_OVERRIDE_FIELDS`, `ValidatedCounterfactualOverrides`, `validate_counterfactual_overrides`, `apply_validated_counterfactual_overrides`).
- `modules/ghostpay/ghostpay/repository.py` — Read-only `GhostPayReplayRepository` `Protocol` for DB-backed handoff.
- `modules/ghostpay/tests/test_ghostpay_hardening.py` — Comprehensive P0/P1 regression test suite (46 test cases including parametrized inputs).
- `modules/ghostpay/GHOSTPAY_HARDENING_REPORT.md` — This report.

### Modified Files
- `modules/ghostpay/ghostpay/replay/engine.py`
- `modules/ghostpay/ghostpay/replay/__init__.py`
- `modules/ghostpay/ghostpay/counterfactual/simulator.py`
- `modules/ghostpay/ghostpay/counterfactual/__init__.py`
- `modules/ghostpay/ghostpay/anomalies/detector.py`
- `modules/ghostpay/ghostpay/provenance/verifier.py`
- `modules/ghostpay/ghostpay/api/router.py`
- `modules/ghostpay/ghostpay/__init__.py`
- `modules/ghostpay/README.md`

---

## 4. Exact Fixes Implemented

1. **Strict Counterfactual Override Validator (`ghostpay/counterfactual/validator.py`)**:
   - Explicitly allowlisted 12 override keys (`ALLOWED_OVERRIDE_FIELDS`) and explicitly denied immutable transaction/evidence/execution keys (`IMMUTABLE_OVERRIDE_FIELDS`) and unknown keys with `OverrideValidationError`.
   - Used `pydantic_core.PydanticCustomError` inside `ValidatedCounterfactualOverrides` to strictly validate `int` vs `bool`, non-negative bounds (`>= 0` for limits/budget/threshold, `> 0` for `amount_override_minor`), `bool` strictly for `allow_unknown_merchants`, UUID coercion for `allowed_merchant_ids`, ISO-8601 UTC normalization for `expires_at`, 3-letter ASCII alphabetic currency codes for `currency_override`, and enum parsing for `passport_status`.
   - Reconstructed `SpendingPassport`, `Merchant`, `PurchaseProposal`, and `QuoteSnapshot` via `.model_validate(...)` (with `assert_same_tenant` on `merchant_override`), catching any Pydantic `ValidationError` cleanly into `OverrideValidationError` (HTTP **422**), while raising `TenantIsolationError` (HTTP **403**) on cross-tenant `merchant_override`.
2. **Baseline Replay vs Simulation Semantics (`ghostpay/replay/engine.py`, `ghostpay/counterfactual/simulator.py`)**:
   - `ReplayEngine.replay()` now rejects nonempty `request.counterfactual_overrides` with `OverrideValidationError` (HTTP **422**).
   - `simulate_counterfactual()` merges `request.counterfactual_overrides` + `overrides`, enforces tenancy and policy version upfront, runs both baseline replay and validated isolated hypothetical replay (without mutating `request`), and prepends `COUNTERFACTUAL_COMPARISON` into `ReplayResult.changed_constraints` and `explanation`.
3. **Policy Version Registry & Drift Enforcement (`ghostpay/replay/registry.py`, `ghostpay/replay/engine.py`, `ghostpay/anomalies/detector.py`)**:
   - Registered `"policy-v1"` in `_POLICY_REGISTRY`. Unsupported versions raise `UnsupportedPolicyVersionError` (HTTP **422**).
   - `ReplayEngine.replay()` executes only the resolved evaluator and sets `ReplayResult.policy_version = executed_policy_version`.
   - Mismatches between `executed_policy_version` and `recorded_decision.policy_version` or `recorded_passport.policy_version` set `drift_detected=True` and prevent returning `CONSISTENT` (`POLICY_VERSION_MISMATCH`).
4. **Category, Provenance, Currency & Tenant Auth Hardening**:
   - Category allowlist (`ghostpay/replay/engine.py`) requires both `merchant.category` and `proposal.merchant_category` to be permitted when `allowed_categories` is populated.
   - `detect_anomalies` (`ghostpay/anomalies/detector.py`) adds `CURRENCY_MISMATCH` and `POLICY_VERSION_MISMATCH`.
   - `verify_provenance_and_integrity` (`ghostpay/provenance/verifier.py`) checks `ev.correlation_id == request.correlation_id` across events and evidence records.
   - `get_dev_tenant_id` (`ghostpay/api/router.py`) checks `request.state.authenticated_tenant_id` first and permits `X-Tenant-Id` only when `APP_ENV` is in `{development, dev, test, testing, local}` (failing closed with HTTP **401** in non-dev environments).

---

## 5. New Tests Added (`modules/ghostpay/tests/test_ghostpay_hardening.py`)

Preserved all 15 baseline tests (`test_ghostpay.py` and `test_ghostpay_api.py`) and added **46 hardening test cases** covering:
- Counterfactual ISO datetime conversion (UTC & naive) and malformed/numeric/bool datetime rejection (HTTP 422).
- UUID string list coercion and invalid UUID/non-list rejection (HTTP 422).
- Nested `merchant_override` dict validation, unknown-field rejection, and malformed UUID rejection (HTTP 422).
- Negative limits/amounts, `bool`-as-`int`, invalid enum, invalid currency code, and unknown override key rejection (HTTP 422).
- Immutable identity/evidence/execution field override rejection (HTTP 422).
- Cross-tenant `merchant_override` rejection (HTTP 403).
- Original `ReplayRequest` and nested object deep non-mutation check.
- Baseline replay empty vs nonempty `counterfactual_overrides` (HTTP 422 on `/ghostpay/replay`, 200 on `/ghostpay/simulate` & `/ghostpay/counterfactual`).
- Policy version registry (`policy-v1` accepted; unsupported versions rejected with 422; recorded version mismatch prevents `CONSISTENT`).
- Production environment (`APP_ENV=production`) rejecting raw `X-Tenant-Id` (HTTP 401) and accepting trusted `request.state.authenticated_tenant_id`.
- Runtime dependency-graph audit verifying zero `paypal` or `database` execution imports across all `ghostpay.*` modules.
- Deterministic byte-identical repeated replay and repeated simulation JSON outputs, cross-correlation integrity failure, non-wall-clock `evaluation_time`, `/v1` router mounting, OpenAPI schema path generation, and `GhostPayReplayRepository` interface presence.

---

## 6. Test Results

- **GhostPay module test suite** (`PYTHONPATH=modules/ghostpay uv run pytest modules/ghostpay/tests -v`):
  - **61 passed, 0 failed, 0 warnings** in 0.52s (`10` core scenarios + `5` baseline API tests + `46` hardening tests).
- **Shared workspace + DisputeOS suite** (`uv run pytest -v` from root):
  - **27 passed, 0 failed** in 0.57s (`packages/contracts`, `packages/security`, `packages/database`, `packages/paypal`, `modules/disputeos`).
  - Live PayPal Sandbox / external PostgreSQL integration: **NOT VERIFIED** (no live credentials/Docker DB run in GhostPay verification; GhostPay does not depend on PayPal).

---

## 7. Ruff Results

- `uv run ruff check modules/ghostpay`: **All checks passed** (0 errors).

---

## 8. API Behavior Changes

- `POST /ghostpay/replay`: Rejects nonempty `counterfactual_overrides` and unsupported `policy_version` with **HTTP 422** (`error_code`: `INVALID_COUNTERFACTUAL_OVERRIDES` / `UNSUPPORTED_POLICY_VERSION`).
- `POST /ghostpay/simulate` & `POST /ghostpay/counterfactual`: Strictly validate `overrides`, return structured **HTTP 422** on invalid/immutable/unknown overrides or unsupported policy versions (no HTTP 500s on bad inputs), return **HTTP 403** on cross-tenant entity or `merchant_override` violations, and include baseline-vs-hypothetical comparison inside `ReplayResult.changed_constraints` and `ReplayResult.explanation`.
- All routes (`create_ghostpay_router(tenant_resolver=...)`): Reject unauthenticated `X-Tenant-Id` with **HTTP 401** when `APP_ENV` is not dev/test unless `request.state.authenticated_tenant_id` or a custom `tenant_resolver` is supplied.

---

## 9. Supported Policy Versions

- `policy-v1` (`ghostpay.replay.registry.SUPPORTED_POLICY_VERSIONS = ("policy-v1",)`).
- No other historical or synthetic policy versions are registered.

---

## 10. Security Guarantees

- Strict `assert_same_tenant` across `ReplayRequest`, all nested objects, events, evidence records, `TimelineRequest`, and `merchant_override`.
- `X-Tenant-Id` disabled outside dev/test unless trusted middleware authenticates tenant identity (`request.state.authenticated_tenant_id` or custom `tenant_resolver`).
- Zero imports of `paypal` or `database` execution code; `executed_payment=False` verified and fail-closed guarded on all replay and simulation paths.
- Original inputs never mutated; missing evidence explicitly listed; tampered hashes/chains/cross-correlation splices fail closed with `INTEGRITY_FAILURE`.

---

## 11. Remaining Limitations

1. **Frozen `ReplayResult` Schema**: `packages/contracts` (`SCHEMA_VERSION = "1.0.0"`) sets `extra="forbid"` on `ReplayResult`. Counterfactual baseline-vs-hypothetical diffs are therefore surfaced via `original_outcome` vs `recomputed_outcome`, `changed_constraints`, and `explanation` rather than adding a new top-level `counterfactual_comparison` field.
2. **Stateless Replay**: Endpoints currently accept complete `ReplayRequest` payloads rather than loading persisted records from PostgreSQL directly.
3. **Single Policy Version**: Only `policy-v1` exists in the codebase; historical policy versions must only be registered when their distinct evaluator logic is implemented.

---

## 12. Integration Instructions (Handoff Patch for Coordinator)

Because shared root configuration (`pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`) and `services/api/` belong to the integration branch (`integration/nexus` / `main`), the coordinator should apply these exact additions when merging `feature/ghostpay`:

1. **Root `pyproject.toml`**:
   - Add `"ghostpay"` to `[project].dependencies`
   - Add `"modules/ghostpay"` to `[tool.uv.workspace].members`
   - Add `ghostpay = { workspace = true }` to `[tool.uv.sources]`
   - Add `"modules/ghostpay/tests"` to `[tool.pytest.ini_options].testpaths`
   - Run `uv lock && uv sync --python 3.12` so `ghostpay` imports directly from the root workspace without `PYTHONPATH=modules/ghostpay`.
2. **`.github/workflows/ci.yml`**:
   - Update lint step to `uv run ruff check packages modules/disputeos modules/ghostpay`.
3. **`services/api/` Mounting**:
   - Mount `app.include_router(create_ghostpay_router(tenant_resolver=authenticated_tenant_dep), prefix="/v1")` to expose `/v1/ghostpay/{health,replay,simulate,counterfactual,timeline}`.
4. **Database Adapter Handoff**:
   - Implement `ghostpay.repository.GhostPayReplayRepository.load_replay_request(tenant_id, correlation_id)` over `database.LedgerRepository` (fetching `PaymentIntent` by `correlation_id`, `PurchaseProposal`, `QuoteSnapshot`, `SpendingPassport`, `Merchant`, `AuthorizationDecision`, optional `ApprovalRecord`, plus `list_events` and `list_evidence`), then optionally add a thin `/v1/ghostpay/replay/{correlation_id}` route in `services/api/`.

---

## 13. Git Commit Reference

- Code, tests, and module documentation hardening commit on `feature/ghostpay`: **`3c65b9abaf82d5657c70550a0a5ef7361f47e31c`** (`3c65b9a`).
