# AEGIS RC1 — Live Chromium Browser E2E Verification Report

**Branch:** `release/rc1-c1-security-e2e-deploy`  
**Stack Tested:** Ephemeral PostgreSQL 16 (`0003_prod_hardening`), FastAPI (`uvicorn aegis_api.app:create_app --factory`), Next.js 16.4.6 production build (`next start`), Real Google Chrome (`/usr/bin/google-chrome`) via `@playwright/test` (`apps/web/tests/playwright_e2e_journeys.spec.ts`)  
**Result:** **5 passed, 0 failed (11.1s)** — Zero uncaught page errors, zero console errors, zero React hydration mismatches, zero 5xx responses, zero unexpected 4xx/404 responses.

---

## Verified End-to-End Journeys

| Journey | Scope Verified | Result | Duration |
|---|---|---|---|
| **Journey 1** | Unauthenticated redirect (`/dashboard`, `/payments` -> `/login`), organization registration + `aegis_session` `HttpOnly` cookie, header org creation modal + org switching + reload persistence, adding `VIEWER` member, logout + cookie clearance, `VIEWER` role UI restriction verification | **PASS** | 2.2s |
| **Journey 2** | Guardian agent & merchant creation, spending passport issuance (`$1,000` total / `$500` per-tx / `$800` daily / `$100` human approval threshold), Proposal 1 (`$150`) -> `AWAITING_APPROVAL` -> `Decline / Reject` (`approved: false`), Proposal 2 (`$150`) -> `Approve & Reserve` -> `Initiate Checkout` (cleanly handling unconfigured PayPal Sandbox `4xx` via `role="alert"`) | **PASS** | 2.1s |
| **Journey 3** | GhostPay forensic replay launch from `/ghostpay`, provenance timeline inspection (`#1` hash chain), counterfactual simulation (`per_tx_limit_minor=5000`), `VIEWER` button disabled + direct `POST /api/proxy/ghostpay/simulate/by-payment/{id}` returning `403 Forbidden` | **PASS** | 2.4s |
| **Journey 4** | DisputeOS `SYNTHETIC_DEMO` case creation linked to `PaymentIntent`, structured JSON evidence attach, file artifact upload, grounded analysis + provenance graph (`Evidence graph: N nodes · M edges`), report export (`200`), draft approval (`Approve Draft`), `SyntheticSubmissionError` disabled `Submit to PayPal` guard, case resolution (`RESOLVED`) | **PASS** | 2.5s |
| **Journey 5** | Developer Portal (`/developer`) API key creation + webhook endpoint creation + delivery history, Settings (`/settings`) Stripe billing & quotas + GDPR/DPDPA portability & erasure UI, public `/status`, `/legal/terms`, `/legal/privacy`, `/legal/dpa` | **PASS** | 1.3s |

---

## Real Defects Discovered and Fixed During Live Chromium Testing

1. **Chromium ES2024 `v`-flag HTML `<input pattern>` Crash (`SyntaxError`)**
   - **Where:** `apps/web/src/app/login/page.tsx`, `apps/web/src/components/AppShell.tsx`, `apps/web/src/app/settings/page.tsx`
   - **Finding:** `pattern="^[a-z0-9-]+$"` threw `Invalid regular expression: /^[a-z0-9-]+$/v: Invalid character in character class` in Chromium.
   - **Fix:** Updated to `pattern={"^[a-z0-9\\-]+$"}` (verified valid in ES2024 `v` mode).

2. **Non-existent `/v1/billing/usage` Endpoint (`404 Not Found`)**
   - **Where:** `apps/web/src/app/settings/page.tsx`
   - **Finding:** Settings page queried `GET /v1/billing/usage` (`404`) instead of `GET /v1/billing/subscription`.
   - **Fix:** Updated `settings/page.tsx` to call `GET /v1/billing/subscription` and map `plan` and `status` cleanly.

3. **Post-Response Transaction Commit Race on Immediate UI Refetch**
   - **Where:** `services/api/aegis_api/routers/auth_orgs.py` (`create_organization`), `services/api/aegis_api/routers/guardian_db.py` (`approve_proposal`), `services/api/aegis_api/routers/disputeos_db.py` (`attach_evidence`, `upload_evidence_artifact`, `analyze_case`, `approve_case`, `resolve_case`)
   - **Finding:** FastAPI `Depends(get_db_session)` generator teardown commits after sending response bytes; immediate browser follow-up requests (`switch-org` -> `/v1/auth/me` returning `403`, `loadDetail()` still seeing `AWAITING_APPROVAL`, `loadCase()` seeing empty evidence) raced with teardown commit.
   - **Fix:** Added explicit `session.commit()` prior to returning responses in those mutating handlers.

4. **DisputeOS JSON Evidence Form Invalid `EvidenceSourceType` Options (`422`)**
   - **Where:** `apps/web/src/app/disputes/[id]/page.tsx`
   - **Finding:** `#json-ev-type` offered values (`ACCESS_LOG`, `MERCHANT_COMMUNICATION`, etc.) not in `packages/contracts.enums.EvidenceSourceType`, causing `422 Unprocessable Entity`.
   - **Fix:** Aligned dropdown options with canonical `EvidenceSourceType` values.

5. **Missing Web App Icon (`/favicon.ico` `404`)**
   - **Where:** `apps/web/src/app/icon.svg`
   - **Finding:** Every browser navigation logged a `404` console error for `/favicon.ico`.
   - **Fix:** Added `apps/web/src/app/icon.svg` so Next.js serves an icon cleanly (`24/24` routes built).

