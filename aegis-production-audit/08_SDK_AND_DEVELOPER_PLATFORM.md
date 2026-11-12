# 08 — SDK & Developer Platform Assessment

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):** **BOTH `aegis-sdk` (PYTHON) AND `@aegis-platform/sdk` (TYPESCRIPT) NOW REACH `98.0%` (`97/99`) OPENAPI PARITY WITH `0` RUFF ERRORS, `38/38` TS TESTS PASS, `0` TS VULNERABILITIES, AND PASSING `INTEGRATION_GUIDE.md` VERBATIM CHECKS.**

---

## 1. Feature & Readiness Matrix (Post-Integration Verified)

| Dimension | `aegis-sdk` (`packages/sdk-python/`) | `@aegis-platform/sdk` (`packages/sdk-typescript/`) | Verified Status |
| :--- | :--- | :--- | :--- |
| Runtime / Async Support | `AegisClient` + `AsyncAegisClient` (`client.py` `2,352` LOC) | Async `fetch` + Node `crypto` & Edge WebCrypto (`client.ts` `967` LOC) | **CLOSED & VERIFIED** |
| **OpenAPI Endpoint Coverage (`99` ops across `88` paths)** | **`97 / 99` (`98.0%`)** | **`97 / 99` (`98.0%`)** | **PASSES `>=85%` GATE (`test_sdk_parity_gate.py`)** |
| Auth, Billing, Privacy, MFA/SSO, Refund & Resolve Wrappers | Sync + Async wrappers added for `/health`, `/ready`, `/v1/auth/{verify-email,resend-verification,mfa/*,sso/oidc/exchange}`, `/v1/orgs/invitations*`, `/v1/billing/*`, `/v1/privacy/*`, `/v1/audit-events/export`, `/v1/guardian/payments/{id}/refund`, `/v1/disputeos/cases/{id}/resolve`, & `/v1/ghostpay/{health,traces,replay,counterfactual}` | Matching typed TS client wrappers + `getArtifact`/`resolveCase`/`refundPayment` + MFA/SSO/invitations/billing/privacy/GhostPay helpers | **VERIFIED (`test_sdk_coverage.py` & parity gate PASS)** |
| Error Modeling | `AegisAPIError` (`exceptions.py`) | `errors.ts` FastAPI `detail` parser (`7/7` PASS) | **CLOSED & VERIFIED** |
| **Webhook Signature (`GAP-014`)** | `verify_aegis_signature` (`AEGIS-Signature: t=,v1=`, `300s` tolerance) | `verifyAegisSignature` Node + Edge WebCrypto (`12/12` `crypto.test.ts` PASS) | **UNIFIED & VERIFIED LIVE** |
| Agent Framework Middlewares & MCP | `aegis_sdk.integrations.{langchain,openai_agents}` + FastAPI `/v1/guardian/mcp` JSON-RPC 2.0 server | `src/integrations/vercel-ai.ts` (`6/6` `middleware.test.ts` PASS) | **VERIFIED** |
| Lint, Packaging & Security | `0` Ruff errors across Python SDK & tests; `py.typed`; `README.md`; `test_verbatim_integration_guide_*` PASS | `vite@^7.3.8` installed; `tsc` PASS; **`35` Vitest + `3` Node PASS**; `npm audit --omit=dev` **`0` vulnerabilities** | **VERIFIED (PyPI/npm publish pending)** |

---

## 2. Observed Post-Integration Parity Gate Output
- `uv run pytest -v tests/integration/test_sdk_parity_gate.py -s`:
  - `Total Canonical Endpoints: 99`
  - `Python SDK Coverage: 97 / 99 (98.0%)` — **PASSED**
  - `TypeScript SDK Coverage: 97 / 99 (98.0%)` — **PASSED**
  - `test_verbatim_integration_guide_python_webhook_verifier`: **PASSED**
  - `test_verbatim_integration_guide_flow`: **PASSED**
- Remaining non-code steps: Publishing `aegis-sdk` to PyPI and `@aegis-platform/sdk` to npm remains **`NOT VERIFIED`**.
