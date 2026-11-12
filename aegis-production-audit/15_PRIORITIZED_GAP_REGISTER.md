# 15 — Prioritized Gap Register (`2026-11-12` Full M1 + M2 + M3 Integrated Tracker)

**Integrated Branch:** `integration/nexus` *(merging M1 `d9ab7b8` + M3 `4b5d52f` + M2 `3bbaeb6` + post-merge integration fixes)*

---

## 1. All 26 Baseline Audit Gaps (`GAP-001`..`GAP-026`) — Post-Integration Status

| ID | Gap Summary | Owners | Code / PG16 Status (`2026-11-12`) | Verification Evidence Observed (`integration/nexus`) | Remaining External / Non-Code Gate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GAP-001** | `POST /approve` ignores `request.approved=False` | M2 + M3 | **CLOSED IN CODE** | `guardian_db.py`, `guardian/domain/service.py`, `apps/web`, SDKs, `test_guardian_hardening.py` PASS. | Live Sandbox approval flow |
| **GAP-002** | Missing RBAC on `/v1/ghostpay/*` | M1 + M2 | **CLOSED IN CODE** | Gateway `app.py` + internal `ghostpay/api/router.py` enforce `GHOSTPAY_READ`/`SIMULATE`; `test_rbac_negative_matrix.py` + `test_ghostpay_api.py` PASS. | None |
| **GAP-003** | Outbound webhook SSRF & response reflection | M1 | **CLOSED IN CODE** | `ssrf.py`, `webhooks.py`, `processor.py` (`follow_redirects=False`, IPv4/IPv6 block, status-only error) PASS. | None |
| **GAP-004** | Broken Next.js UI contract screens | M3 + M2 | **CLOSED IN CODE** | All 5 screens aligned; `next lint` `0`, `10` Node tests, `next build` (`24` routes) PASS; M2 backend routes live. | Live Chromium Playwright |
| **GAP-005** | Cross-intent approval reuse & `quote_hash` bypass | M2 | **CLOSED IN CODE** | `approvals/service.py` binds `approval.payment_intent_id == intent.id`; `QuoteSnapshot` enforces unconditional hash & expiry; `test_contracts.py` & `test_security_adversarial.py` PASS. | None |
| **GAP-006** | `.env` / Compose `JWT_SECRET`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR` ignored | M1 | **CLOSED LIVE** | `settings.py` aliases + `validate_security_posture`; verified in tests & live `make compose-smoke`. | None |
| **GAP-007** | Global JWT rate-limit prefix collision & unbounded RAM | M1 | **CLOSED LIVE** | `rate_limit.py` `sha256[:16]` + TTL eviction + Redis sorted-set backend verified. | None |
| **GAP-008** | `ADMIN -> OWNER` escalation & cross-org hijack | M1 | **CLOSED IN CODE** | `auth_orgs.py` blocks `ADMIN->OWNER`, uses invite tokens & email verification/throttling (`test_auth_billing_erasure.py` PASS). | Live SMTP delivery |
| **GAP-009** | `DisputeOS` fake `SUBMITTED` without PayPal `provide-evidence` | M2 | **CLOSED IN CODE (Mocked)** | `PayPalDisputeAdapter` calls `provide-evidence`/`accept-claim` behind `paypal_disputes_api_enabled` + blocks synthetics; `disputeos_db.py` sets `SUBMITTED` only on HTTP 2xx. | Live PayPal Disputes Sandbox |
| **GAP-010** | Outbox lease reaper, `SKIP LOCKED`, DLQ reset, concurrency | M1 + Sync | **CLOSED IN CODE** | M1 leases/`SKIP LOCKED`/DLQ `attempts=0`; post-merge SQLite CAS fix in `platform_repo.py:656-703`; `test_outbox_lease_claim_concurrency` & `test_worker.py` PASS. | Multi-worker live soak |
| **GAP-011** | `PolicyEngine` vs GhostPay `"policy-v1"` parity, daily/agent-status/allowlist | M2 | **CLOSED IN CODE** | Canonical `contracts.policy_v1.evaluate_policy_v1`; **1,000-case property test (`1000/1000`, `0` mismatches)** + agent status/allowlist/daily limits PASS. | None |
| **GAP-012** | PayPal `JPY/BHD` decimals, pre-capture check, timeouts, refunds | M2 | **CLOSED IN CODE (Mocked)** | `contracts` ISO-4217 minor utils in `paypal/client.py`, `CAPTURE_PENDING` pre-check, retries, `POST /refund` (`guardian_db.py:867`); `test_paypal.py` PASS. | **Live PayPal Sandbox (`1 skipped`)** |
| **GAP-013** | GhostPay legacy split-brain, RAM traces/investigations, partial digests | M2 + M1 | **CLOSED IN CODE** | Deleted `timemachine/replay.py` & `forensics/*`; wired `adapters.py` & GhostPay router to PG snapshots/traces/DNA; canonical hashes (`test_forensics_hardening.py` PASS). | None |
| **GAP-014** | Webhook signature contract (`AEGIS-Signature: t=,v1=`) | M1 + M3 | **CLOSED LIVE** | Unified across Worker, `hashing.py`, Py SDK, TS SDK (Node + WebCrypto), & `INTEGRATION_GUIDE.md` (`test_verbatim_integration_guide_*` PASS). | None |
| **GAP-015** | Python & TS SDK parity, `AsyncAegisClient`, `detail` parser | M3 + Sync | **CLOSED IN CODE** | Both SDKs expanded to **`97 / 99` (`98.0%`) OpenAPI ops**; `35/35` Vitest + `3/3` Node + `test_sdk_coverage.py` + parity gate PASS. | PyPI / npm publication |
| **GAP-016** | Proposal/checkout idempotency TOCTOU race & payload equivalence | M2 | **CLOSED IN CODE** | `guardian/domain/service.py:181-208` + `coordinator.py` payload equivalence & reason-code race fix; `test_parallel_payment_proposal_idempotency` PASS. | None |
| **GAP-017** | DisputeOS state guard, `/resolve`, `SEC-06` BOLA, `CUSTOMER.DISPUTE.*`, graph | M2 + M1 | **CLOSED IN CODE** | `DisputeStatus` guard, `POST /resolve`, `disputeos.paypal.webhook_handler`, `disputeos_db.py:464-477` BOLA check, non-Cartesian graph, full-context `normalizer.py`. | Live PayPal dispute webhook delivery |
| **GAP-018** | Error sanitization, active principals, `HttpOnly` cookie BFF | M1 + M3 | **CLOSED IN CODE** | `tenant.py`/routes sanitize errors; `deps.py` checks active users/SAs; Next.js `HttpOnly` cookie BFF + CSP headers verified (`SEC-09` Guardian closed). | Unmounted unit-only `disputeos/api/router.py` cleanup |
| **GAP-019** | Live LLM adapters (`OpenAI`/`Gemini`/`Anthropic`), sanitization, semantic citations | M2 + M1 | **CLOSED IN CODE (Mocked)** | `llm_client.py` (`631` lines) + `llm_invocation_logs` PG persistence + `sanitize_untrusted_text` + semantic `citations.py` (`test_ai_eval.py` PASS). | **Live OpenAI / Gemini / Anthropic API evals** |
| **GAP-020** | PG `financial_events` immutability trigger, `FOR UPDATE` seq, PITR scripts | M1 | **CLOSED LIVE** | Alembic `0003` trigger verified PG16 + live `backup_pitr.sh`/`restore_verify.sh` drill passed in M1. | Remote S3/R2 PITR bucket test |
| **GAP-021** | Non-root containers, healthchecks, `127.0.0.1:5432`, `/metrics`, OTel, Linux VPS | M1 | **CLOSED LIVE** | **`make compose-smoke` PASS post-merge** (`migrate` + `api /ready` + `worker --healthcheck`), Grafana/alerts, `deploy/linux-staging/`. | Live VPS deployment & Compose `web` check |
| **GAP-022** | Session detach across PayPal `await`, S3/R2 WORM, 10MB cap, pagination | M1 + M2 | **CLOSED IN CODE** | `guardian_db.py:728` `_detach_session`, `S3ObjectStorage` WORM, 10MB stream cap, `limit`/`offset` pagination across routers. | Live S3/R2 upload test |
| **GAP-023** | SHA-pinned CI, `pytest-cov`, `pip-audit`, Ruff clean, `tests/` harness in `testpaths` | M1 + M3 + Sync | **CLOSED IN CODE (`pip-audit`/`npm` CVEs tracked)** | **`0` Ruff errors**, `"tests"` in `pyproject.toml`, **`313 passed, 1 skipped` (`90%` cov)**; SHA-pinned CI. | `11` `pip-audit` (`langgraph`/`pytest`), `2` `apps/web` `postcss` CVEs, live Chromium Playwright |
| **GAP-024** | Stripe billing, GDPR/DPDPA export/erasure, `/onboarding`, `/status`, `/legal/*` | M1 + M3 | **CLOSED IN CODE** | `/v1/billing/*`, `/v1/privacy/*`, legal pages, status & runbooks verified by unit/build tests. | **Live Stripe API + Legal counsel review** |
| **GAP-025** | Multi-rail (`Stripe`, `AP2`, `TAP`, `x402`, `Deflection`) & MCP Server | M2 | **CLOSED IN CODE (Mocked)** | `guardian/providers/*` (`test_providers.py`) + `/v1/guardian/mcp` (`test_copilot_mcp.py`, `598` LOC) verified cleanly. | Live Stripe/AP2/TAP/x402 sandbox runs |
| **GAP-026** | `contracts.schema.json` export, `feature/ghostpay` sync, docs/`packages/ui` cleanup | M2 + M3 + Sync | **CLOSED IN CODE** | `export_schemas.py` & updated `contracts.schema.json`; `TEAM_HANDOFF.md` deleted; `rmdir packages/ui` clean. | None |

---

## 2. Remaining Pre-Launch Action List (Non-Code External & Dependency Items Only)
1. **External Sandbox & Provider Execution (`NOT VERIFIED`):** Obtain PayPal Sandbox credentials to run `packages/paypal/tests/test_live_sandbox_optional.py` live (`create -> approve -> capture -> refund -> dispute -> webhook`), plus test-mode Stripe Billing, live LLM evals, remote S3/R2 upload, & SMTP.
2. **Real Browser Playwright (`NOT VERIFIED`):** Install `@playwright/test` in `apps/web/package.json` and run `apps/web/tests/playwright_e2e_journeys.spec.ts` against `next start` + `aegis_api`.
3. **Supply-Chain CVE Updates:** Upgrade `langgraph` (`>=0.4.4+` ecosystem / `langgraph-sdk>=0.4.4`) & `pytest>=9.0.3` for `pip-audit`, and upgrade `next` (`16.4.6`) or transitive `postcss` in `apps/web` before public beta/commercial release.
4. **Ops, Legal & Compliance Sign-Off:** Deploy `deploy/linux-staging/` to target Linux VPS, benchmark RPS load capacity, complete external legal counsel review of `/legal/*` & `DPA`, run external pen-test, and prepare SOC 2 Type II controls.
