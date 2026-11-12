# 12 — Performance, Scalability & Infrastructure Cost Model

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **3 OF 5 ARCHITECTURAL BOTTLENECKS RESOLVED IN M1 (`REDIS RATE LIMIT`, `CONCURRENT WORKER SEMAPHORE`, `S3/R2 STREAMING STORAGE`, `POOL RECYCLE`, `FOR UPDATE SEQUENCE LOCK`, `PAGINATION`); REMAINING SYNC-DB-ACROSS-PAYPAL-AWAIT BOTTLENECK AWAITS M2.**

---

## 1. Bottleneck Status Matrix (`498043e`)

| Bottleneck Identified at `1be376e` | Status (`498043e`) | Observed Code Evidence |
| :--- | :--- | :--- |
| 1. Global in-process rate-limiter collision & memory growth | **FIXED (`M1`)** | `services/api/aegis_api/rate_limit.py` uses `sha256(token)[:16]`, bounded TTL eviction, and Redis sorted-set backend (verified live in Compose). |
| 2. Synchronous `Session` held open across PayPal `await` network I/O (`guardian_db.py`) | **STILL OPEN (`M2`)** | `packages/database/database/session.py` added `pool_recycle`, `pool_timeout`, and PG statement timeouts (`M1`), **but `guardian_db.py:463,515,558` still awaits M2 to detach DB work around PayPal HTTP calls**. |
| 3. Unlocked `append_financial_event` sequence read & unbounded lists | **FIXED IN `M1` *(Partially awaits `M2`)* ** | `repository.py` now locks sequence allocation with `SELECT ... FOR UPDATE`; M1 routers (`auth_orgs`, `overview`, `webhooks`) added `limit`/`offset` pagination (`guardian_db`/`disputeos_db` pagination awaits M2). |
| 4. Sequential outbox worker HTTP dispatch head-of-line blocking | **FIXED (`M1`)** | `services/worker/aegis_worker/processor.py` executes outbox HTTP deliveries concurrently behind a bounded `asyncio.Semaphore`. |
| 5. RAM-buffered `10 MB` upload & local-only disk (`LocalObjectStorage`) | **FIXED (`M1`)** | `packages/database/database/storage.py` adds streaming size-checked `put_stream(..., max_bytes=10MB)` and `S3ObjectStorage` (S3/R2 + WORM Object Lock); awaiting M2/router wiring in `disputeos_db.py`. |

*(Capacity tiers from Tier 1 `\$25–\$80/mo` through Tier 4 remain unbenchmarked planning estimates; zero load/RPS benchmarks have executed yet — `NOT VERIFIED`.)*
