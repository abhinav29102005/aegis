# 09 — Infrastructure, Deployment & Staging Audit

**Status as of `2026-11-12` (`integration/nexus` @ `498043e`):** **M1 HARDENING COMPLETE & LIVE DOCKER COMPOSE + PG16/18 RESTORE VERIFIED; LINUX VPS MANIFESTS ADDED RETIRING OPPO/TERMUX STAGING.**

---

## 1. Container, Compose, CI & Staging Deployment Audit

| Area | Baseline (`1be376e`) | Current Verified State (`498043e` / M1 `d9ab7b8`) | Remaining Gap |
| :--- | :--- | :--- | :--- |
| **Compose Env Var Mapping (`GAP-006`)** | `JWT_SECRET`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR` ignored | **FIXED & VERIFIED LIVE:** `settings.py` reads both legacy names & `AEGIS_`/`NEXUS_` aliases; Compose `migrate`, `api`, `worker`, `redis` tested live (`aegis-smoke`) | None |
| **Non-Root Python Containers (`GAP-021`)** | `api` & `worker` ran as `root` | **FIXED & VERIFIED LIVE:** Both Dockerfiles run `USER aegis` (`id` inside running containers verified `uid=999(aegis) gid=999(aegis)`) with `UV_CACHE_DIR=/home/aegis/.cache/uv` & `nginx`/`compose` hardening | Ensure M2 preserves clean imports in images |
| **Worker Healthcheck & Postgres Binding (`GAP-021`)** | No worker healthcheck; Postgres bound `0.0.0.0:5432` | **FIXED & VERIFIED LIVE:** Worker runs `python -m aegis_worker.main --healthcheck` (`worker_healthcheck=OK`, zero `RuntimeWarning`); Postgres port bound `127.0.0.1:5432`; Redis service wired in Compose | None |
| **Backups, PITR & Restore Drill (`GAP-020`)** | Zero backup/restore scripts | **FIXED & VERIFIED LIVE:** `scripts/backup_pitr.sh` + `scripts/restore_verify.sh` (auto-matching PG restore image version) tested end-to-end against live Compose Postgres dump (`alembic current: 0003_prod_hardening (head)` & immutability trigger verified) | Live remote S3/R2 bucket upload `NOT VERIFIED` without credentials |
| **Observability & Linux VPS Staging (`GAP-021`)** | Zero metrics/alerts/deploy manifests | **ADDED (`M1`):** Prometheus `/metrics`, OTel spans, `deploy/observability/{grafana-dashboard.json,prometheus-alerts.yml}`, `deploy/linux-staging/{docker-compose.prod.yml,aegis.nginx.conf,aegis-api.service,postgres-backup.cron,env.*.example}` | Live VPS/managed cloud deployment & Alertmanager webhook target `NOT VERIFIED` |
| **CI Pipeline & Supply Chain (`GAP-023`)** | Unpinned actions; no `pip-audit`/`pytest-cov`/Compose smoke | **UPDATED (`M1`):** SHA-pinned GitHub Actions, `pytest-cov`, `pip-audit` (`continue-on-error` for 11 upstream `langgraph`/`pytest` advisories), `gitleaks`, `trivy`, Compose smoke job | Re-sync `ci.yml` with root `tests/` + Ruff clean on M3 |

---

## 2. OPPO / Termux / Debian PRoot Android Staging Retirement Note
- Per M1 `deploy/linux-staging/README.md` (`GAP-021`), **Android / OPPO / Termux / PRoot is formally retired as a staging/production target** due to Android LMK / Phantom Process Killer risks, PRoot `ptrace` syscall overhead, and absence of Docker cgroups/namespaces. All staging/production deployments must target the Linux VPS / Managed Cloud + Managed PostgreSQL topology in `deploy/linux-staging/`.
- Live `aegis_web` Next.js container boot inside `docker-compose.yml` was not part of the `aegis-smoke` backend+worker verification and remains `NOT VERIFIED` via Compose (verified standalone via `npm run build`).
