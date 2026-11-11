# 07 — Frontend & Product Experience Audit (`apps/web/`)

**Stack:** Next.js `15.1.6`, React `19`, TypeScript, Tailwind CSS `3.4.17`, `lucide-react` (`apps/web/package.json`)  
**Build Check Observed:** `npm run typecheck`, `npm run lint` (0 errors), `npm test` (3 format tests), `npm run build` (`14` routes built cleanly).  
**Crucial Caveat:** Next.js builds cleanly **only because there are zero UI/integration/E2E tests and client types silently mask broken backend API contracts.**

---

## 1. Cross-Cutting Product & Security Issues

1. **[CRITICAL] Client/Backend Contract Drift Breaks 5 Core Flows:** UI interfaces in `apps/web/src/lib/api.ts` and page components were authored against outdated enum/field names that no longer match `packages/contracts` / `packages/security`.
2. **[HIGH] JWT Persisted in `window.localStorage` Without Verification (`auth-context.tsx:23,29-50,80-105`):**
   - Stores full bearer JWT in `localStorage["aegis.session.v1"]`, making any future XSS defect equivalent to full session takeover across orgs.
   - On page load, `AuthProvider` never validates the stored token via `GET /v1/auth/me`.
   - `apiRequest()` (`api.ts:204-258`) has **no request timeout (`AbortController`)**, **no retry**, and **no HTTP 401 session expiration eviction**.
   - Org switcher (`AppShell.tsx:144`) fires `void switchOrganization(...)` with no error handling/toast on failure.
3. **[MEDIUM] Accessibility & Responsive Polish Gaps:** Only `/dashboard` uses `.table-wrapper` + `<th scope="col">`; 7 other table pages (`payments`, `payments/[id]`, `ghostpay`, `disputes`, `audit`, `developer`, `settings`) omit `<th scope="col">`; `login/page.tsx:99` uses `role="status"` instead of `role="alert"` on error banners.
4. **[MEDIUM] No Pagination, No Text Search & Hidden Operational Surfaces:** Every list screen fetches fixed limits (`30`/`50`/`100`) with zero next/previous pagination or search input. Multiple implemented backend capabilities (`POST /v1/orgs`, `/v1/orgs/service-accounts`, `PATCH /v1/guardian/passports/{id}`, `DELETE /v1/webhooks/endpoints/{id}`, `GET /v1/webhooks/deliveries`, `GET/POST /v1/worker/outbox`, `POST /v1/disputeos/cases`, `/ghostpay/investigations` create, `/ghostpay/agents/{id}`) have zero UI exposure.

---

## 2. Route-by-Route Truth Table (`14` Built Routes)

