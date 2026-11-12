# 09 — Infrastructure, Deployment & Staging Audit

**Status as of `2026-11-12` (`fix/rc1-guardian-deadlock`):** **FULL-STACK COMPOSE STACK (`migrate`, `api`, `worker`, `web`, `postgres`, `redis`) VERIFIED VIA `make compose-smoke` AND DEPLOYED LIVE ON AZURE VM (`20.124.91.36`) WITH NGINX REVERSE PROXY, REMOTE NEON PG 18.6, UPSTASH REDIS 7, AND CLOUDFLARE EDGE TLS.**

---

## 1. Container, Compose, CI & Staging Deployment Audit

| Area | Baseline (`1be376e`) | Integrated Verified State (`2026-11-12`) | Remaining Gap |
| :--- | :--- | :--- | :--- |
| **Compose Env Mapping (`GAP-006`)** | `JWT_SECRET`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR` ignored | **CLOSED & VERIFIED LIVE:** `settings.py` supports legacy names + `AEGIS_`/`NEXUS_` aliases; verified in tests, live Compose smoke, and Azure staging. | None |
| **Non-Root Containers & Merged Build (`GAP-021`)** | `api` & `worker` ran as `root` | **CLOSED & VERIFIED LIVE (`make compose-smoke` & Azure VM):** Rebuilt `migrate`, `api`, `worker`, and `web` from integrated tree (`USER aegis` `uid=999`, `UV_CACHE_DIR`), `migrate` (`0003`) exited `0`, `GET /ready` returned `200`, and `aegis-web` running healthy on port 3005. | None |
| **Worker Healthcheck & Postgres Binding (`GAP-021`)** | No worker healthcheck; Postgres `0.0.0.0:5432` | **CLOSED & VERIFIED LIVE:** `docker compose exec -T worker python -m aegis_worker.main --healthcheck` exited `0`; worker healthy on Azure VM; Compose Postgres binds `127.0.0.1:${POSTGRES_PORT:-5432}:5432`. | None |
| **Backups, PITR & Restore Drill (`GAP-020`)** | Zero backup/restore scripts | **VERIFIED LIVE (`M1`):** `scripts/backup_pitr.sh` + `scripts/restore_verify.sh` verified against PG dump (`alembic 0003` + immutability trigger active). | Live remote S3/R2 bucket upload `NOT VERIFIED` without bucket credentials |
| **Observability & Linux VPS Staging (`GAP-021`)** | Zero metrics/alerts/deploy manifests | **CLOSED & VERIFIED LIVE:** Deployed on Azure VM (`20.124.91.36`, Ubuntu 24.04 LTS). Nginx reverse proxy routes `api-staging.abhinavkumarsingh.tech` to `:8000` and `aegis-staging.abhinavkumarsingh.tech` + `20.124.91.36` to `:3005`. `/health` and `/ready` (`paypal_configured: true`) return `200 OK`. | None |
| **CI Pipeline & Supply Chain (`GAP-023`)** | Unpinned actions; no `pip-audit`/`pytest-cov`/Compose | **CLOSED & VERIFIED (`0` CVEs):** SHA-pinned GitHub Actions, `pip-audit`: **`0` vulnerabilities** (resolved all `11` upstream CVEs), `npm audit --omit=dev`: **`0` vulnerabilities** (upgraded to `next@16.4.6`). | None |

---

## 2. Live Azure Staging Topology & Smoke Notes
- **Host:** Azure Ubuntu 24.04 LTS VM (`20.124.91.36`) with 4 GB swapfile.
- **Backend Edge:** `https://api-staging.abhinavkumarsingh.tech` (Cloudflare edge proxy -> Nginx -> FastAPI `:8000`).
- **Frontend Console:** `http://20.124.91.36/login` (Nginx -> Next.js 16 container `:3005`).
- **Database:** Remote managed Neon Serverless PostgreSQL 18.6 with connection pooling and SSL enabled.
- **Redis:** Remote managed Upstash Redis 7 with TLS enabled.
- **PayPal Sandbox:** Live client credentials provisioned and verified (`paypal_configured: true`).
- **Retired Formats:** Android / OPPO / Termux / PRoot formally retired in `deploy/linux-staging/README.md`. Staging and production officially target Linux VPS / Managed Cloud topology.
