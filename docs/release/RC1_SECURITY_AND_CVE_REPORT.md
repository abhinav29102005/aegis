# AEGIS RC1 — Security & Dependency CVE Report (`Workstream A`)

**Status:** **VERIFIED LOCALLY (Prod Dependencies `0` Vulnerabilities; AppSec Regressions `20/20` PASS; Non-Root Digest-Pinned Containers)**  
**Branch:** `release/rc1-c1-security-e2e-deploy` (branched from `integration/nexus` @ `ebe4069`)  
**Audit Date:** `2026-11-12`

---

## 1. Python Dependency CVE Remediation (`A1`)

- **Command Executed (Pre-Upgrade):** `uv export --frozen --no-emit-workspace --no-hashes -o /tmp/aegis-reqs.txt && uv run pip-audit -r /tmp/aegis-reqs.txt --desc` -> `11` vulnerabilities across `4` packages.
- **Command Executed (Post-Upgrade):** `uv export --frozen --no-emit-workspace --no-hashes -o /tmp/aegis-reqs-after.txt && uv run pip-audit -r /tmp/aegis-reqs-after.txt` -> **`No known vulnerabilities found` (exit code `0`)**.

| Advisory ID | Package | Baseline Version | Patched Version | Dependency Type | Action Taken (`pyproject.toml` + `uv.lock`) | Post-Upgrade Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `PYSEC-2026-83` | `langgraph` | `0.6.11` | `>=1.0.10` (`1.2.20` installed) | Direct | Upgraded to `langgraph>=1.0.10,<2.0.0` | **VERIFIED LOCALLY (RESOLVED)** |
| `PYSEC-2026-2573`, `PYSEC-2026-2574` | `langgraph-checkpoint` | `3.0.1` | `>=4.1.1` (`4.3.1` installed) | Transitive (`langgraph`) | Resolved cleanly via `langgraph` upgrade | **VERIFIED LOCALLY (RESOLVED)** |
| `PYSEC-2026-2194`, `PYSEC-2026-2575`, `PYSEC-2026-4240` | `langgraph-sdk` | `0.2.15` | `>=0.4.4` (`0.4.14` installed) | Transitive (`langgraph`) | Resolved cleanly via `langgraph` upgrade | **VERIFIED LOCALLY (RESOLVED)** |
| `PYSEC-2026-1845` | `pytest` | `8.4.2` | `>=9.0.3` (`9.2.0` installed) | Direct (`dev`) | Upgraded `pytest>=9.0.3,<10.0.0` + `pytest-asyncio>=1.0.0,<2.0.0` | **VERIFIED LOCALLY (RESOLVED)** |

---

## 2. Node / Frontend Dependency CVE Remediation (`A2`)

- **SDK (`packages/sdk-typescript`):** `npm audit` & `npm audit --omit=dev` -> **`found 0 vulnerabilities`** (`VERIFIED LOCALLY`).
- **Next.js Console (`apps/web`):**
  - `npm audit --omit=dev`: **`found 0 vulnerabilities` (exit code `0`)** after upgrading `next@16.4.6` (resolving all `4` `postcss` High advisories: `GHSA-qx2v-qp2m-jg93`, `GHSA-6g55-p6wh-862q`, `GHSA-fxqj-rqcc-2cmp`, `GHSA-r28c-9q8g-f849`).
  - `npm audit` (including `devDependencies`): **`8 moderate severity vulnerabilities` remaining** — exclusively transitive `minimatch` (`GHSA-g3hv-75wg-m249`) via `@typescript-eslint/*` inside `eslint-config-next@16.4.6` (lint/build-time devDependency only, absent from runtime production bundle; no non-breaking upstream fix in `eslint-config-next@16.4.6`).
  - Post-upgrade checks (`apps/web`): `npm run typecheck` PASS, `npm run lint` (`eslint .` with `eslint.config.mjs`) PASS (`0` errors, `4` warnings), `npm test` `3/3` PASS, `npm run build` (`Next.js 16.4.6 Turbopack`) `23/23` static pages PASS.

---

## 3. Container & CI Security Hardening (`A3`)

