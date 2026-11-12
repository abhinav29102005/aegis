# 07 — Frontend & Product Experience Audit (`apps/web/`)

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **M3 CONTRACT FIXES, `HttpOnly` COOKIE BFF, ONBOARDING/LEGAL/BILLING/PRIVACY UI COMPLETE & BUILT (`19` pages + `6` BFF routes); LIVE PLAYWRIGHT BROWSER RUN STILL PENDING.**  
**Stack:** Next.js `15.5.29`, React `19`, TypeScript, Tailwind CSS `3.4.17`, `lucide-react`

---

## 1. Cross-Cutting Product & Security Fixes Landed in M3 (`4b5d52f`)

1. **`HttpOnly` Cookie Session BFF (`GAP-018` RESOLVED):** Replaced `window.localStorage` JWT storage with Next.js Route Handlers (`/api/auth/login`, `/api/auth/signup`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/switch-org`, `/api/proxy/[...path]`) setting `HttpOnly; SameSite=Lax` cookie `aegis_session`. Verified zero `localStorage` matches in `apps/web/src/`. Added `/api/auth/me` load validation, `401` eviction, `AbortController` timeouts, `middleware.ts` route protection, & CSP / `X-Frame-Options` / `X-Content-Type-Options` / `Referrer-Policy` headers.
2. **All 5 Broken Backend Contract Screens Aligned (`GAP-004` RESOLVED):**
   - `/payments/[id]`: Capture button now keys on `activeAttempt?.state === "CAPTURE_PENDING"`, reads `attempt.state`, `verified_capture?.paypal_capture_id`, `paypal_approval_url`, `approval.decided_at`, and exposes **Decline (`approved: false`)** & **Refund** actions.
   - `/agents`: Fixed permission check from non-existent `"merchants:write"` to `"passports:write"` + search/pagination.
   - `/developer` & `/settings`: Replaced legacy invalid roles (`DEVELOPER`, `AGENT_RUNTIME`, `FINANCE_ADMIN`, `RISK_ANALYST`, `DISPUTE_OPERATOR`) with the canonical 6 `Role`s (`OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`).
   - `/ghostpay/replay/[id]`: Updated timeline rendering to `occurred_at`, `actor_type`, `actor_id`, `previous_event_hash`; added `POST /v1/ghostpay/investigations` & Agent DNA view.
   - `/disputes/[id]`: Aligned `DisputeAnalysis` rendering (`grounded_summary`, `generated_with_llm`, `citations`, `contradictions`), SLA `response_due_by` display, non-synthetic `POST /cases`, `/resolve`, `/report`.
3. **Commercial, Legal, Onboarding & Operational Surfaces Added (`GAP-022`/`GAP-024`):** Added `/onboarding` guided wizard, `/status` system status view, `/legal/terms`, `/legal/privacy`, `/legal/dpa`, plus `/settings` Billing & Quotas / GDPR Privacy Export & Erasure tabs, and `/developer` Service Accounts + Webhook Deliveries + Worker Outbox DLQ controls.

---

## 2. Build Verification & Remaining Frontend Gaps

- **Verified (`498043e`):**
  - `npm run lint`: `✔ No ESLint warnings or errors`
  - `npm test` (`tests/format.test.mjs`): `3 passed, 0 failed`
  - `node --test tests/console_e2e_journeys.test.mjs`: `7 passed, 0 failed`
  - `npm run build` (`next build`): `✓ Compiled successfully`, `✓ Linting and checking validity of types`, generated **`24` static/dynamic pages** across `19` app pages + `6` `/api/*` routes.
- **Remaining Gaps:**
  1. **Live Browser Playwright Execution (`NOT VERIFIED`):** `apps/web/tests/playwright_e2e_journeys.spec.ts` exists (`90` lines), **but `@playwright/test` is not listed in `apps/web/package.json`** and no real Chromium browser test has run against live `next start` + `aegis_api`.
  2. **M2 Backend Dependency:** While the UI now sends `approved: false`, calls `PATCH /passports`, `/disputes/.../resolve`, & `/payments/.../refund`, those actions depend on **Computer 2 (`work/m2`)** landing before end-to-end backend execution succeeds!
