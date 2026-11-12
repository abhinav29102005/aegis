# AEGIS RC1 Failure Injection & Operations Verification

**Branch:** `release/rc1-c2-payments-ops-load`  
**Scope:** Isolated Docker Compose failure-injection exercise (`postgres`, `redis`, `migrate`, `api`, `worker`), worker lease reclamation & DLQ integration tests, `/ready` 503 sanitization, `/metrics` Prometheus exposition, and structured JSON logging.

---

## 1. Isolated Docker Compose Failure-Injection Exercise

### Environment & Isolation
```bash
export COMPOSE_PROJECT_NAME=aegis_fi
export POSTGRES_PORT=55442
export REDIS_PORT=56380
export API_PORT=18010
export WEB_PORT=13010
```
Stack startup and guaranteed cleanup trap:
```bash
trap 'docker compose down -v --remove-orphans || true' EXIT
docker compose up -d --build postgres redis migrate api worker
```

### Observed Verification Results

| Step | Action / Command | Observed Result |
| --- | --- | --- |
| 1. Initial Readiness | `curl -s -w "%{http_code}" http://127.0.0.1:18010/ready` | `HTTP=200` — `{"status":"ready","database":"connected","paypal_configured":false}` |
| 2. Database Outage Injection | `docker compose stop postgres` followed by `GET /ready` | `HTTP=503` — `{"detail":{"error_code":"DB_UNAVAILABLE","message":"Database readiness check failed."}}` (sanitized; no stack trace, host, or DB credentials leaked) |
| 3. Database Recovery | `docker compose start postgres` followed by `GET /ready` | `HTTP=200` — `{"status":"ready","database":"connected","paypal_configured":false}` |
| 4. Worker Healthcheck (Initial) | `docker compose exec -T worker python -m aegis_worker.main --healthcheck` | Exited `0` |
| 5. Worker Kill / Restart & Recovery | `docker compose restart worker` then `docker compose exec -T worker python -m aegis_worker.main --healthcheck` | Exited `0` cleanly after restart |
| 6. Prometheus `/metrics` | `curl -s -D - http://127.0.0.1:18010/metrics` | `content-type: text/plain; version=0.0.4; charset=utf-8` with `aegis_http_requests_total`, `aegis_http_requests_created`, `aegis_http_request_duration_seconds_bucket`, `aegis_http_request_duration_seconds_count`, `aegis_http_request_duration_seconds_sum`, `aegis_http_requests_in_progress` |
| 7. Structured JSON API Logs | `docker compose logs --no-color --tail=30 api` | Emits JSON log lines with `timestamp`, `level`, `logger`, `correlation_id`, and `message` (e.g. `{"timestamp": "2026-11-12T09:58:22.072887+00:00", "level": "INFO", "logger": "aegis.api", "correlation_id": "3641994a-4d71-406c-803c-5010b1aeedff", "message": "GET /ready -> 200"}`) and no secrets |
| 8. Teardown | `docker compose down -v --remove-orphans` (via `EXIT` trap) | All 5 containers (`aegis-api`, `aegis-worker`, `aegis-migrate`, `aegis-redis`, `aegis-postgres`), 3 volumes, and network `aegis_fi_default` removed |

---

## 2. Automated Failure-Injection Integration Tests

Test suite: [`tests/integration/test_rc1_failure_injection.py`](../../tests/integration/test_rc1_failure_injection.py)

### Covered Scenarios
1. `test_worker_lease_expiration_and_reclamation`: Verifies `OutboxWorker.process_outbox_batch` reclaims expired `PROCESSING` outbox leases from a crashed worker and delivers them (`PUBLISHED`, `attempts=1`, `locked_by=None`, `lease_expires_at=None`), while leaving active future leases untouched.
2. `test_worker_dlq_transition_after_max_retries_and_requeue`: Verifies transient `503` webhook failures transition through `RETRY` to `DEAD_LETTER` once `attempts >= worker_max_attempts`, expired leases at `worker_max_attempts - 1` transition to `DEAD_LETTER` with `last_error="WORKER_LEASE_EXPIRED"`, and `PlatformRepository.requeue_dead_letter_outbox` resets a dead-lettered event to `PENDING` for successful delivery after downstream recovery.
3. `test_api_ready_503_sanitization_and_recovery`: Verifies `GET /ready` returns `200` (`database: "connected"`), returns sanitized `503` (`DB_UNAVAILABLE`) without leaking credentials/DSNs/tracebacks when `db_engine.connect()` fails, and recovers to `200` when DB connectivity is restored.
4. `test_api_metrics_prometheus_exposition`: Verifies `GET /metrics` returns `200` with `text/plain` Prometheus exposition format containing `aegis_http_requests_total` and `aegis_http_request_duration_seconds`.

### Verification Commands & Results
```bash
uv run ruff check
# All checks passed!

uv run pytest -v tests/integration/test_rc1_failure_injection.py
# 4 passed in 0.82s
```


---

## 3. Production Staging & Reverse Proxy Audit (`deploy/linux-staging/`)

- **Localhost-Only Port Bindings Fixed (`deploy/linux-staging/docker-compose.prod.yml`):** Added `ports: !override` on `postgres`, `redis`, `api`, and `web` so Compose v2 override merging emits **only** `127.0.0.1` bindings (`5432`, `6379`, `8000`, `3005->3000`), preventing accidental `0.0.0.0` exposure from base `docker-compose.yml`.
- **Fail-Closed Secrets & Verification Defaults:** Added `EMAIL_VERIFICATION_REQUIRED: ${EMAIL_VERIFICATION_REQUIRED:-true}` in `docker-compose.prod.yml`. Verified `docker compose -f docker-compose.yml -f deploy/linux-staging/docker-compose.prod.yml config --quiet` passes with required env vars and fails closed when `NEXUS_SIGNING_SECRET` is omitted.
- **Nginx Reverse Proxy Hardening (`deploy/linux-staging/aegis.nginx.conf`):** Verified HTTP->HTTPS `301` redirect, `TLSv1.2 TLSv1.3`, HSTS preload, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `/metrics` CIDR allowlist (`127.0.0.1`, `10.0.0.0/8`, `deny all`), and added `server_tokens off;`, `limit_req_status 429;`, `ssl_session_timeout 1d;`, and `ssl_session_cache shared:SSL:10m;`.
- **Linux VPS vs OPPO/Termux Staging Boundaries:** `deploy/linux-staging/` provides a `systemd`-supervised Linux VPS stack (`aegis-api.service`) behind Nginx TLS, replacing ad-hoc OPPO/Termux staging. Live VPS deployment, Certbot TLS issuance, `systemd` startup, and `nginx -t` on a remote host remain **NOT VERIFIED** (no SSH target available).
