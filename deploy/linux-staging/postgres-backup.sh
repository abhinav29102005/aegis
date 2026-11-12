#!/usr/bin/env bash
set -euo pipefail

# Daily PostgreSQL backup script for AEGIS Linux VPS.
# Reads POSTGRES_USER / POSTGRES_DB / AEGIS_S3_BUCKET from /etc/aegis/.env when present.

if [[ -f /etc/aegis/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/aegis/.env
  set +a
fi

BACKUP_DIR="${AEGIS_BACKUP_DIR:-/var/backups/aegis/postgres}"
RETENTION_DAYS="${AEGIS_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
POSTGRES_USER="${POSTGRES_USER:-aegis}"
POSTGRES_DB="${POSTGRES_DB:-aegis_platform}"
ARCHIVE="${BACKUP_DIR}/aegis-${POSTGRES_DB}-${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

docker exec aegis-postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --format=plain \
  | gzip -9 > "${ARCHIVE}"

sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256"

# Optional off-site encrypted S3 archive if AWS CLI & backup bucket are configured
if [[ -n "${AEGIS_BACKUP_S3_BUCKET:-}" ]] && command -v aws >/dev/null 2>&1; then
  aws s3 cp "${ARCHIVE}" "s3://${AEGIS_BACKUP_S3_BUCKET}/postgres/${TIMESTAMP}/" --sse AES256
  aws s3 cp "${ARCHIVE}.sha256" "s3://${AEGIS_BACKUP_S3_BUCKET}/postgres/${TIMESTAMP}/" --sse AES256
fi

find "${BACKUP_DIR}" -type f -name 'aegis-*.sql.gz*' -mtime "+${RETENTION_DAYS}" -delete
echo "[${TIMESTAMP}] PostgreSQL backup written to ${ARCHIVE}"
