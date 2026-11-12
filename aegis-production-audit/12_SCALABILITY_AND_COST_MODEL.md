# 12 — Performance, Scalability & Infrastructure Cost Model

**Status as of `2026-11-12` (`fix/rc1-guardian-deadlock`):** **ALL 5 ARCHITECTURAL BOTTLENECKS RESOLVED; P0 DEADLOCK ELIMINATED VIA ADVISORY LOCKS; LOAD/RPS BENCHMARKS EXECUTED WITH `0.0%` ERROR RATE AT `c=10` AND `c=25`.**

---

## 1. Bottleneck Resolution Matrix (Baseline `1be376e` -> Integrated `2026-11-12`)

| Bottleneck Identified at `1be376e` | Status (`2026-11-12` Integrated) | Observed Evidence |
| :--- | :--- | :--- |
| 1. Global in-process rate-limiter collision & memory growth | **CLOSED (`M1`)** | `rate_limit.py` uses `sha256(token)[:16]`, bounded TTL eviction, and Redis sorted-set backend (verified live + unit tests). |
| 2. Synchronous `Session` held open across PayPal `await` network I/O | **CLOSED (`M2`)** | `guardian_db.py:728` calls `_detach_session(http_request, session)` before async `await paypal_client` calls and opens short-lived `db2` session to finalize/record timeout or failure; `session.py` sets `pool_recycle` & `pool_timeout`. |
| 3. Unlocked `append_financial_event` sequence read & `FOR UPDATE` deadlocks | **CLOSED (`fix/rc1-guardian-deadlock`)** | Replaced table-level `SELECT tenants.id ... FOR UPDATE` with `pg_advisory_xact_lock(hashtext(tenant_id), hashtext(correlation_id))` and `pg_advisory_xact_lock(hashtext(tenant_id), hashtext(idempotency_key))`; pagination enforced across routers; 3× PG16 stress runs (`18/18`) PASS. |
| 4. Sequential outbox worker HTTP dispatch head-of-line blocking | **CLOSED (`M1`)** | `services/worker/aegis_worker/processor.py` executes outbox deliveries concurrently behind `asyncio.Semaphore`. |
| 5. RAM-buffered `10 MB` upload & local-only disk (`LocalObjectStorage`) | **CLOSED (`M1+M2`)** | `storage.py` enforces streaming `max_bytes=10MB` & `S3ObjectStorage` (S3/R2 WORM); `disputeos_db.py:368` streams uploads cleanly. |

---

## 2. Synthetic Load & Concurrency Benchmark Results
- **Load Harness:** `tests/load/load_benchmark.py` against PostgreSQL 16.
- **Results:** **`0.0%` error rate across all endpoints** (`50` requests per endpoint at `c=10` and `c=25`).
- **Throughput:** `POST /v1/guardian/proposals`: `63.35 RPS` @ `c=10`, `60.96 RPS` @ `c=25` (100% HTTP 201). Replay and read queries: `112.94` – `1,483.37 RPS`.
- **Latency:** P95 latency remained under 38ms on local PostgreSQL; no connection pool starvation or advisory lock lockouts observed.
