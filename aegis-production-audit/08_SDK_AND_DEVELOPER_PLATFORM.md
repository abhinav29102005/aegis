# 08 — SDK & Developer Platform Assessment

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **MASSIVELY UPGRADED BY M3 (`aegis-sdk` 2,043 LOC + `@aegis-platform/sdk` 35/35 Vitest + VERBATIM DOCS FIXED); PARITY GATE BELOW 85% AGAINST M1'S 96 ENDPOINTS (`75.0%` PY / `79.2%` TS) & RUFF CLEANUP NEEDED.**

---

## 1. Feature & Readiness Matrix (Post-M1 + M3 Merge)

| Dimension | `aegis-sdk` (`packages/sdk-python/`) | `@aegis-platform/sdk` (`packages/sdk-typescript/`) | Remaining Gap vs Target |
| :--- | :--- | :--- | :--- |
| Runtime / Async Support | Sync (`AegisClient`) **+** Async (`AsyncAegisClient`) implemented (`client.py` `2,043` LOC) | Async `fetch` + **Node `crypto` AND WebCrypto (`crypto.subtle`)** in `src/crypto.ts` | Clean |
| **OpenAPI Endpoint Coverage (`96` ops)** | **`72 / 96` operations (`75.0%`)** *(failed M3 `85%` CI gate)* | **`76 / 96` operations (`79.2%`)** *(failed M3 `85%` CI gate)* | M3 targeted pre-M1 `78` ops (`>90%`), missing M1's new `/v1/billing/*`, `/v1/privacy/*`, `/v1/auth/{mfa,sso,verify-email}`, `/v1/orgs/invitations*`, `/v1/audit-events/export` routes! |
| Error Modeling | `AegisAPIError` (`exceptions.py`) parses FastAPI `detail` | Fixed `errors.ts` (`typeof detail === "string"`, array, & `detail.message`) — `7/7` `errors.test.ts` PASS | Clean |
| Retries / Timeouts / Pagination | Configurable timeouts, retries, `PaginationIterator` / `AsyncPaginationIterator` | `AbortController` timeouts, retries, pagination helpers | Clean |
| Approval Reject Support | Supports explicit `approved: bool` + decline helper | Supports explicit `approved: boolean` + decline helper | Backend execution awaits M2 |
| **Webhook Signature Contract (`GAP-014`)** | **UNIFIED:** `verify_aegis_signature(raw_body, signature_header, secret, tolerance_seconds=300)` against `AEGIS-Signature: t=,v1=` | **UNIFIED:** `verifyAegisSignature` (Node + WebCrypto) against `AEGIS-Signature: t=,v1=` (`12/12` `crypto.test.ts` PASS) | Matches M1 Worker & `INTEGRATION_GUIDE.md` verbatim (`test_verbatim_integration_guide_*` PASS)! |
| Agent Framework Middlewares | `aegis_sdk.integrations.langchain` + `openai_agents` (`88–94%` cov) | `src/integrations/vercel-ai.ts` (`6/6` `middleware.test.ts` PASS) | Clean |
| Docs & Packaging | `packages/sdk-python/README.md`, `py.typed`, rewritten `docs/sdk/INTEGRATION_GUIDE.md` (`docs/TEAM_HANDOFF.md` deleted) | `packages/sdk-typescript/README.md`, typed `src/types.ts`, Vitest `35/35` + `tsc` build PASS | Clean up Ruff errors in `sdk-python` (`F821` `Any` in `tests/test_pagination.py`, unused imports in `client.py`, `BLE001`) |

---

## 2. Specific Failing Check Identified on Merged Sync
- `uv run pytest tests/integration/test_sdk_parity_gate.py::test_openapi_sdk_coverage_gate` **FAILED (`2026-11-12`)**:
  - `Total Canonical Endpoints: 96`
  - `Python SDK Coverage: 72 / 96 (75.0%)` (missing M1 routes `/v1/billing/*`, `/v1/privacy/*`, `/v1/auth/mfa/*`, `/v1/auth/sso/oidc/exchange`, `/v1/auth/verify-email`, `/v1/orgs/invitations*`, `/v1/audit-events/export`, plus `/v1/ghostpay/{health,replay,counterfactual}`, `/v1/paypal/webhooks`, `/health`, `/ready`)
  - `TypeScript SDK Coverage: 76 / 96 (79.2%)`
  - Remediation: Wrap M1's commercial/privacy/auth/invitation endpoints in `sdk-python` and `sdk-typescript` to restore `>=85%` parity across all `96` operations (plus any new M2 `/resolve`/refund routes).
