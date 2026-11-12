# 07 — Frontend & Product Experience Audit (`apps/web/`)

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):** **`HttpOnly` COOKIE BFF, ALL 5 CONTRACT SCREENS, M2 BACKEND WIRING (`/approve` DECLINE, `/refund`, `/cases`, `/resolve`), & COMMERCIAL/LEGAL PAGES BUILT & PASSING NODE TESTS; LIVE CHROMIUM PLAYWRIGHT + LIVE `web` COMPOSE BOOT STILL `NOT VERIFIED`.**  
**Stack:** Next.js `15.5.29` (`next: ^15.1.6`), React `19.0.0`, TypeScript `^5.7.2`, Tailwind CSS `3.4.17`, `lucide-react`

---

## 1. Cross-Cutting Product & Security Fixes Integrated (`apps/web/`)

1. **`HttpOnly` Cookie Session BFF (`GAP-018` CLOSED):** Route handlers (`/api/auth/login`, `/api/auth/signup`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/switch-org`, `/api/proxy/[...path]`) store tokens in `HttpOnly; SameSite=Lax` cookie `aegis_session` (`0` `localStorage` JWT hits in `apps/web/src/`). Protected via `middleware.ts` + security headers (`CSP`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`).
2. **All 5 Broken Backend Contract Screens Aligned & Now End-to-End Supported by M2 (`GAP-004` CLOSED):**
   - `/payments/[id]`: Capture keys on `activeAttempt?.state === "CAPTURE_PENDING"`, reads `verified_capture?.paypal_capture_id`, `paypal_approval_url`, `approval.decided_at`, and triggers real M2 **Decline (`approved: false`)** & **Refund (`POST /refund`)** routes.
   - `/agents`: Uses `"passports:write"` permission + search/pagination.
   - `/developer` & `/settings`: Uses the 6 canonical `Role`s (`OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`) + Service Accounts, Webhook Deliveries, & Outbox DLQ views.
   - `/ghostpay/replay/[id]`: Displays `occurred_at`, `actor_type`, `actor_id`, `previous_event_hash` + PG-persisted `POST /v1/ghostpay/investigations` & Agent DNA.
   - `/disputes/[id]`: Renders `DisputeAnalysis` (`grounded_summary`, `generated_with_llm`, `citations`, `contradictions`), SLA `response_due_by`, non-synthetic `POST /cases`, real M2 `POST /resolve`, & `/report` export.
3. **Commercial, Onboarding & Legal Surfaces:** `/onboarding` wizard, `/status`, `/legal/terms`, `/legal/privacy`, `/legal/dpa`, and `/settings` Billing & Quotas / Privacy Export & Erasure tabs.

---

## 2. Verification Results & Remaining Frontend Gates

- **Verified Post-Edit (`apps/web`):**
  - `npm run typecheck`: PASS (`tsc --noEmit`).
  - `npm run lint`: PASS (`✔ No ESLint warnings or errors`).
  - `npm test` (`tests/format.test.mjs`): `3/3` PASS.
  - `node --test tests/console_e2e_journeys.test.mjs`: `7/7` user journeys PASS.
  - `npm run build` (`next build`): **`24` routes across `19` App Router pages + `6` BFF API routes built cleanly**.
  - Cross-stack API/UI harness (`tests/e2e/test_console_journeys_e2e.py` against FastAPI ASGI): PASS inside full `313 passed` suite.
- **Remaining Gaps (`NOT VERIFIED` / Advisory):**
  1. **Live Chromium Playwright Execution (`NOT VERIFIED`):** `apps/web/tests/playwright_e2e_journeys.spec.ts` (`90` lines) still has no `@playwright/test` dependency in `apps/web/package.json` and has not run inside a live browser against `next start` + `aegis_api`.
  2. **Next.js Security Advisory (`npm audit --omit=dev`):** Reports **`2` vulnerabilities (`1` moderate, `1` high)** in transitive `postcss` under `next@15.5.29` (fix available via `next@16.4.6`).
  3. **Compose `web` Container (`NOT VERIFIED`):** `make compose-smoke` boots `postgres`, `redis`, `migrate`, `api`, and `worker`; live `docker compose up web` health remains `NOT VERIFIED`.
