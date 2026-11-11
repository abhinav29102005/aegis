# Runbook: PostgreSQL Point-in-Time Recovery (PITR)

**Version:** 1.0.0  
**Effective Date:** November 12, 2026  
**Target Environment:** PostgreSQL 16 (AEGIS Canonical Ledger & Multi-Tenant Database)

---

## 1. Overview & Recovery Objectives

AEGIS relies on PostgreSQL 16 as its single source of truth for financial transactions, budget reservations, Spending Passports, and tamper-evident event chains (`FinancialEvent`).

Point-in-Time Recovery (PITR) enables restoring the database to an exact microsecond prior to an adverse event (e.g., accidental table truncation, software defect, or infrastructure failure) without losing transactions committed prior to the target time.

- **Recovery Point Objective (RPO):** < 1 minute (governed by continuous WAL archiving).
- **Recovery Time Objective (RTO):** < 30 minutes for databases up to 100 GB.

---

## 2. Prerequisites & Architecture

PITR requires two data streams:
1. **Periodic Base Backups**: Full file-system copies created with `pg_basebackup` (retained for 30 days).
2. **Continuous WAL Archives**: Continuous Write-Ahead Log (WAL) segments copied via `archive_command` to persistent storage (`/var/lib/postgresql/wal_archive` or dedicated Cloud Storage bucket).

### PostgreSQL 16 Production Archiving Configuration
Ensure these parameters are active in `postgresql.conf`:
```ini
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /var/lib/postgresql/wal_archive/%f && cp %p /var/lib/postgresql/wal_archive/%f'
archive_timeout = 60
```

---

## 3. Step-by-Step PITR Execution Procedure

> [!CAUTION]
> **NEVER RESTORE DIRECTLY OVER A RUNNING PRODUCTION CLUSTER.**  
> Always execute the recovery process in an isolated container or staging host first. Once validated, redirect application traffic.

### Step 1: Determine Recovery Target Timestamp
Identify the exact UTC timestamp $T_{\text{target}}$ prior to the corruption event.
Example: Corrupted migration occurred at `2026-11-12 03:45:22 UTC`. Target time:
$$T_{\text{target}} = \text{'2026-11-12 03:44:00 UTC'}$$

### Step 2: Stop Application Traffic & Drain Workers
Prevent incoming writes from worsening inconsistency:
```bash
# Stop API control plane and workers:
docker compose stop api worker
```

### Step 3: Prepare the Recovery Instance
Provision a dedicated directory or container for recovery:
```bash
mkdir -p /var/lib/postgresql/recovery_data
chmod 700 /var/lib/postgresql/recovery_data
```

### Step 4: Restore the Base Backup
Extract the latest base backup taken *before* $T_{\text{target}}$ into the target directory:
```bash
tar -xvf /var/lib/postgresql/backups/base_backup_20261112_000000.tar -C /var/lib/postgresql/recovery_data
```

### Step 5: Configure Recovery Parameters
In PostgreSQL 16, recovery is signaled via a `recovery.signal` file and configured in `postgresql.auto.conf`:

1. **Create the signal file**:
   ```bash
   touch /var/lib/postgresql/recovery_data/recovery.signal
   ```

2. **Append recovery settings to `postgresql.auto.conf`**:
   ```ini
   # Restore command pulling archived WAL files:
   restore_command = 'cp /var/lib/postgresql/wal_archive/%f %p'
   
   # Exact point in time target:
   recovery_target_time = '2026-11-12 03:44:00 UTC'
   
   # Action upon reaching target (pause allows inspection before promotion):
   recovery_target_action = 'pause'
   ```

### Step 6: Start PostgreSQL in Recovery Mode
Launch the PostgreSQL 16 instance:
```bash
docker run -d --name aegis_pg_recovery \
  -v /var/lib/postgresql/recovery_data:/var/lib/postgresql/data \
  -v /var/lib/postgresql/wal_archive:/var/lib/postgresql/wal_archive:ro \
  -e POSTGRES_PASSWORD=recovery_secret \
  -p 5433:5432 \
  postgres:16-alpine
```

Monitor container logs to observe WAL replay:
```bash
docker logs -f aegis_pg_recovery
```
Look for the confirmation log:
```text
LOG: starting point-in-time recovery to 2026-11-12 03:44:00+00
LOG: redo starts at ...
LOG: consistent recovery state reached at ...
LOG: recovery stopping at restore point or target time 2026-11-12 03:44:00+00
LOG: recovery has paused
```

---

## 4. Data Validation Checklist (Before Promotion)

Connect to the recovery database on port `5433` and execute verification:

### 4.1. Verify Alembic Schema Version
```sql
SELECT version_num FROM alembic_version;
-- Expected output: latest valid revision (e.g., 0002_aegis_platform_extensions)
```

### 4.2. Verify Cryptographic Event Hash Chain Continuity
```sql
-- Check that the most recent financial events have intact previous_event_hash links:
SELECT id, correlation_id, event_type, previous_event_hash, event_hash, created_at
FROM financial_event_rows
ORDER BY created_at DESC
LIMIT 10;
```

### 4.3. Check Budget Reservation Consistency
```sql
-- Confirm no orphan or negative balance states exist:
SELECT status, count(*), sum(amount_minor)
FROM budget_reservation_rows
GROUP BY status;
```

---

## 5. Promotion to Production

Once data integrity is confirmed:

1. **Promote the Database out of recovery**:
   ```sql
   SELECT pg_wal_replay_resume();
   ```
2. **Swap Production DNS or Container Endpoints**:
   Update `DATABASE_URL` in `.env` to point to the promoted cluster.
3. **Re-align Transactional Outbox**:
   ```sql
   -- Mark any unconfirmed in-flight captures as PENDING_RECONCILIATION:
   UPDATE payment_intent_rows
   SET state = 'PENDING_PROVIDER'
   WHERE state = 'CAPTURE_PENDING'
     AND updated_at > '2026-11-12 03:40:00 UTC';
   ```
4. **Restart API & Background Worker**:
   ```bash
   docker compose up -d api worker
   ```
5. **Take an Immediate Fresh Base Backup** of the new timeline.
