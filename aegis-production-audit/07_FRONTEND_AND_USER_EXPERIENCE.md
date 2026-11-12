# 07 — Frontend & Product Experience Audit (`apps/web/`)

**Status as of `2026-11-12` (`fix/rc1-guardian-deadlock`):** **`HttpOnly` COOKIE BFF, ALL 5 CONTRACT SCREENS, M2 BACKEND WIRING, NEXT.JS 16 (`0` CVEs), 5/5 CHROMIUM PLAYWRIGHT E2E JOURNEYS PASS, & LIVE NEXT.JS CONTAINER RUNNING ON AZURE VM (`20.124.91.36:80`).**  
**Stack:** Next.js `16.4.6`, React `19.0.0`, TypeScript `^5.7.2`, Tailwind CSS `3.4.17`, `lucide-react`

---

## 1. Cross-Cutting Product & Security Fixes Integrated (`apps/web/`)

1. **`HttpOnly` Cookie Session BFF (`GAP-018` CLOSED):** Route handlers (`/api/auth/login`, `/api/auth/signup`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/switch-org`, `/api/proxy/[...path]`) store tokens in `HttpOnly; SameSite=Lax` cookie `aegis_session` (`0` `localStorage` JWT hits in `apps/web/src/`). Protected via `middleware.ts` + security headers (`CSP`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security`).
2. **All 5 Broken Backend Contract Screens Aligned & Now End-to-End Supported by M2 (`GAP-004` CLOSED):**
   - `/payments/[id]`: Capture keys on `activeAttempt?.state === "CAPTURE_PENDING"`, reads `verified_capture?.paypal_capture_id`, `paypal_approval_url`, `approval.decided_at`, and triggers real M2 **Decline (`approved: false`)** & **Refund (`POST /refund`)** routes.
   - `/agents`: Uses `"passports:write"` permission + search/pagination.
   - `/developer` & `/settings`: Uses the 6 canonical `Role`s (`OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`) + Service Accounts, Webhook Deliveries, & Outbox DLQ views.
   - `/ghostpay/replay/[id]`: Displays `occurred_at`, `actor_type`, `actor_id`, `previous_event_hash` + PG-persisted `POST /v1/ghostpay/investigations` & Agent DNA.
   - `/disputes/[id]`: Renders `DisputeAnalysis` (`grounded_summary`, `generated_with_llm`, `citations`, `contradictions`), SLA `response_due_by`, non-synthetic `POST /cases`, real M2 `POST /resolve`, & `/report` export.
3. **Commercial, Onboarding & Legal Surfaces:** `/onboarding` wizard, `/status`, `/legal/terms`, `/legal/privacy`, `/legal/dpa`, and `/settings` Billing & Quotas / Privacy Export & Erasure tabs.

---

## 2. Verification Results & Staging Operational State

- **Verified Code & Tests (`apps/web`):**
  - `npm run typecheck`: PASS (`tsc --noEmit`).
  - `npm run lint`: PASS (`0` errors, `4` warnings).
  - `npm test` (`tests/format.test.mjs`): `3/3` PASS.
  - `node --test tests/console_e2e_journeys.test.mjs`: `7/7` user journeys PASS.
  - `npm run build` (`next build`): **`24` routes across `19` App Router pages + `6` BFF API routes built cleanly**.
  - `npm audit --omit=dev`: **`0` vulnerabilities** (upgraded to `next@16.4.6`).
  - **Live Chromium Playwright (`5/5` PASS in 11.1s):** Executed via `@playwright/test` and `/usr/bin/google-chrome` against real backend + `next start` with zero console/hydration errors.
- **Live Staging Deployment (`20.124.91.36`):**
  - Container `aegis-web` running healthy in Docker on port 3005, exposed by Nginx on port 80.
  - Tested: `curl -s -I http://20.124.91.36/login` -> `HTTP/1.1 200 OK`.
  - Tested: `curl -s -I http://20.124.91.36/` -> `HTTP/1.1 200 OK`.
  - Ready for domain binding: `aegis-staging.abhinavkumarsingh.tech` pre-configured in Nginx.
