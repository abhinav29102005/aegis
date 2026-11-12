# AEGIS — Live Cloud Integration & Beta Release Report

**Release Candidate:** AEGIS Public Beta Candidate  
**Repository:** `https://github.com/abhinav29102005/agentpay-nexus.git`  
**Development & Verification Branch:** `release/public-beta-candidate`  
**Date:** `2026-11-12`  
**Lead Authors:** Staff Payments Architect, Security Engineer, SRE & Release Manager  

---

## 1. Executive Status & Release Gates

| Release Gate | Criteria | Current Result | Verdict |
| :--- | :--- | :--- | :---: |
| **Gate A: Engineering Integrity** | Ruff 0 errors, 354 PG16 pytest pass, 0 P0 deadlocks, 0 CVEs in pip-audit & npm audit | `uv run ruff check .` PASS; `354 passed, 3 skipped, 0 failed`; `pip-audit`: 0 CVEs; `npm audit`: 0 CVEs | **MET** |
| **Gate B: Live Staging Deployment** | Live Azure VM, Nginx reverse proxy, Cloudflare TLS, Neon PG 18.6, Upstash Redis 8.4 | Deployed on `20.124.91.36`; `https://api-staging.abhinavkumarsingh.tech` (`/health` & `/ready` 200 OK); web console on port 80 | **MET** |
| **Gate C: PayPal Sandbox Beta** | Live OAuth, Order creation, capture guard, webhook receiver, signature verification, DB logging | Live OAuth + Orders v2 pass; unapproved capture guard verified; authentic live webhooks delivered and verified | **MET (Pre-Beta)** |
| **Gate D: Commercial Launch** | Live Stripe billing, signed external legal counsel review, formal SOC 2 Type II audit | Stripe test mode implemented (live unrun); legal templates drafted; external audit pending | **PENDING** |

---

## 2. Infrastructure Inventory & Health Check

### Azure Staging Virtual Machine
- **Host:** `20.124.91.36` (Azure Ubuntu 24.04.5 LTS, Kernel `7.0.0-1017-azure`)
- **Containers:**
  - `aegis-api`: FastAPI backend running Uvicorn on port `8000` (healthy).
  - `aegis-web`: Next.js 16 Web console running on port `3005` (healthy, mapped to port 80 by Nginx).
  - `aegis-worker`: Background durable outbox worker processing outbox table (healthy).
  - `aegis-postgres`: Local container present (fallback/test), production traffic routed to Neon.
  - `aegis-redis`: Local container present (fallback/test), production traffic routed to Upstash.
- **Reverse Proxy:** Nginx v1.24.0 routing:
  - `api-staging.abhinavkumarsingh.tech` -> `127.0.0.1:8000`
  - `aegis-staging.abhinavkumarsingh.tech` and `20.124.91.36` -> `127.0.0.1:3005`
- **Edge Routing & TLS:** Cloudflare edge proxy with SSL certificate termination on `api-staging.abhinavkumarsingh.tech`.
- **System Metrics:** Load: `0.63`, RAM: `39%`, Disk: `36.6% of 28 GB`, Swapfile: `4 GB` (6% used).

### Managed Databases
- **Neon PostgreSQL:**
  - Endpoint: `ep-wandering-breeze-beh1prf3-pooler.c-9.us-east-2.aws.neon.tech`
  - Version: `PostgreSQL 18.6` on aarch64
  - Mode: Connection pooling enabled with SSL enforced (`sslmode=require`)
  - Schema: Alembic `0003_prod_hardening` (37 ORM tables)
  - Integrity Triggers: `trg_aegis_prevent_financial_event_mutation` append-only enforcement active
  - Concurrency Lock: `pg_advisory_xact_lock` transaction locks verified functional
- **Upstash Redis:**
  - Endpoint: `uncommon-lab-186998.upstash.io:6379`
  - Version: Redis `8.4.0`
  - Transport: TLS encrypted (`rediss://`)
  - Features: SHA-256 token prefix rate limiting, sorted-set eviction, outbox leases

---

## 3. Subsystem Health & Verification Evidence

### AgentPay Guardian
- **Deadlock Remediation:** P0 table-level lock `SELECT tenants.id ... FOR UPDATE` was replaced with two advisory transaction locks:
  - `pg_advisory_xact_lock(hashtext(tenant_id), hashtext(correlation_id))` for financial event sequencing.
  - `pg_advisory_xact_lock(hashtext(tenant_id), hashtext(idempotency_key))` for proposal idempotency.
- **Concurrency Evidence:** 3 consecutive runs of `tests/concurrency/test_rc1_deadlock_stress.py` passed (`18 passed` × 3).
- **Synthetic Load Benchmark:** `tests/load/load_benchmark.py` achieved **`0.0%` errors across all endpoints** at `c=10` and `c=25` (proposals: `60.96 – 63.35 RPS`).

### GhostPay Forensics
- **Shared Policy Parity:** 1,000-scenario randomized property test between Guardian and GhostPay `"policy-v1"` evaluator passed with **`0` mismatches**.
- **Historical Snapshots:** Replay retrieves historical `spending_passport_snapshots` and matches exact financial event hashes.

### DisputeOS
- **Evidence Contradiction Graph:** Evidence records ingested and analyzed with semantic contradiction detection.
- **Provider Protection:** External disputes require genuine provider webhook confirmation; synthetics blocked from live updates.

### Frontend Web Console
- **Stack:** Next.js 16 (`16.4.6`), React 19, TypeScript 5.7, Tailwind CSS.
- **Security:** `HttpOnly; SameSite=Lax` cookie BFF (`/api/auth/*`), zero JWT storage in `localStorage`.
- **E2E Browser QA:** `apps/web/tests/playwright_e2e_journeys.spec.ts` passed **`5/5` journeys in 11.1s** with 0 console, hydration, or HTTP errors.
- **Live Status:** Responding `200 OK` on `http://20.124.91.36/login` and `http://20.124.91.36/`.
