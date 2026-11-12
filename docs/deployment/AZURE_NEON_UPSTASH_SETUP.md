# Azure, Neon & Upstash Infrastructure Setup Guide

**Document:** `docs/deployment/AZURE_NEON_UPSTASH_SETUP.md`  
**Target:** Azure Ubuntu 24.04 VM, Neon PostgreSQL 18.6, Upstash Redis 8.4  
**Date:** `2026-11-12`  

---

## 1. Architecture Topology

```
                       [ Internet Users / PayPal Webhooks ]
                                       │
                                       ▼ (Port 443 / HTTPS)
                            [ Cloudflare Edge Proxy ]
                                       │
                                       ▼ (Port 80 / HTTP)
                   [ Azure Ubuntu 24.04 LTS VM (20.124.91.36) ]
                                       │
                              [ Nginx v1.24.0 ]
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
               api-staging...:8000            aegis-staging...:3005
             [ aegis-api (FastAPI) ]         [ aegis-web (Next.js 16) ]
                        │
                        ├─────────────────────────────┐
                        ▼                             ▼
      [ Neon Serverless PostgreSQL 18.6 ]    [ Upstash Redis 8.4 ]
      (SSL pooler, AWS us-east-2)            (TLS encrypted, rediss://)
```

---

## 2. Azure VM Configuration

- **OS:** Ubuntu 24.04.5 LTS
- **IP:** `20.124.91.36`
- **SSH Access:** Key-based authentication via RSA 4096-bit `.pem` key (`aegis` user).
- **Swapfile:** 4 GB configured at `/swapfile` to ensure stability during Next.js builds and Docker image compilations.
- **Docker Compose Stack:**
  - Located in `/home/aegis/agentpay-nexus`
  - Managed by Docker Compose v5.7.1
  - Service containers run non-root (`USER aegis`, UID 999).
  - Restart policy: `unless-stopped` across all services.

### Nginx Virtual Hosts (`/etc/nginx/sites-available/aegis`)
```nginx
# API Reverse Proxy
server {
    listen 80;
    server_name api-staging.abhinavkumarsingh.tech;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Web Console Reverse Proxy
server {
    listen 80;
    server_name aegis-staging.abhinavkumarsingh.tech 20.124.91.36 _;

    location / {
        proxy_pass http://127.0.0.1:3005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 3. Neon Managed PostgreSQL Integration

- **Connection URL Format:**
  `postgresql+psycopg://neondb_owner:<PASSWORD>@ep-wandering-breeze-beh1prf3-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require`
- **Connection Pooling:**
  Neon provides built-in PgBouncer pooling on port 5432.
  SQLAlchemy engine configured with:
  - `pool_size=10`
  - `max_overflow=20`
  - `pool_recycle=300`
  - `pool_pre_ping=True`
- **Advisory Locks:**
  `pg_advisory_xact_lock` functions correctly across pooled transaction blocks because locks are session/transaction scoped and released automatically upon `COMMIT` or `ROLLBACK`.

---

## 4. Upstash Managed Redis Integration

- **Connection URL Format:**
  `rediss://default:<PASSWORD>@uncommon-lab-186998.upstash.io:6379`
- **Transport Security:** Requires `rediss://` scheme for TLS encryption.
- **Operational Usage:**
  - Rate Limiter: Bounded sliding window via Redis sorted sets (`ZADD`, `ZREMRANGEBYSCORE`, `ZCARD`). Key hashes use `sha256(token)[:16]` to prevent RAM explosion.
  - Outbox Worker: Distributed task leases with TTL expiration to prevent worker contention.

---

## 5. Security & Isolation Invariants

1. **No Secrets in Git:** All secrets injected via `.env` on host.
2. **Container Security:** Containers execute under unprivileged user `aegis` (UID 999).
3. **Fail-Closed Webhook Verification:** The `/v1/paypal/webhooks` endpoint rejects any unauthenticated or tampered request with `401 Unauthorized`.
4. **Firewall Rules:** Azure Network Security Group (NSG) restricts inbound access to port 22 (SSH), port 80 (HTTP), and port 443 (HTTPS). Database and Redis ports are not exposed on the Azure VM.

