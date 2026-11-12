# 18 — Audit Evidence Index & Verification Ledger (`2026-11-12` Sync)

**Repository:** `/home/bigboyaks/Projects/agentpay-nexus` (`integration/nexus` @ `498043e`, M1 `d9ab7b8` + M3 `4b5d52f` merged)  
**Baseline Audited Commit:** `integration/nexus` @ `1be376e` / `7829095`

---

## 1. Commands & Runtime Checks Executed Directly on Merged Code

| Check | Exact Command | Observed Result | Classification |
| :--- | :--- | :--- | :--- |
| Branch Sync State | `git fetch --all --prune && git ls-remote origin` | `work/m1-platform-security-infra` (`d9ab7b8`) & `work/m3-web-sdks-qa` (`4b5d52f`) present & merged cleanly (`0` conflicts); **`work/m2-financial-forensics-ai` absent from `origin`** | **VERIFIED** |
| OpenAPI & ORM Inventory | `create_app().openapi()` + `Base.metadata.tables` (`498043e`) | `PATHS=85`, `OPS=96`, `ORM_TABLES=37`, `3` Alembic revisions (`0001`–`0003`) | **VERIFIED** |
| Python Workspace PG16 Suite + Coverage | `AEGIS_TEST_POSTGRES_URL=... uv run pytest --cov=... -q` | **`228 passed, 0 failed, 0 skipped in 23.32s`** (`87%` statement coverage across `10,490` stmts, `1,401` missed) | **VERIFIED BY TEST (`PG16`)** |
| Root QA Harness (`M3` `tests/`) | `AEGIS_TEST_POSTGRES_URL=... uv run pytest tests/ -v` | **`14 passed, 2 failed in 7.44s`** (`test_outbox_lease_claim_concurrency` `60 vs 20` on hardcoded SQLite WAL; `test_openapi_sdk_coverage_gate` `75.0%` Py / `79.2%` TS < `85%`) | **VERIFIED BY TEST (`2 FAILS`)** |
| Python Lint (`ruff`) | `uv run ruff check . --statistics` | **`Found 79 errors`** (`48` F401, `6` I001, `2` F821 `Any` in `test_pagination.py`, `1` S102 `exec`, `1` BLE001 in `coordinator.py`, etc.; M1 files `0` errors) | **VERIFIED (`FAIL`)** |
| TypeScript SDK (`sdk-typescript`) | `npm ci && npm test && npm run build` | **`35 passed` (Vitest `4` files)** + **`3 passed` (Node legacy)** + **`tsc` build PASS** | **VERIFIED BY TEST** |
| Next.js Console (`apps/web`) | `npm ci && npm run lint && npm test && node --test tests/console_e2e_journeys.test.mjs && npm run build` | `0` ESLint warnings/errors; `3/3` unit + `7/7` E2E journey Node tests PASS; `next build` generated **`24` pages** cleanly; zero `localStorage` matches in `src/` | **VERIFIED BY TEST** |
| Playwright Live Browser E2E | Inspection of `apps/web/package.json` + `playwright_e2e_journeys.spec.ts` | Spec file (`90` lines) exists, **`@playwright/test` absent from `package.json`**, not run in browser | **NOT VERIFIED** |
| Live Compose + Redis + PG Backup/Restore (`work/m1` `d9ab7b8`) | `aegis-smoke` Compose + `backup_pitr.sh` + `restore_verify.sh` | `postgres`, `redis`, `api` (`uid=999`), `worker` (`worker_healthcheck=OK`) healthy; `migrate` exit `0`; `/ready` `200`; Redis RL `239->238`; `/metrics` `200`; PITR restore verified `0003_prod_hardening` & `financial_events` trigger | **VERIFIED LIVE (`M1`)** |
| Live PayPal / Stripe / S3 / LLM / VPS | External provider calls | Mocked/stubbed only; live network execution not executed | **NOT VERIFIED** |
