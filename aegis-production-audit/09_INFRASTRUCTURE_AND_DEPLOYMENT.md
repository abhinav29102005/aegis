# 09 — Infrastructure, Deployment & Staging Audit

**Status as of `2026-11-12` (`integration/nexus`, Post-M1+M2+M3):** **FULL-STACK MERGED IMAGES (`migrate`, `api`, `worker`, `postgres`, `redis`) VERIFIED LIVE VIA `make compose-smoke` POST-INTEGRATION (`exit 0`); PITR BACKUP/RESTORE VERIFIED IN M1; LIVE CLOUD/VPS & `pip-audit` CVES REMAIN PRE-LAUNCH GATES.**

---

## 1. Container, Compose, CI & Staging Deployment Audit

| Area | Baseline (`1be376e`) | Integrated Verified State (`2026-11-12`) | Remaining Gap |
| :--- | :--- | :--- | :--- |
| **Compose Env Mapping (`GAP-006`)** | `JWT_SECRET`, `RATE_LIMIT_RPM`, `EVIDENCE_STORAGE_DIR` ignored | **CLOSED & VERIFIED LIVE:** `settings.py` supports legacy names + `AEGIS_`/`NEXUS_` aliases; verified in live Compose smoke after full merge. | None |
| **Non-Root Python Containers & Merged Build (`GAP-021`)** | `api` & `worker` ran as `root` | **CLOSED & VERIFIED LIVE (`make compose-smoke`):** Rebuilt `migrate`, `api`, & `worker` from integrated `M1+M2+M3` tree (`USER aegis` `uid=999`, `UV_CACHE_DIR`), `migrate` (`0003`) exited `0`, `GET /ready` returned `{"status":"ready","database":"connected","paypal_configured":false}`. | Live Compose boot of optional `web` container not in `compose-smoke` (`NOT VERIFIED`) |
| **Worker Healthcheck & Postgres Binding (`GAP-021`)** | No worker healthcheck; Postgres `0.0.0.0:5432` | **CLOSED & VERIFIED LIVE:** `docker compose exec -T worker python -m aegis_worker.main --healthcheck` exited `0` post-merge; Compose Postgres binds `127.0.0.1:${POSTGRES_PORT:-5432}:5432`. | None |
| **Backups, PITR & Restore Drill (`GAP-020`)** | Zero backup/restore scripts | **VERIFIED LIVE (`M1`):** `scripts/backup_pitr.sh` + `scripts/restore_verify.sh` verified against PG dump (`alembic 0003` + immutability trigger active). | Live remote S3/R2 bucket upload `NOT VERIFIED` without credentials |
| **Observability & Linux VPS Staging (`GAP-021`)** | Zero metrics/alerts/deploy manifests | **ADDED & CLEAN:** Prometheus `/metrics`, OTel spans, `deploy/observability/{grafana-dashboard.json,prometheus-alerts.yml}`, `deploy/linux-staging/` (`docker-compose.prod.yml`, Nginx, systemd, cron, EU/IN/US envs). | Live Linux VPS / Alertmanager webhook runtime `NOT VERIFIED` |
| **CI Pipeline & Supply Chain (`GAP-023`)** | Unpinned actions; no `pip-audit`/`pytest-cov`/Compose | **HARDENED (`M1` + Sync):** SHA-pinned GitHub Actions, `pytest-cov`, `pip-audit`, `gitleaks`, `trivy`, Compose smoke, & root `pyproject.toml` `testpaths` now includes `"tests"`. | **`pip-audit`** flags `11` upstream CVEs (`langgraph 0.6.11`, `langgraph-checkpoint 3.0.1`, `langgraph-sdk 0.2.15`, `pytest 8.4.2`); **`apps/web` `npm audit --omit=dev`** flags `2` transitive `postcss` CVEs |

---

## 2. OPPO / Termux / PRoot Staging Retirement & Live Smoke Notes
- Android / OPPO / Termux / PRoot remains formally retired in `deploy/linux-staging/README.md` due to Phantom Process Killer, PRoot syscall overhead, and absence of Docker cgroups/namespaces; staging/production deployments target the Linux VPS / Managed Cloud topology.
- Note on host port override during local multi-project verification: `POSTGRES_PORT=55432 REDIS_PORT=56379 API_PORT=18000 make compose-smoke` ran cleanly on host where `5432`/`6380` were already occupied by unrelated non-AEGIS containers.
