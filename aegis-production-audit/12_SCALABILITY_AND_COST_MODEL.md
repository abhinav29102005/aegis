# 12 — Performance, Scalability & Infrastructure Cost Model

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):** **ALL 5 ARCHITECTURAL BOTTLENECKS IDENTIFIED AT BASELINE (`1be376e`) ARE NOW RESOLVED IN CODE; LOAD/RPS BENCHMARKS REMAIN `NOT VERIFIED`.**

---

## 1. Bottleneck Resolution Matrix (Baseline `1be376e` -> Integrated `2026-11-12`)

| Bottleneck Identified at `1be376e` | Status (`2026-11-12` Integrated) | Observed Evidence |
| :--- | :--- | :--- |
| 1. Global in-process rate-limiter collision & memory growth | **CLOSED (`M1`)** | `rate_limit.py` uses `sha256(token)[:16]`, bounded TTL eviction, and Redis sorted-set backend (verified live + unit tests). |
| 2. Synchronous `Session` held open across PayPal `await` network I/O | **CLOSED (`M2`)** | `guardian_db.py:728` calls `_detach_session(http_request, session)` before async `await paypal_client` calls and opens short-lived `db2` session to finalize/record timeout or failure; `session.py` sets `pool_recycle` & `pool_timeout`. |
| 3. Unlocked `append_financial_event` sequence read & unbounded lists | **CLOSED (`M1+M2`)** | `repository.py` uses `SELECT ... FOR UPDATE`; M1 (`auth_orgs`, `overview`, `webhooks`) & M2 (`guardian_db`, `disputeos_db`, `ghostpay`) enforce `limit`/`offset` pagination cleanly. |
| 4. Sequential outbox worker HTTP dispatch head-of-line blocking | **CLOSED (`M1`)** | `services/worker/aegis_worker/processor.py` executes outbox deliveries concurrently behind `asyncio.Semaphore`. |
| 5. RAM-buffered `10 MB` upload & local-only disk (`LocalObjectStorage`) | **CLOSED (`M1+M2`)** | `storage.py` enforces streaming `max_bytes=10MB` & `S3ObjectStorage` (S3/R2 WORM); `disputeos_db.py:368` streams uploads cleanly. |

*(Tier 1 `\$25–\$80/mo` through Tier 4 cloud cost sizing estimates remain capacity-planning models; synthetic k6/Locust RPS saturation benchmarks have not executed — **`NOT VERIFIED`**.)*
