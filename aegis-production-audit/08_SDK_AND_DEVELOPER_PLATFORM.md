# 08 — SDK & Developer Platform Assessment

**Scope:** `packages/sdk-python/`, `packages/sdk-typescript/`, `docs/sdk/INTEGRATION_GUIDE.md`, OpenAPI coverage (`69` paths / `78` operations).

---

## 1. Feature & Readiness Comparison Matrix

| Dimension | `aegis-sdk` (Python — `packages/sdk-python/`) | `@aegis-platform/sdk` (TS — `packages/sdk-typescript/`) | Production Target |
| :--- | :--- | :--- | :--- |
| Runtime / Async Support | Sync only (`httpx.Client` `client.py:48`); **no `AsyncAegisClient`** | Async (`Promise` over `fetch` `src/index.ts:97`); webhook helper requires Node `node:crypto` (`L1`, breaks browsers/Edge) | Async+Sync (Py); universal WebCrypto (TS) |
| **API Endpoint Coverage** | **`10 / 78` operations (`12.8%`)** | **`20 / 78` operations (`25.6%`)** | >= 85% coverage + generated OpenAPI types |
| Type Safety | Poor (`dict[str, Any]` returns; `pydantic` dep declared but unused; no `py.typed`) | Weak (`Record<string, unknown>` on most methods; only 3 interfaces) | Full typed models from canonical OpenAPI |
| Error Modeling | Parses `detail.message` + `message` (`client.py:121-123`) | **BUG (`HIGH`, `src/index.ts:156-160`):** ignores FastAPI `detail.message` -> falls back to `"Forbidden"`/`"Bad Request"` | Typed `AegisAPIError(code, message, detail, correlationId)` |
| Retries / Backoff | **None** | **None** | Idempotent GET/retry-safe POST exponential jitter backoff |
| Timeouts | `15.0s` default (`client.py:41`) | **None** (no `AbortSignal.timeout`) | Configurable per-request timeout |
| Pagination Helpers | **None** (`offset` omitted on `list_investigations`) | Partial (`offset` on `listPayments` only; no paginator iterator) | Cursor/offset auto-pagination iterators |
| Approval Reject Support | **Broken** (`approve_proposal` hardcodes `approved=True`) | **Broken** (`approveProposal` hardcodes `approved: true`) | Explicit `approved: bool` + decline methods |
| **Webhook Signature Contract** | Expects `X-AEGIS-Signature: sha256=<hex>` over sorted JSON dict (`L23-28`, **no timestamp/raw bytes**) | Expects `X-AEGIS-Signature: sha256=<hex>` (`L71-83`, **no timestamp/raw bytes**) | **Crashes against `docs/sdk/INTEGRATION_GUIDE.md`!** (`INTEGRATION_GUIDE.md:107` calls `max_age_seconds=300` & `AEGIS-Signature: t=...,v1=...`, causing immediate `TypeError`) |
| Package Publishing Metadata | Missing `README.md`, `license`, `authors`, `urls`, `classifiers`, examples | Missing `README.md`, `files`, `license`, `repository`, `author`, examples | Complete PyPI & npm package metadata + changelogs |

---

## 2. Critical Integration Blocker: External Developer Journey Without Reading Backend Source

**Verdict: AN EXTERNAL DEVELOPER CANNOT INTEGRATE AEGIS WITHOUT READING BACKEND SOURCE OR FAILING IN PRODUCTION.**
Four traps guarantee integration failure from docs alone:
1. **`INTEGRATION_GUIDE.md` crashes verbatim on Python & TS SDK calls:**
   - Doc (`L76`) passes `orgId` to `new AegisClient(...)`, actual constructor (`src/index.ts:19`) expects `organizationId`.
   - Doc (`L46`, `L61`, `L79`, `L93`) calls `submit_proposal`, `replay_payment`, `issue_api_key`, `submitProposal`, `replayPayment` — actual SDK methods are `submit_purchase_proposal`, `replay_by_payment`, **no `issue_api_key` exists**, `submitPurchaseProposal`, `replayByPayment`.
   - Doc (`L103-122`) instructs parsing `AEGIS-Signature: t=...,v1=...` with `secret=..., payload=raw_bytes, max_age_seconds=300` — worker sends `X-AEGIS-Signature: sha256=...` and both SDK signatures reject `max_age_seconds` / `secret` / raw bytes (`TypeError`).
2. **Missing complete lifecycle in Python SDK:** A Python LangGraph developer cannot even call `capture_payment`, `buyer_approved`, `reconcile_payment`, `create_agent`, `create_merchant`, `create_passport`, `create_dispute`, or `submit_dispute` via `aegis-sdk` (`10/78` ops).
3. **Hidden role names (`INTEGRATION_GUIDE.md:42`):** Guide passes `role="AGENT_RUNTIME"` which fails HTTP `422` (`Role.AGENT_SERVICE`).

---

## 3. Proposed Honest Quick-Start Developer Journey (Post-Fix Target)
1. **Provision & Key:** Developer signs up -> issues scoped `AGENT_SERVICE` API key (`aegis_live_...` / `aegis_test_...`).
2. **Policy Setup:** Register agent (`create_agent`), verify merchant (`create_merchant`), mint `SpendingPassport` with budget, per-tx/daily limits, allowed merchants, and approval threshold (`create_passport`).
3. **Agent Tool Execution:** Inside LangGraph/CrewAI tool, call `client.submit_purchase_proposal(..., idempotency_key=f"step-{run_id}")`:
   - `ALLOW` -> receive `CHECKOUT_READY` -> call `initiate_checkout` -> hand PayPal approval link to user/browser -> call `capture_payment` (or let webhook trigger async capture).
   - `ESCALATE` -> agent yields `AWAITING_APPROVAL`; operator approves or rejects in AEGIS Console; webhook notifies agent workflow to resume or abort.
   - `DENY` -> agent receives structured `reason_codes` + human explanation without touching payment rails.
4. **Post-Payment Forensics & Disputes:** Verify provenance (`replay_by_payment`, `get_audit_events`), run counterfactual policy tuning (`simulate_by_payment`), and auto-assemble dispute evidence packets if a buyer files a claim.

## 4. Minimum Checklist Before Publishing `aegis-sdk` (PyPI) & `@aegis-platform/sdk` (npm)
1. Align worker + SDKs + docs on **one canonical webhook signature contract** (`AEGIS-Signature: t=<unix>,v1=<hmac>` over raw bytes with replay tolerance).
2. Expand endpoint coverage from `13–26%` to `>= 85%` (including `capture`, `buyer_approved`, `buyer_declined`, `reconcile`, `agents/merchants/passports` CRUD, `disputes` full flow, `webhooks`, `audit`, `orgs`).
3. Fix TS error parsing (`detail.message`) and add configurable timeouts + safe retries + `approved: bool` / decline methods.
4. Generate/maintain strict Pydantic models (Py) + full TypeScript `.d.ts` interfaces (TS) synced from OpenAPI schema + `py.typed` + WebCrypto compatibility.
5. Add per-package `README.md`, `LICENSE`, examples, package metadata, and automated SDK-vs-OpenAPI contract tests in CI.