| Route | Line Count | Maturity Rating | Observed Contract Mismatches, Broken Controls & UX Findings |
| :--- |---:| :--- | :--- |
| `/` (`src/app/page.tsx`) | 93 | **Rendered** | Auth redirect hub (`/dashboard` vs `/login`), no functional actions. |
| `/login` (`src/app/login/page.tsx`) | 241 | **Functional** | Login & signup work; stores JWT in `localStorage`; error banner uses `role="status"` instead of `role="alert"`. |
| `/dashboard` (`src/app/dashboard/page.tsx`) | 183 | **Fully Integrated** | Matches `GET /v1/overview/metrics` + real budget/dispute/dead-letter counters + accessible `.table-wrapper` (`<th scope="col">`). **No fake metrics.** Needs auto-refresh/401 eviction. |
| `/agents` (`src/app/agents/page.tsx`) | 394 | **Functional (Partially Broken)** | Agent create + status toggle work. **BUG (`HIGH`, L208,363):** Merchant creation & allowlist toggle check `hasPermission("merchants:write")`, which **does not exist** in `packages/security/security/auth.py` (backend requires `"passports:write"`). **Merchant controls NEVER render for any user!** |
| `/passports` (`src/app/passports/page.tsx`) | 313 | **Functional** | Create & revoke work; `allow_unknown_merchants` hardcoded `false`; no `PATCH` policy editor; `loadData` `useCallback` re-fetches all data whenever `agentId` or `selectedMerchantIds` changes (`L52`). |
| `/payments` (`src/app/payments/page.tsx`) | 481 | **Functional (Contract Drift)** | Proposal submit, checkout, approve-only (`approved: true`) work. **BUG (`MEDIUM`, L18-31):** `PAYMENT_STATES` filter lists invalid backend states (`PROPOSED`, `POLICY_EVALUATED`, `BUYER_APPROVED`, `CAPTURE_IN_PROGRESS`, `REJECTED`) and omits `CREATED`, `POLICY_CHECK`, `CAPTURE_PENDING`, `CANCELLED`. No search, pagination, or Reject action. |
| `/payments/[id]` (`src/app/payments/[id]/page.tsx`) | 421 | **Critically Broken (`Functional`)** | **BUG (`CRITICAL`, L235):** Capture button only renders when `intent.state === "BUYER_APPROVED"` — backend transitions to `CAPTURE_PENDING`, so **Capture button is UNREACHABLE!** **BUG (`HIGH`, L49-57,316,360-370):** Reads non-existent `attempt.status`, `attempt.paypal_capture_id`, and `approval.approved_at` (backend uses `state`, `verified_capture.paypal_capture_id`, `decided_at`), rendering `"UNKNOWN"`/`"—"`, and ignores `paypal_approval_url`. No `buyer-declined` or reject controls. |
| `/ghostpay` (`src/app/ghostpay/page.tsx`) | 190 | **Fully Integrated** | Lists DB investigations (`consistency_status`, `drift_detected`) and links to replay page. Lacks pagination, text search, `POST /investigations`, and Agent DNA views. |
| `/ghostpay/replay/[id]` (`src/app/ghostpay/replay/[id]/page.tsx`) | 251 | **Functional (Broken Timeline)** | Replay & counterfactual slider work against `*-by-payment/*`, **but timeline (`L234-244`, `api.ts:157-164`) reads undefined `source`, `actor`, `timestamp`** (backend emits `actor_type`, `actor_id`, `occurred_at`), rendering `( · )` and `—`. |
| `/disputes` (`src/app/disputes/page.tsx`) | 181 | **Functional** | Lists/filters cases & seeds clearly tagged `SYNTHETIC_DEMO` cases; missing non-synthetic `POST /cases` creation form & pagination. |
| `/disputes/[id]` (`src/app/disputes/[id]/page.tsx`) | 538 | **Functional (Broken Analysis UI)** | **BUG (`HIGH`, L25-39,327-357):** Expects `latest_analysis.summary`, `model_used`, `evidence_citations`, `contradictions: [{code, severity, summary}]`, while backend `DisputeAnalysis` emits `grounded_summary`, `generated_with_llm`, `citations`, `contradictions: list[str]`. Summary & contradictions render **blank**! `source_type` hardcoded `"DELIVERY_RECEIPT"` (`L148`); missing `/evidence` JSON form & `/report` export. |
| `/audit` (`src/app/audit/page.tsx`) | 214 | **Functional** | Live audit event + admin audit logs & correlation hash-chain verification (`L50` `api.ts`: `previous_hash` vs backend `previous_event_hash`). No pagination or event_type filter. |
| `/developer` (`src/app/developer/page.tsx`) | 404 | **Broken Defaults (`422`)** | **BUG (`HIGH`, L47,231-234):** Defaults API key role to `"DEVELOPER"` and offers `DEVELOPER`, `AGENT_RUNTIME`, `FINANCE_ADMIN`, `VIEWER` — **3 of 4 return HTTP `422`** (valid roles: `OWNER`, `ADMIN`, `OPERATOR`, `AUDITOR`, `AGENT_SERVICE`, `VIEWER`). Missing webhook disable, deliveries table, worker outbox viewer/requeue, & service accounts. |
| `/settings` (`src/app/settings/page.tsx`) | 284 | **Broken Roles (`422`)** | **BUG (`HIGH`, L20-28,37):** Member invite/role dropdown offers `FINANCE_ADMIN`, `RISK_ANALYST`, `DISPUTE_OPERATOR`, `DEVELOPER`, `AGENT_RUNTIME` (defaults to `RISK_ANALYST`) — **5 of 7 return HTTP `422`!** |

---

## 3. Persona Evaluation
- **Merchant Administrator:** Blocked — cannot add merchants in UI (`merchants:write` bug), cannot invite admins/operators cleanly (`/settings` `422`), cannot capture payments (`/payments/[id]` unreachable button).
- **AI Agent Developer:** Blocked — `/developer` default key role returns `422`; cannot inspect webhook delivery failures or requeue dead-letter outbox events in UI despite backend endpoints existing.
- **Risk Analyst:** Mixed — `/dashboard`, `/audit`, and `/ghostpay` counterfactual simulation work, but replay timeline actor/timestamps render blank and Agent DNA profiling has zero UI.
- **Dispute Operations Analyst:** Blocked — `/disputes/[id]` hides analysis summary & contradictions behind schema mismatch (`summary` vs `grounded_summary`), cannot create real disputes or view deadlines/reports in UI, and submit falsely says `SUBMITTED` without calling PayPal.
- **Enterprise Security Administrator:** Unsatisfied — JWT in `localStorage`, no session management/MFA/SSO UI, no security alerts, broken role taxonomy between docs (`7` roles), UI (`7` roles), and API (`6` roles).

