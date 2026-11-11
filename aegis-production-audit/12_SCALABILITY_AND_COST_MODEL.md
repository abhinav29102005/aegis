# 12 — Performance, Scalability & Infrastructure Cost Model

**Audit Honest Baseline Notice:** Zero load tests or latency benchmarks exist in `/home/bigboyaks/Projects/agentpay-nexus`. The capacity analysis below is strictly derived from static inspection of database indexes, query patterns, locking, worker loops, and frontend bundle builds — **no latency or throughput numbers are fabricated**.

---

## 1. Architectural Bottlenecks & Scaling Limits Observed in Code

1. **In-Process Single-Node Rate Limiter (`services/api/aegis_api/rate_limit.py:22-31`):**
   - Today's global JWT header collision (`tok:eyJhbGciOiJIUzI1Ni`) collapses **the entire multi-tenant user base into ONE `240` rpm limit (~`4` RPS)** across all authenticated JWT users! Even after fixing the key bug, `_buckets` lives in per-process memory (fails across `N` API replicas) and never evicts dead keys (unbounded RSS growth).
2. **Database Connection Pool & Sync FastAPI Route Bottleneck (`packages/database/database/session.py:14-19`):**
   - FastAPI endpoints (`guardian_db.py`, `disputeos_db.py`, `auth_orgs.py`) use **synchronous** SQLAlchemy `Session` (`pool_size=5, max_overflow=10` default = `15` max conns/worker). Calling synchronous DB queries inside `async def` routes vs sync `def` routes: FastAPI runs `def` routes in AnyIO's default 40-thread pool, while `async def` routes (`initiate_checkout`, `execute_capture`, `reconcile_pending` at `guardian_db.py:463,515,558` and `paypal_webhook` at `webhooks.py:161`) hold synchronous `Session` open **across `await` network I/O to PayPal**! Under slow PayPal responses (up to `15s` timeout), just 15 concurrent checkouts/captures exhaust the entire Postgres connection pool!
3. **N+1 / Full-Table Scans & Unindexed/Unbounded Queries:**
   - `SqlAlchemyGhostPayRepository.load_replay_request` (`adapters.py:125`) calls `list_intents(..., limit=200)` sequentially or scans when resolving correlations, and `overview.py:54` loads **all** `financial_events` for a `correlation_id` in RAM for chain verification (`O(E)` per check).
   - Unbounded list endpoints (`/orgs/members`, `/guardian/passports`, `/guardian/agents`, `/guardian/merchants`, `/disputeos/cases`, `/webhooks/endpoints`) serialize entire tenant tables as row counts grow.
   - `append_financial_event` (`repository.py:722-735`) allocates monotonic `sequence_number` per `correlation_id` via `SELECT ... ORDER BY sequence_number DESC LIMIT 1` without lock -> retry storms under parallel bursts on one payment.
4. **Outbox Worker Polling & Head-of-Line Blocking (`services/worker/aegis_worker/processor.py:59-144`):**
   - Polls sequentially (`limit=25` every `2s–5s` -> theoretical ceiling ~`5–12.5` outbox events/sec/worker if webhooks respond in `<1s`), and **processes the `25` claimed HTTP deliveries sequentially in one `for` loop** (`L59`), so 5 slow endpoints (`5s` timeout each) stall a single batch for `25+` seconds!
5. **Artifact & Ledger Growth (`packages/database/database/storage.py` + `orm.py`):**
   - `disputeos_db.py:281-285` buffers up to `10 MB` per upload in FastAPI RAM (`await file.read()`) and writes to local container filesystem (`LocalObjectStorage`) — incompatible with horizontal stateless API/worker replicas unless shared NFS/EFS is mounted or migrated to **S3/R2/GCS pre-signed object storage**.
   - `financial_events` and `outbox_events` (`PUBLISHED` rows never pruned/archived) grow unboundedly without Postgres time-partitioning or archival.

---

## 2. Explicit Workload Modeling Across 4 Tenant Tiers

### Explicit Workload Assumptions per Active Organization (Monthly)
*(Assumptions declared explicitly for capacity planning, NOT measured metrics):*
- Each active org averages: `5` active agents, `2,000` spend proposals/month (~`1,000` PayPal checkouts/captures), generating ~`5` financial/outbox events per payment = `10,000` events/org/month + `20` DisputeOS cases/month (`2` artifacts avg `1.5 MB` each = `60 MB`/org/month) + `500` GhostPay replays/month. Peak traffic factor = `10x` average (bursts inside business/agent-cron hours).

| Scale Tier | Active Orgs | Est. Proposals / Month | Peak RPS (10x burst) | Monthly Ledger Rows (`financial_events` + `outbox`) | Est. Storage / Year (DB + Evidence) | Architectural Changes Required | Indicative Monthly Cloud Infra Estimate *(Unbenchmarked Planning Range)* |
| :--- | ---: | ---: | ---: | ---: | :--- | :--- | :--- |
| **Tier 1** | **10** | 20k | ~0.1–1 RPS | ~200k rows/mo | ~1 GB DB / ~7 GB Evidence | Single VPS or 1 API + 1 Worker + Managed PG; fix rate-limit key & async DB/HTTP boundary | \$25–\$80 / mo (1–2 vCPU VPS + small Managed PG) |
| **Tier 2** | **100** | 200k | ~1–8 RPS | ~2M rows/mo | ~10 GB DB / ~72 GB Evidence | Redis rate limiting + S3 object storage (drop local disk!) + parallel worker HTTP dispatch + PgBouncer | \$150–\$400 / mo (2x API containers, 2x Workers, PG 4GB, Redis, S3) |
| **Tier 3** | **1,000** | 2M | ~10–80 RPS | ~20M rows/mo | ~100 GB DB / ~720 GB Evidence | Monthly Postgres partitioning (`financial_events`, `outbox_events`), async SQLAlchemy (`psycopg` async) or decoupled checkout queue so PayPal I/O never holds DB connections, read replica for GhostPay/Overview | \$1,200–\$3,000 / mo (Autoscaling ECS/EKS, Multi-AZ PG 16-32GB, Read Replica, Redis, S3, OTel) |
| **Tier 4** | **10,000** | 20M | ~100–800 RPS | ~200M rows/mo | ~1 TB+ DB / ~7.2 TB Evidence | Sharded/partitioned event store or ClickHouse/Timescale analytics sink for Overview/Agent DNA, dedicated webhook egress fleet with SQS/Kafka-style partitioned workers, tenant rate quotas | \$8,000–\$20,000+ / mo |

---

## 3. Targeted Performance Recommendations (Avoid Premature Microservices)
Do **not** split into microservices before Tier 3 — today's `API + Worker + Postgres + Next.js` modular monolith is the ideal topology. Prioritize:
1. **Release DB connection before `await` PayPal HTTP calls** inside `initiate_checkout`, `execute_capture`, `reconcile_pending`.
2. **Add composite indexes & pagination** on `(tenant_id, occurred_at)`, `(tenant_id, state, created_at)` + `limit`/`offset` across every list route.
3. **Move `LocalObjectStorage` -> S3/MinIO/R2 abstraction** before running >1 API container.
4. **Add Redis** for sliding-window rate limiting + JWT revocation blocklist.
5. **Parallelize worker outbox batches** with bounded `asyncio.Semaphore(10)` + per-endpoint circuit breakers so one slow customer webhook cannot head-of-line block other tenants.