- **Dockerfiles (`services/api/Dockerfile`, `services/worker/Dockerfile`, `apps/web/Dockerfile`):**
  - All 3 containers run as non-root (`USER aegis` UID `999` in Python containers; `USER nextjs` UID `1001` with `--chown=nextjs:nodejs` in `apps/web/Dockerfile`).
  - All 3 Dockerfiles are SHA256 digest-pinned (`python:3.12-slim@sha256:5e2bdb1b...` and `node:22-alpine@sha256:1314fb30...`) and use reproducible frozen installs (`uv sync --frozen --no-dev`, `npm ci --no-audit --no-fund`).
  - Added root `.dockerignore` excluding `.git`, `.venv`, `.env*`, `**/node_modules`, `.next`, `postgres-data`, and local DBs from build contexts.
- **`docker-compose.yml`:**
  - Postgres (`127.0.0.1:${POSTGRES_PORT:-5432}:5432`) and Redis (`127.0.0.1:${REDIS_PORT:-6379}:6379`) bound strictly to loopback.
  - Added `security_opt: ["no-new-privileges:true"]` on all 6 services and `cap_drop: ["ALL"]` on `migrate`, `api`, `worker`, `web`.
- **`.github/workflows/ci.yml`:**
  - All GitHub Actions are SHA-pinned; removed `continue-on-error: true` from `pip-audit`; switched Node jobs to `npm ci`; added `aegis-web:ci` build & Trivy (`CRITICAL,HIGH`, `exit-code: "1"`) scan; extended `compose-smoke` to verify `web`.
  - Note: Gitleaks & Trivy CI jobs require GitHub Actions runner execution (`NOT VERIFIED` locally in GitHub Actions UI).

---

## 4. Application Security Regression Suite (`A4`)

- **Test Execution:** `uv run ruff check tests/adversarial/` -> `All checks passed!`; `uv run pytest -v tests/adversarial/` -> **`20 passed in 7.12s`** (`3` in `test_rbac_negative_matrix.py`, `6` in `test_security_adversarial.py`, `11` new regressions in `tests/adversarial/test_rc1_security_regressions.py`).
- **Verified Invariants:**
  1. 6-role RBAC enforcement & GhostPay `GHOSTPAY_SIMULATE` denied (`403`) for `VIEWER` and `AGENT_SERVICE` *(note: `Role.AUDITOR` is intentionally granted `GHOSTPAY_SIMULATE` in `packages/security/security/auth.py:89`)*.
  2. `ADMIN -> OWNER` privilege escalation blocked (`403`).
  3. Cross-case (`404`) & cross-tenant (`403/404`) dispute artifact BOLA rejected (`disputeos_db.py:464-477`).
  4. Inactive user (`USER_INACTIVE` `401`) and revoked service account (`SERVICE_ACCOUNT_INACTIVE` `401`) API-key bypass blocked.
  5. Outbound webhook SSRF (`APP_ENV=production`, `webhook_require_https=True`) blocks metadata, loopback, RFC1918, and non-HTTPS URLs (`422`).
  6. JWT rate-limit bucket isolation across distinct Bearer tokens sharing a `64+` char prefix (`429` isolated to offending token).
  7. Arbitrary `X-Tenant-Id` header rejected (`401`) when `APP_ENV=production` on standalone `guardian/api/router.py`.
  8. Financial approval denial (`approved=False`) sets `REJECTED` & blocks subsequent checkout (`409`).
  9. Cross-intent approval & `QuoteSnapshot` hash substitution rejected (`ApprovalMismatchError`).
  10. Prompt injection & MCP tool privilege boundary verified (`PurchasingCopilot` deterministic fallback + `AegisMCPServer` rejects approve/capture/override).
  11. `signing_secret` omitted from `GET /v1/webhooks/endpoints` & `TenantIsolationError` redacts foreign UUIDs to `<redacted>`.

---

## 5. Remaining Security & Release Notes
- **Third-Party External Penetration Test:** `NOT VERIFIED`.
- **CI Runner (`gitleaks` / `trivy`) Live Run:** `NOT VERIFIED` locally until pushed PR/CI run.
- **Dev-Only `minimatch` (`eslint-config-next@16.4.6`):** `8` moderate `devDependencies` advisories documented above; `0` production runtime vulnerabilities (`npm audit --omit=dev`).

