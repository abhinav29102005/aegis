# GhostPay

Read-only transaction forensics for AgentPay Nexus: replay initial authorization,
check evidence and event chains, detect drift, and simulate policy changes without
executing payments.

## Run and deploy

See [DEPLOYMENT.md](DEPLOYMENT.md) for credential generation, Docker Compose,
HTTPS/reverse-proxy requirements, routes, historical snapshots, limits, and
operations. The container includes a responsive forensic console at `/`.

```sh
uv sync --python 3.12
uv run pytest modules/ghostpay/tests -q
uv run ruff check modules/ghostpay
# Configure GHOSTPAY_TOKENS privately as documented before starting:
uv run uvicorn ghostpay.app:create_app --factory --host 127.0.0.1 --port 8000
```

The standalone app refuses to start without tenant-scoped bearer credentials.
It does not require PayPal credentials or a database. Public health checks prove
liveness only. The module router remains available for a host application that
supplies authenticated tenant context; do not expose that bare router directly.

## Implemented behavior

- Initial policy replay uses Guardian's deterministic public policy interface.
  `policy-v1` is supported; mismatched/unknown versions are explicitly rejected.
- Evaluations use historical record times and cannot predate supplied inputs.
  Approval consumption and payment execution belong to Guardian.
- Record identity, correlation, tenant, payment, merchant, amount, currency,
  approval bindings, and evidence ownership are verified.
- Full-content/envelope evidence digests, complete contiguous event chains, and
  duplicate record checks expose tampering and missing artifacts.
- Timelines sort deterministically and attach only associated evidence.
- Counterfactual changes are isolated, validated, and labeled hypothetical.
  They never conceal integrity/completeness failures in the original snapshot.
- A read-only snapshot-directory adapter supports identifier-based historical
  replay without substituting current policy for historical state.
- The web console imports snapshots, replays, simulates, shows findings/timelines,
  and exports JSON results. The built-in example is explicitly synthetic.

## Override contract

Supported fields: `per_tx_limit_minor`, `total_budget_minor`,
`allowed_merchant_ids`, `allow_unknown_merchants`,
`human_approval_threshold_minor`, `passport_status`, `expires_at`,
`merchant_override`, and `amount_override_minor`.

Money must be integer minor units: positive purchase amounts, nonnegative limits.
Numeric strings, fractions, boolean money, explicit nulls, and unknown fields are
rejected. Omit unchanged fields. UUID strings and timezone-aware ISO dates are
normalized. Merchant patches use the canonical Merchant schema and cannot cross
tenant boundaries. Explicit overrides take precedence over embedded overrides.
Invalid overrides return controlled HTTP 400 errors; malformed bodies use 422.

## Verification and limitations

See [STATUS.md](STATUS.md) for executed checks and [plan.md](plan.md) for the
implementation plan. Fixtures and mocked checks do not establish live provider
acceptance. Sandbox-backed replay and public hosting remain NOT VERIFIED.

`CONSISTENT` means the submitted records agree under the supported evaluator and
local checks; it does not authenticate their source or prove a PayPal payment.
Full-content hashes do not establish authenticity without trusted source records.
Legacy partial-content digests are rejected. A complete suffix deletion requires
an independently trusted terminal anchor to detect. The service is stateless;
external operators own snapshot retention, access policy, and backups.
