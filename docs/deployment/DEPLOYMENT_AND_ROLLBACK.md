# Deployment & Zero-Downtime Rollback Runbook

**Document:** `docs/deployment/DEPLOYMENT_AND_ROLLBACK.md`  
**Revision Date:** `2026-11-12`  
**Target:** Azure Ubuntu 24.04 Staging VM (`20.124.91.36`)  

---

## 1. Standard Deployment Procedure

### Prerequisites
- SSH key: RSA private key with permissions `0600`.
- User: `aegis` on `20.124.91.36`.
- Verified Git branch and clean working tree.

### Step-by-Step Deployment
```bash
# 1. Connect to Azure Staging VM
KEY_PATH="<path-to-key>.pem"
ssh -i "$KEY_PATH" aegis@20.124.91.36

# 2. Enter repository directory and fetch target commit
cd ~/agentpay-nexus
git fetch origin
git checkout release/public-beta-candidate
git pull origin release/public-beta-candidate

# 3. Apply non-destructive database migrations
sudo docker compose run --rm migrate

# 4. Build updated service images with Docker Compose
sudo docker compose build api worker web

# 5. Restart services with minimal downtime
sudo docker compose up -d --no-deps api worker web

# 6. Verify health & readiness
curl -f http://127.0.0.1:8000/health
curl -f http://127.0.0.1:8000/ready
curl -f http://127.0.0.1:3005/login

# 7. Check public edge endpoints
curl -f https://api-staging.abhinavkumarsingh.tech/health
curl -f https://api-staging.abhinavkumarsingh.tech/ready
curl -f http://20.124.91.36/login
```

---

## 2. Fast Rollback Procedure

If a deployed release introduces an error, follow this rollback procedure:

### Rollback Steps
```bash
# 1. Connect to VM
ssh -i "$KEY_PATH" aegis@20.124.91.36

# 2. Identify previous stable commit
cd ~/agentpay-nexus
git log --oneline -n 5

# 3. Checkout previous known good commit (e.g. c3289e2)
PREVIOUS_COMMIT="c3289e2"
git checkout "$PREVIOUS_COMMIT"

# 4. Rebuild and restart containers
sudo docker compose build api worker web
sudo docker compose up -d --no-deps api worker web

# 5. Verify rollback health
curl -f http://127.0.0.1:8000/health
curl -f http://127.0.0.1:8000/ready
curl -f http://127.0.0.1:3005/login
```

---

## 3. Database Migration Rollback Guidelines

1. **Non-Destructive Constraint:** Migrations must never drop existing columns or tables in production before code retirement.
2. **Rollback Single Revision:**
   ```bash
   sudo docker compose run --rm api alembic downgrade -1
   ```
3. **Immutability Protection:** The `financial_events` table is protected by PostgreSQL trigger `trg_aegis_prevent_financial_event_mutation`. No migration or script can alter or delete ledger history.

