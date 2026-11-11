# GhostPay (`modules/ghostpay/`)

**Branch:** `feature/ghostpay`
**Status:** Hardened, Tested, and Integration-Ready (Forensic & Simulation Engine for AgentPay Nexus)

## Overview
GhostPay provides deterministic authorization replay, strictly validated counterfactual policy simulation, anomaly detection, provenance verification, and deterministic event timeline reconstruction for autonomous agent spending.

## Core Responsibilities & Components
```text
modules/ghostpay/
├── ghostpay/
│   ├── __init__.py
│   ├── errors.py        # Domain exceptions (OverrideValidationError, UnsupportedPolicyVersionError, ReplayExecutionForbiddenError)
│   ├── repository.py    # Read-only GhostPayReplayRepository Protocol for DB handoff
│   ├── replay/          # Policy version registry (registry.py) & deterministic ReplayEngine (engine.py)
│   ├── counterfactual/  # Strict Pydantic v2 override validator (validator.py) & non-mutating simulator (simulator.py)
│   ├── anomalies/       # Authorization drift, currency, policy-version, & forensic anomaly detection
│   ├── provenance/      # Evidence completeness, correlation binding, & hash-chain integrity verification
│   ├── timelines/       # Deterministic event timeline reconstruction (`build_timeline`)
│   └── api/             # FastAPI APIRouter (`prefix="/ghostpay"`, `create_ghostpay_router(...)` + `router`)
├── tests/               # 10 core scenarios + API tests + comprehensive hardening regression suite
├── GHOSTPAY_HARDENING_REPORT.md
├── README.md
└── pyproject.toml
```

## Supported Policy Versions
- **`policy-v1`** (default and only registered evaluator):
  - Enforces `SpendingPassport` status (`ACTIVE`) and UTC expiration vs `evaluation_time` (or `recorded_decision.decided_at` / `quote.created_at`, never wall-clock time).
  - Enforces `per_tx_limit_minor`, `available_budget_minor`, and `daily_limit_minor`.
  - Enforces merchant allowlists (`allowed_merchant_ids`, `allow_unknown_merchants`) and strict category allowlists (`merchant.category` & `proposal.merchant_category`).
  - Enforces `human_approval_threshold_minor` and `ApprovalRecord` expiry/merchant/amount/quote-hash binding.
- Unsupported `policy_version` values fail closed with `UnsupportedPolicyVersionError` (HTTP **422**).
- Policy-version mismatches against `recorded_decision.policy_version` or `recorded_passport.policy_version` are flagged (`POLICY_VERSION_MISMATCH`) and cannot silently return `CONSISTENT`.

## Counterfactual Overrides & Baseline Replay Semantics
- **Baseline replay** (`POST /ghostpay/replay`, `ReplayEngine.replay`): reconstructs recorded policy evaluation only and rejects nonempty `counterfactual_overrides` with `OverrideValidationError` (HTTP **422**).
- **Counterfactual simulation** (`POST /ghostpay/simulate`, `POST /ghostpay/counterfactual`, `simulate_counterfactual`):
  - Validates overrides against an explicit allowlist (`ALLOWED_OVERRIDE_FIELDS`): `per_tx_limit_minor`, `total_budget_minor`, `daily_limit_minor`, `allowed_merchant_ids`, `allow_unknown_merchants`, `allowed_categories`, `human_approval_threshold_minor`, `passport_status`, `expires_at`, `merchant_override`, `amount_override_minor`, `currency_override`.
  - Rejects unknown fields and immutable identity/evidence/execution fields (`tenant_id`, `payment_intent_id`, `correlation_id`, `events`, `evidence_records`, `recorded_decision`, `executed_payment`, `paypal_order_id`, `paypal_capture_id`, `quote_hash`, etc.) with HTTP **422**.
  - Reconstructs affected Pydantic contracts via `Model.model_validate(...)` (never unvalidated `model_copy(update=...)`).
  - Returns baseline-vs-hypothetical comparison inside `ReplayResult.changed_constraints` and `ReplayResult.explanation` (without mutating original inputs).

## Security, Read-Only Safety & Database Status
- **Tenant Isolation**: `assert_same_tenant` is enforced across `ReplayRequest`, all nested contract records, events, evidence records, `TimelineRequest`, and counterfactual `merchant_override`s (violations raise `TenantIsolationError` → HTTP **403**).
- **Authentication Boundary**: Raw `X-Tenant-Id` header fallback is restricted to `APP_ENV` in `{development, dev, test, testing, local}`. Outside dev/test environments, endpoints require authenticated tenant context from trusted middleware (`request.state.authenticated_tenant_id` or `create_ghostpay_router(tenant_resolver=...)`), failing closed with HTTP **401** otherwise.
- **Zero Payment Execution**: GhostPay has zero runtime imports from `paypal` or `database` execution clients and enforces `executed_payment=False` on every path.
- **Database Persistence Status**: The current GhostPay API is **stateless** and accepts complete `ReplayRequest` payloads. `ghostpay.repository.GhostPayReplayRepository` defines the exact read-only `Protocol` (`load_replay_request(tenant_id, correlation_id) -> ReplayRequest | None`) for wiring into `packages/database` (`LedgerRepository`) inside `services/api/`.

## Running Verification & Tests
```bash
# Run all GhostPay tests
PYTHONPATH=modules/ghostpay uv run pytest modules/ghostpay/tests -v

# Run Ruff lint checks
uv run ruff check modules/ghostpay
```
