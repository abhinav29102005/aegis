# AEGIS RC1 — Synthetic Load & Performance Baseline

**Status:** **MEASURED LOCALLY (PostgreSQL 16 + Single-Worker Uvicorn; 0.0% Error Rate Across All Endpoints Post-Deadlock Remediation)**  
**Branch:** `fix/rc1-guardian-deadlock`  
**Audit Date:** `2026-11-12`  
**Benchmark Script:** [`tests/load/load_benchmark.py`](../../tests/load/load_benchmark.py)

---

## 1. Test Environment & Hardware Caveats

- **Database:** Isolated `postgres:16-alpine` Docker container on `127.0.0.1:55443`, migrated via `alembic -c packages/database/alembic.ini upgrade head` (`0003_prod_hardening`).
- **API Server:** `uvicorn aegis_api.app:create_app --factory --host 127.0.0.1 --port 18011 --log-level warning` (single worker process).
- **Rate Limiter Override:** `RATE_LIMIT_RPM=10000` (set for synthetic load testing so the default `240` RPM sliding-window limiter did not throttle burst traffic).
- **Host Hardware:** `20` logical CPUs (`nproc`), `15Gi` total RAM (`5.7Gi` available during run).
- **Workload Shape:** `50` requests per endpoint at `concurrency=10` and `concurrency=25`, issued by `httpx.AsyncClient` against a single seeded tenant/passport.
- **Endpoint Mapping Note:** In `modules/ghostpay/ghostpay/api/router.py`, payment-scoped replay is mounted at `POST /v1/ghostpay/replay/by-payment/{id}` (called with `{"persist_investigation": false}` so replay exercises full trace reconstruction and deterministic evaluation).
- **Caveats:** Single-process Uvicorn on localhost over Docker bridge networking; results represent single-node development hardware baseline rather than multi-worker production VPS throughput.

---

## 2. Measured Benchmark Results (`requests_per_endpoint = 50`, Post-Remediation on `fix/rc1-guardian-deadlock`)

| Endpoint | Concurrency | Requests | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Error Rate | Status Breakdown |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /health` | 10 | 50 | 6.18 | 11.76 | 15.73 | 1378.21 | 0.0% | `200:50` |
| `POST /v1/guardian/proposals` | 10 | 50 | 124.48 | 325.18 | 364.85 | 63.35 | 0.0% | `201:50` |
| `GET /v1/guardian/payments/{id}` | 10 | 50 | 28.49 | 37.19 | 40.30 | 339.42 | 0.0% | `200:50` |
| `POST /v1/ghostpay/replay/by-payment/{id}` | 10 | 50 | 78.58 | 136.83 | 143.15 | 112.94 | 0.0% | `200:50` |
| `GET /v1/disputeos/cases` | 10 | 50 | 30.97 | 44.67 | 52.16 | 300.49 | 0.0% | `200:50` |
| `GET /health` | 25 | 50 | 10.76 | 30.34 | 31.86 | 1483.37 | 0.0% | `200:50` |
| `POST /v1/guardian/proposals` | 25 | 50 | 306.40 | 690.58 | 776.33 | 60.96 | 0.0% | `201:50` |
| `GET /v1/guardian/payments/{id}` | 25 | 50 | 74.77 | 141.30 | 152.78 | 268.00 | 0.0% | `200:50` |
| `POST /v1/ghostpay/replay/by-payment/{id}` | 25 | 50 | 169.94 | 275.56 | 289.16 | 123.32 | 0.0% | `200:50` |
| `GET /v1/disputeos/cases` | 25 | 50 | 86.05 | 139.82 | 141.46 | 238.96 | 0.0% | `200:50` |

---

## 3. Key Findings & Bottleneck Resolution

1. **Read & Replay Endpoints (`0.0%` Error Rate):**
   - `GET /health` sustained **1,378.21–1,483.37 RPS** (`p95 <= 30.34 ms`).
   - `GET /v1/guardian/payments/{id}` sustained **268.00–339.42 RPS** (`p95 = 37.19 ms` at conc=10, `141.30 ms` at conc=25).
   - `GET /v1/disputeos/cases` sustained **238.96–300.49 RPS** (`p95 = 44.67 ms` at conc=10, `139.82 ms` at conc=25).
   - `POST /v1/ghostpay/replay/by-payment/{id}` sustained **112.94–123.32 RPS** (`p95 = 136.83 ms` at conc=10, `275.56 ms` at conc=25).

2. **`POST /v1/guardian/proposals` Deadlock Eliminated (`98.0%` -> `0.0%` Error Rate):**
   - Prior to `fix/rc1-guardian-deadlock`, same-tenant concurrent bursts hit `psycopg.errors.DeadlockDetected` (`98.0%` error rate, `1.78` / `1.39` RPS) due to `SELECT tenants.id ... FOR UPDATE` in `LedgerRepository.append_financial_event()` conflicting with FK `FOR KEY SHARE` locks on `tenants`.
   - After replacing `tenants FOR UPDATE` with `(tenant_id, correlation_id)`-scoped `pg_advisory_xact_lock` and adding `(tenant_id, idempotency_key)`-scoped `pg_advisory_xact_lock` in `GuardianService.submit_proposal()`, **all `50/50` requests succeeded (`201`) at both `conc=10` (`63.35 RPS`, `p50=124.48 ms`) and `conc=25` (`60.96 RPS`, `p50=306.40 ms`)** with **`0.0%` error rate**. See [`RC1_GUARDIAN_DEADLOCK_REMEDIATION.md`](./RC1_GUARDIAN_DEADLOCK_REMEDIATION.md).

---

## 4. Verification Commands

- `uv run ruff check tests/load/` -> `All checks passed!`
- `uv run python tests/load/load_benchmark.py --base-url http://127.0.0.1:18011 --concurrency 10 25 --requests 50` (executed against isolated `postgres:16-alpine` on `127.0.0.1:55443` + `uvicorn` on `127.0.0.1:18011`, both cleaned up on exit).
