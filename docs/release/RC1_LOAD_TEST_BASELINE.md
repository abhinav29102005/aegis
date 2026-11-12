# AEGIS RC1 — Synthetic Load & Performance Baseline

**Status:** **MEASURED LOCALLY (PostgreSQL 16 + Single-Worker Uvicorn; Read/Replay 0.0% Error, Concurrent Same-Tenant `POST /v1/guardian/proposals` Deadlock Finding)**  
**Branch:** `release/rc1-c2-payments-ops-load`  
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

## 2. Measured Benchmark Results (`requests_per_endpoint = 50`)

| Endpoint | Concurrency | Requests | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Error Rate | Status Breakdown |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /health` | 10 | 50 | 6.01 | 13.12 | 17.88 | 1188.59 | 0.0% | `200:50` |
| `POST /v1/guardian/proposals` | 10 | 50 | 4549.08 | 10995.27 | 11001.40 | 1.78 | 98.0% | `0:20, 201:1, 500:29` |
| `GET /v1/guardian/payments/{id}` | 10 | 50 | 25.91 | 40.96 | 46.39 | 343.23 | 0.0% | `200:50` |
| `POST /v1/ghostpay/replay/by-payment/{id}` | 10 | 50 | 79.82 | 100.23 | 104.24 | 122.25 | 0.0% | `200:50` |
| `GET /v1/disputeos/cases` | 10 | 50 | 36.01 | 90.96 | 93.79 | 220.69 | 0.0% | `200:50` |
| `GET /health` | 25 | 50 | 15.54 | 24.78 | 28.89 | 1281.95 | 0.0% | `200:50` |
| `POST /v1/guardian/proposals` | 25 | 50 | 12560.83 | 25996.97 | 26005.23 | 1.39 | 98.0% | `0:13, 201:1, 500:36` |
| `GET /v1/guardian/payments/{id}` | 25 | 50 | 65.88 | 100.91 | 120.03 | 294.35 | 0.0% | `200:50` |
| `POST /v1/ghostpay/replay/by-payment/{id}` | 25 | 50 | 180.81 | 255.17 | 370.03 | 117.82 | 0.0% | `200:50` |
| `GET /v1/disputeos/cases` | 25 | 50 | 100.76 | 172.68 | 188.23 | 207.46 | 0.0% | `200:50` |

*(Note: Status `0` indicates client-side `httpx.HTTPError` / timeout while awaiting locked/pooled responses.)*

---

## 3. Key Findings & Bottleneck Analysis

1. **Read & Replay Endpoints (`0.0%` Error Rate):**
   - `GET /health` sustained **1,188.59–1,281.95 RPS** (`p95 <= 24.78 ms`).
   - `GET /v1/guardian/payments/{id}` sustained **294.35–343.23 RPS** (`p95 = 40.96 ms` at conc=10, `100.91 ms` at conc=25).
   - `GET /v1/disputeos/cases` sustained **207.46–220.69 RPS** (`p95 = 90.96 ms` at conc=10, `172.68 ms` at conc=25).
   - `POST /v1/ghostpay/replay/by-payment/{id}` sustained **117.82–122.25 RPS** (`p95 = 100.23 ms` at conc=10, `255.17 ms` at conc=25).

2. **Critical Concurrency Bottleneck on `POST /v1/guardian/proposals` (`98.0%` Error Rate under Same-Tenant Burst):**
   - Under `concurrency=10` and `concurrency=25` against the **same tenant**, only `1` of `50` requests succeeded (`201`), while `29` (conc=10) and `36` (conc=25) returned HTTP `500` and the remainder timed out (`status=0`).
   - **Observed Server Error:** `psycopg.errors.DeadlockDetected: deadlock detected` inside `LedgerRepository.append_financial_event()` (`packages/database/database/repository.py:882`), triggered during `GuardianService.submit_proposal()` (`modules/agentpay-guardian/guardian/domain/service.py:318`) at:
     ```sql
     SELECT tenants.id FROM tenants WHERE tenants.id = %(id_1)s::UUID FOR UPDATE
     ```
   - **Mechanism:** Concurrent transactions acquire row/key-share locks on `spending_passports` / FK-referenced `tenants` rows in conflicting order before `append_financial_event()` attempts `SELECT ... FROM tenants ... FOR UPDATE` to serialize the tenant's hash-chained audit log, resulting in PostgreSQL deadlock detection (`500`) and connection pool / lock-wait exhaustion (`status=0`).
   - **Recommendation (Outside Load-Test Scope):** Acquire the tenant-level `FOR UPDATE` lock (or advisory transaction lock `pg_advisory_xact_lock`) **at the start** of the write transaction before locking `spending_passports` or inserting FK rows, and/or increase SQLAlchemy `pool_size`/`max_overflow` for high-concurrency deployments.

---

## 4. Verification Commands

- `uv run ruff check tests/load/` -> `All checks passed!`
- `uv run python tests/load/load_benchmark.py --base-url http://127.0.0.1:18011 --concurrency 10 25 --requests 50` (executed against isolated `postgres:16-alpine` on `127.0.0.1:55443` + `uvicorn` on `127.0.0.1:18011`, both cleaned up on exit).
