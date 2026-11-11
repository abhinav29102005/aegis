# 09 — Infrastructure, Deployment & Android Staging Audit

**Scope:** `services/api/Dockerfile`, `services/worker/Dockerfile`, `apps/web/Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `Makefile`, Host Architecture Analysis (including OPPO / Termux / Debian PRoot candidate staging).

---

## 1. Container, Compose & CI Deployment Audit

| Area | Evidence Observed (`VERIFIED IN CODE`) | Severity | Gap & Required Fix |
| :--- | :--- | :--- | :--- |
| **Compose Env Var Mismatch** | `docker-compose.yml:51-53,89` configures `JWT_SECRET`, `EVIDENCE_STORAGE_DIR: /var/lib/aegis/evidence`, `RATE_LIMIT_RPM`. `NexusSettings` (`settings.py:32-52`) reads `NEXUS_JWT_SECRET`, `AEGIS_EVIDENCE_STORAGE_DIR`, `AEGIS_RATE_LIMIT_RPM`. | **HIGH** | Uploaded dispute artifacts silently go to ephemeral container dir `./var/aegis-evidence` instead of named volume `aegis_evidence_data`; `JWT_SECRET` & `RATE_LIMIT_RPM` ignored! Fix `NexusSettings` or `docker-compose.yml`. |
| **Root Containers (API & Worker)** | `services/api/Dockerfile:1-24` & `services/worker/Dockerfile:1-19` lack `USER` directive (run as `root`); `apps/web/Dockerfile:21,24` properly switches to `nextjs:nodejs`. | **MEDIUM** | Add dedicated unprivileged `USER aegis` in both Python Dockerfiles. |
| **Unpinned Image Digests & Non-Deterministic `npm install`** | `python:3.12-slim`, `node:22-alpine`, `postgres:16-alpine`, GitHub Actions (`@v4/@v5`) lack `@sha256:` pins; `apps/web/Dockerfile:4` uses `npm install` instead of `npm ci`. | **MEDIUM** | Use `npm ci` in `apps/web/Dockerfile`; pin base image & Action digests; add Docker build/smoke test to `.github/workflows/ci.yml`. |
| **Worker Healthcheck & Graceful Shutdown** | `services/worker/Dockerfile` has zero `HEALTHCHECK`; `main.py` logs unstructured text and dies on unhandled `SQLAlchemyError`; Compose does not set `APP_ENV=production` cleanly or TLS termination (reverse proxy / Nginx / Caddy / Traefik missing). | **MEDIUM** | Add file-heartbeat or lightweight HTTP health probe for worker; place TLS reverse proxy + non-public Postgres port (`127.0.0.1` or internal Docker network only — `compose.yml:11` exposes `5432` to `0.0.0.0`!). |
| **Backups, Metrics, Alerting & Live Compose Run** | Zero backup/restore scripts (`scripts/` empty); zero Prometheus/OTel metrics/alerts; **full `docker compose up` build/boot is `NOT VERIFIED`** in repo/CI (only PG16 container ran in CI & local test). | **HIGH** | Add Compose CI smoke test + pg_dump/WAL backup automation + OTel/Prometheus `/metrics` + alert rules before staging/beta. |

---

## 2. OPPO / Termux / Debian PRoot Android Staging Evaluation (Phase C5)

**Verification Status:**
- **Local Machine Hardware Observed:** Host inspected is **`x86_64`, `20` cores, `15 GiB RAM` (with `7.8/8.0 GiB` swap in use)** — **NOT** the OPPO ARM64 phone.
- **Repository Check:** Zero documentation, setup scripts, systemd/supervisord units, Cloudflare Tunnel (`cloudflared`), or Tailscale deployment manifests for OPPO/Termux/PRoot exist anywhere in the repo (`ABSENT`). `cloudflared` and `tailscale` binaries exist on this Linux host (`/usr/local/bin/cloudflared`, `/usr/bin/tailscale`), and `uv.lock` contains `arm64`/`aarch64` wheels (plus `android_24_arm64_v8a` for `charset_normalizer`, `markupsafe`, `xxhash`). Live runtime execution on the OPPO Android device itself is **`BLOCKED / NOT VERIFIED`** in this audit.

### Technical Constraint Assessment for OPPO + Termux + Debian PRoot

1. **ARM64 & Runtime Compatibility:** Python 3.12 (`uv`), Node 22, FastAPI, and Next.js 15 run natively on `aarch64` Linux; Debian PRoot provides glibc/FHS compatibility for `manylinux_aarch64` wheels (`psycopg`, `cryptography`, `@next/swc-linux-arm64-gnu`). However, **PRoot intercepts syscalls via `ptrace`/`seccomp`**, adding substantial I/O and CPU overhead (~1.5x–3x latency on SQLite/Postgres fsync, `next build`, and crypto) and breaking standard Docker-in-Termux (no native kernel cgroups/namespaces without rooted custom kernel, so `docker-compose.yml` **cannot run inside unrooted Termux/PRoot**).
2. **PostgreSQL & Database Feasibility:** Running PostgreSQL 16 directly inside Termux/PRoot shares Android internal UFS flash with the phone OS; `ptrace` syscall virtualization + mobile flash wear/fsync latency + Android **LMK (Low Memory Killer)** or ColorOS/OPPO aggressive background battery optimization (**Phantom Process Killer** in Android 12–15 kills Termux child processes exceeding ~32 background processes or CPU/wake thresholds) risks mid-transaction kills and WAL corruption.
3. **Next.js & Worker Memory Pressure:** A concurrent stack (`Postgres` + `FastAPI/uvicorn` + `aegis_worker` + `Next.js standalone server` + `cloudflared` + `tailscaled`) typically needs ~1.5–2.5 GB steady RAM, and `next build` spikes >2 GB RAM — triggering Android LMK on typical 6–12 GB phones under concurrent apps.
4. **Power, Thermal, Reboot & Supervision:** No hardware UPS/redundant PSU beyond phone battery (swelling risk on 24/7 trickle charge), thermal throttling under sustained CPU/build load, no `systemd` inside Termux/PRoot (requires Termux:Boot + custom wake-lock + `runit`/`supervisord` scripts that survive reboot), and residential/mobile NAT instability.
5. **Networking (Cloudflare Tunnel / Tailscale / Pocket Host):**
   - *Cloudflare Tunnel (`cloudflared`)* works cleanly outbound without port-forwarding for exposing HTTP demos/webhooks, though edge caching/WAF rules must be configured carefully and webhook IP allowlisting isn't static.
   - *Tailscale* provides strong WireGuard private mesh access for admin/operator SSH/dashboard testing (reducing public exposure of alpha UI!).
   - *Pocket Host* is aimed at lightweight PocketBase/JS hosting — **unsuitable** for AEGIS's custom FastAPI + PostgreSQL 16 + `SELECT ... FOR UPDATE` + Python worker architecture.

### Infrastructure Hosting Comparison Matrix

| Criterion | 1. Android (OPPO/Termux/PRoot) | 2. Traditional Linux VPS (e.g., Hetzner/DO ARM64) | 3. Managed Container/Cloud (Fly.io/Render/ECS) | 4. Managed PG + Managed App Services (RDS/Neon/Supabase PG + Container API/Worker + Vercel/Container Web) |
| :--- | :--- | :--- | :--- | :--- |
| **Cost** | \$0 marginal | \$6–\$25 / month | \$30–\$100 / month | \$50–\$200+ / month |
| **Docker Compose Support** | **No** (unrooted PRoot lacks cgroups/namespaces) | **Yes (Native Linux kernel)** | Native container orchestration | Native container orchestration |
| **PostgreSQL Durability & `FOR UPDATE` Reliability** | **Poor** (Android LMK / Phantom Process Killer / PRoot ptrace overhead) | **Good** (with automated `pg_dump`/WAL backups) | Moderate (if stateful volume; PG best managed) | **Best** (Automated PITR backups, Multi-AZ failover, TLS, connection pooling) |
| **Process Supervision & Reboot Recovery** | Fragile (requires Termux:Boot + wake-lock) | Strong (`systemd` / Docker `unless-stopped`) | Automatic health-checked restarts | Automatic health-checked restarts & rolling zero-downtime deploys |
| **Production Payment Suitability** | **UNACCEPTABLE (Single point of failure)** | Staging / Early Single-Tenant Beta (with backups) | Good for Early Commercial SaaS | **RECOMMENDED FOR PRODUCTION COMMERCIAL FINTECH** |

### Clear Workload Split Recommendation
- **Safe on OPPO / Termux / PRoot (ONLY if locked behind Tailscale / Cloudflare Access):** Offline local experiments, API smoke demos using ephemeral/resettable DB, single-developer mobile edge lab, or Tailscale-only demo UI preview — **never host PayPal live credentials or real merchant/customer financial data on it**.
- **Must Move to VPS (`>= \$10/mo`) or Managed Cloud + Managed PostgreSQL Immediately:** Any persistent staging shared with testers, CI/CD target, multi-worker outbox testing (`docker compose`), **live PayPal Sandbox webhook receivers**, and **100% of external/paid customer workloads**.

