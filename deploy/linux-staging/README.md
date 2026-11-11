# AEGIS Linux Staging & Production Deployment Pack

This directory replaces ad-hoc Android/OPPO phone staging with a reproducible, systemd-supervised Linux VPS (Ubuntu 24.04 LTS / Debian 12+) deployment behind Nginx TLS.

## Contents

- `docker-compose.prod.yml` — Production Compose override (`127.0.0.1`-only service bindings, fail-closed `:?` secrets, memory limits, log rotation).
- `aegis-api.service` — `systemd` unit supervising the Compose stack.
- `aegis.nginx.conf` — TLS 1.2/1.3 reverse proxy template with HSTS, security headers, rate limiting, and `/metrics` CIDR allowlisting.
- `postgres-backup.cron` & `postgres-backup.sh` — Daily compressed `pg_dump` with SHA-256 verification and optional encrypted S3 upload.
- `env.eu-gdpr.example`, `env.in-dpdpa.example`, `env.us-east.example` — Regional data residency overlays (`AEGIS_DATA_RESIDENCY` + regional S3 Object Lock).

## Quickstart (Ubuntu/Debian VPS)

1. Install Docker Engine (`docker compose` v2+), `nginx`, and `certbot`.
2. Clone the repository under `/opt/aegis/agentpay-nexus`.
3. Choose a regional overlay (`env.us-east.example`, `env.eu-gdpr.example`, or `env.in-dpdpa.example`), copy to `/etc/aegis/.env` (`chmod 600 /etc/aegis/.env`), and generate distinct secrets (`openssl rand -hex 32`) for `NEXUS_SIGNING_SECRET`, `JWT_SECRET`, `NEXUS_API_KEY`, and `POSTGRES_PASSWORD`.
4. Install Nginx TLS config (`deploy/linux-staging/aegis.nginx.conf`) and issue Let's Encrypt certificates with `certbot`.
5. Enable the systemd service and backup cron:
   ```bash
   sudo cp deploy/linux-staging/aegis-api.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now aegis-api.service
   sudo cp deploy/linux-staging/postgres-backup.cron /etc/cron.d/aegis-postgres-backup
   ```
6. Validate readiness and worker health:
   ```bash
   curl -fsS https://api.aegis.example.com/ready
   docker compose -f docker-compose.yml -f deploy/linux-staging/docker-compose.prod.yml exec -T worker python -m aegis_worker.main --healthcheck
   ```
