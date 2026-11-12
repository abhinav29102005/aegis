# RC1 PayPal Sandbox & Negative-Path Verification

**Branch:** `fix/rc1-guardian-deadlock`  
**Scope:** PayPal Sandbox credential check, live Sandbox OAuth + Orders v2 creation (`api-m.sandbox.paypal.com`), `packages/paypal` unit tests, and RC1 PayPal/webhook negative-path integration tests (`httpx.MockTransport`).

## 1. Live PayPal Sandbox Verification Status

**Status:** **PARTIAL PASS — Live Sandbox OAuth + Order Creation VERIFIED (`test_live_paypal_sandbox_oauth_and_order_roundtrip` PASSED); Buyer Capture / Live Webhook Delivery / Disputes v1 NOT VERIFIED**

Environment credential check (values never printed; stored in untracked local `.env`):

```text
PAYPAL_MODE: sandbox
PAYPAL_BASE_URL: https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID: SET
PAYPAL_CLIENT_SECRET: SET
PAYPAL_WEBHOOK_ID: SET (staging webhook https://api-staging.abhinavkumarsingh.tech/v1/paypal/webhooks)
```

With `.env` exported (`set -a && source .env && set +a`), `packages/paypal/tests/test_live_sandbox_optional.py::test_live_paypal_sandbox_oauth_and_order_roundtrip` **PASSED (`2.05s`)** against `https://api-m.sandbox.paypal.com` (live OAuth2 client-credentials token acquisition and live Sandbox Orders v2 creation). Interactive buyer-approved capture, live webhook delivery to `api-staging.abhinavkumarsingh.tech`, and live Disputes v1 API calls remain **`NOT VERIFIED`** until staging is live.

## 2. Existing PayPal Unit + Live Sandbox Suite

Command:

```bash
set -a && source .env && set +a && uv run pytest packages/paypal/tests/ -q
```

Observed output:

```text
............                                                             [100%]
12 passed in 3.52s
```

- `11 passed` (`packages/paypal/tests/test_paypal.py`)
- `1 passed` (`packages/paypal/tests/test_live_sandbox_optional.py::test_live_paypal_sandbox_oauth_and_order_roundtrip`)

## 3. RC1 PayPal & Webhook Negative-Path Integration Suite

Test file: [`tests/integration/test_rc1_paypal_negative_paths.py`](../../tests/integration/test_rc1_paypal_negative_paths.py)

### Coverage Summary

1. **Missing / malformed `AEGIS-Signature` & stale timestamps (>300s tolerance)**
   - Verified both `security.verify_aegis_signature` and `aegis_sdk.verify_aegis_signature` reject empty, missing `t=`, missing `v1=`, non-integer `t=`, duplicate `t=`, wrong digest, wrong secret, tampered payload, and timestamps outside `±300s` (`ts + 301`, `ts - 301`, `now - 305`), while accepting the exact boundary (`ts + 300`).
2. **Missing / malformed PayPal webhook signature headers (`PAYPAL-TRANSMISSION-SIG` & required PayPal headers)**
   - Verified `PayPalSandboxClient.verify_webhook_signature` fails closed (`False`) with zero outbound HTTP calls when any of `PAYPAL-TRANSMISSION-SIG`, `PAYPAL-AUTH-ALGO`, `PAYPAL-CERT-URL`, `PAYPAL-TRANSMISSION-ID`, or `PAYPAL-TRANSMISSION-TIME` is missing.
   - Verified `PayPalSandboxClient.verify_webhook_signature` raises `PayPalConfigurationError` when `PAYPAL_WEBHOOK_ID` is unset.
   - Verified `POST /v1/paypal/webhooks` returns `401` (`PAYPAL_WEBHOOK_INVALID_SIGNATURE`) for missing/empty `PAYPAL-TRANSMISSION-SIG` or `verification_status: FAILURE`, and `400` (`INVALID_WEBHOOK_PAYLOAD`) for malformed/non-object JSON.
3. **Duplicate webhook event replay idempotency**
   - Verified `POST /v1/paypal/webhooks` deduplicates repeated `event_id` deliveries (`deduplicated: False` on first delivery, `deduplicated: True` on replay) without duplicating ledger events.
4. **PayPal HTTP 5xx / timeout retry & error surfacing without secret leakage**
   - Verified transient `503` retries succeed on subsequent `201` response.
   - Verified persistent `503` raises `PayPalAPIError(status_code=503, debug_id=...)` and `httpx.ReadTimeout` raises `PayPalTimeoutError` without leaking `paypal_client_secret` or bearer tokens.
   - Verified API endpoints (`POST /v1/paypal/webhooks` on `ConnectError` -> `401 PAYPAL_WEBHOOK_VERIFICATION_FAILED`; `POST /v1/disputeos/cases/{case_id}/submit` on `503` -> `502 PAYPAL_UPSTREAM_ERROR`, on `ReadTimeout` -> `504 PAYPAL_TIMEOUT`) do not leak `paypal_client_secret` or internal exception strings.
5. **`SyntheticSubmissionError` blocking external PayPal dispute submission for `SYNTHETIC_DEMO` cases**
   - Verified `POST /v1/disputeos/cases/{case_id}/submit` on an analyzed, human-approved `SYNTHETIC_DEMO` case returns `403 Forbidden` with zero outbound HTTP calls to PayPal, and `DisputeCaseService.mark_submitted` raises `SyntheticSubmissionError`.

### Lint & Test Execution

Command:

```bash
uv run ruff check tests/integration/test_rc1_paypal_negative_paths.py
```

Observed output:

```text
All checks passed!
```

Command:

```bash
uv run pytest -v tests/integration/test_rc1_paypal_negative_paths.py
```

Observed output:

```text
13 passed in 1.64s
```
