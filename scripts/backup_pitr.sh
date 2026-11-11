#!/usr/bin/env bash
# =============================================================================
# AEGIS PostgreSQL Logical Backup & PITR Posture Verification Script
#
# Creates a consistent custom-format pg_dump snapshot, writes a SHA-256
# checksum manifest + JSON metadata manifest, checks PostgreSQL WAL archiving /
# PITR configuration, and optionally uploads artifacts to S3 / Cloudflare R2.
#
# Usage:
#   DATABASE_URL="postgresql://user:pass@localhost:5432/aegis_platform" \
#     ./scripts/backup_pitr.sh
#
# Environment variables:
#   DATABASE_URL          Required. PostgreSQL connection URI (postgresql:// or postgresql+psycopg://)
#   BACKUP_DIR            Output directory (default: ./var/backups/postgres)
#   S3_BACKUP_URI         Optional S3/R2 destination prefix, e.g. s3://aegis-backups/postgres/
#   S3_ENDPOINT_URL       Optional S3-compatible endpoint (e.g. Cloudflare R2 endpoint)
#   REQUIRE_PITR_WAL      If "true", fail when wal_level/archive_mode are not PITR-ready (default: false)
#   BACKUP_PRUNE_DAYS     If > 0, remove local backup files older than N days (default: 0 = disabled)
# =============================================================================
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,22p' "${BASH_SOURCE[0]}"
  exit 0
fi

BACKUP_DIR="${BACKUP_DIR:-${REPO_ROOT}/var/backups/postgres}"
S3_BACKUP_URI="${S3_BACKUP_URI:-}"
S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-}"
REQUIRE_PITR_WAL="${REQUIRE_PITR_WAL:-false}"
BACKUP_PRUNE_DAYS="${BACKUP_PRUNE_DAYS:-0}"

log() {
  printf '[%s] [backup_pitr] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  printf '[%s] [backup_pitr] ERROR: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

normalize_pg_url() {
  local raw="$1"
  # Strip SQLAlchemy driver suffix (+psycopg / +psycopg2) so libpq accepts the URI.
  echo "${raw/postgresql+psycopg:\/\//postgresql:\/\/}" | sed 's|^postgresql+psycopg2://|postgresql://|'
}

redact_url() {
  sed -E 's|(://[^:/@]+:)[^@]+@|\1***@|' <<<"$1"
}

sha256_file() {
  local target="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$target"
  else
    fail "Neither sha256sum nor shasum is installed"
  fi
}

require_cmd pg_dump
require_cmd psql

RAW_DB_URL="${DATABASE_URL:-}"
if [[ -z "${RAW_DB_URL}" ]]; then
  fail "DATABASE_URL must be set"
fi
PG_URL="$(normalize_pg_url "${RAW_DB_URL}")"

mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_BASENAME="aegis_${TIMESTAMP}.dump"
DUMP_FILE="${BACKUP_DIR}/${DUMP_BASENAME}"
TMP_DUMP_FILE="${DUMP_FILE}.tmp"
SHA_FILE="${DUMP_FILE}.sha256"
MANIFEST_FILE="${DUMP_FILE}.manifest.json"

cleanup() {
  if [[ -f "${TMP_DUMP_FILE}" ]]; then
    rm -f "${TMP_DUMP_FILE}"
  fi
}
trap cleanup EXIT

log "Starting PostgreSQL backup target=$(redact_url "${PG_URL}") dir=${BACKUP_DIR}"

# ---------------------------------------------------------------------------
# 1. WAL archiving & Point-in-Time Recovery (PITR) posture check
# ---------------------------------------------------------------------------
WAL_LEVEL="$(psql "${PG_URL}" -Atc "SHOW wal_level;" 2>/dev/null || echo "unknown")"
ARCHIVE_MODE="$(psql "${PG_URL}" -Atc "SHOW archive_mode;" 2>/dev/null || echo "unknown")"
ARCHIVE_CMD="$(psql "${PG_URL}" -Atc "SHOW archive_command;" 2>/dev/null || echo "")"
ALEMBIC_REV="$(psql "${PG_URL}" -Atc "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null || echo "unknown")"

PITR_READY="false"
if [[ ( "${WAL_LEVEL}" == "replica" || "${WAL_LEVEL}" == "logical" ) && ( "${ARCHIVE_MODE}" == "on" || "${ARCHIVE_MODE}" == "always" ) && -n "${ARCHIVE_CMD}" && "${ARCHIVE_CMD}" != "(disabled)" ]]; then
  PITR_READY="true"
fi

log "PITR posture: wal_level=${WAL_LEVEL} archive_mode=${ARCHIVE_MODE} pitr_ready=${PITR_READY} alembic_rev=${ALEMBIC_REV}"
if [[ "${PITR_READY}" != "true" ]]; then
  log "NOTE: Continuous PITR requires PostgreSQL wal_level=replica (or logical), archive_mode=on,"
  log "      and archive_command pushing WAL segments (e.g. via WAL-G or pgBackRest) plus periodic pg_basebackup."
  log "      Recovery target is configured via restore_command + recovery_target_time in postgresql.conf + recovery.signal."
  if [[ "${REQUIRE_PITR_WAL}" == "true" ]]; then
    fail "REQUIRE_PITR_WAL=true but PostgreSQL WAL archiving is not active"
  fi
fi

# ---------------------------------------------------------------------------
# 2. Consistent custom-format pg_dump
# ---------------------------------------------------------------------------
log "Running pg_dump --format=custom --no-owner --no-privileges"
pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="${TMP_DUMP_FILE}" \
  "${PG_URL}"

mv "${TMP_DUMP_FILE}" "${DUMP_FILE}"

# ---------------------------------------------------------------------------
# 3. SHA-256 checksum & metadata manifests
# ---------------------------------------------------------------------------
(
  cd "${BACKUP_DIR}"
  sha256_file "${DUMP_BASENAME}" > "${DUMP_BASENAME}.sha256"
)
DUMP_SHA256="$(awk '{print $1}' "${SHA_FILE}")"
DUMP_BYTES="$(wc -c < "${DUMP_FILE}" | tr -d ' ')"

cat > "${MANIFEST_FILE}" <<EOF
{
  "timestamp_utc": "${TIMESTAMP}",
  "dump_file": "${DUMP_BASENAME}",
  "byte_size": ${DUMP_BYTES},
  "sha256": "${DUMP_SHA256}",
  "alembic_revision": "${ALEMBIC_REV}",
  "wal_level": "${WAL_LEVEL}",
  "archive_mode": "${ARCHIVE_MODE}",
  "pitr_wal_ready": ${PITR_READY}
}
EOF

log "Backup written: ${DUMP_FILE} (${DUMP_BYTES} bytes, sha256=${DUMP_SHA256})"

# ---------------------------------------------------------------------------
# 4. Optional remote upload hook (AWS S3 / Cloudflare R2)
# ---------------------------------------------------------------------------
if [[ -n "${S3_BACKUP_URI}" ]]; then
  require_cmd aws
  DEST_PREFIX="${S3_BACKUP_URI%/}"
  AWS_ARGS=()
  if [[ -n "${S3_ENDPOINT_URL}" ]]; then
    AWS_ARGS+=(--endpoint-url "${S3_ENDPOINT_URL}")
  fi

  log "Uploading backup + manifests to ${DEST_PREFIX}/"
  aws "${AWS_ARGS[@]}" s3 cp "${DUMP_FILE}" "${DEST_PREFIX}/${DUMP_BASENAME}"
  aws "${AWS_ARGS[@]}" s3 cp "${SHA_FILE}" "${DEST_PREFIX}/${DUMP_BASENAME}.sha256"
  aws "${AWS_ARGS[@]}" s3 cp "${MANIFEST_FILE}" "${DEST_PREFIX}/${DUMP_BASENAME}.manifest.json"
  log "Remote upload complete"
fi

# ---------------------------------------------------------------------------
# 5. Optional local retention pruning
# ---------------------------------------------------------------------------
if [[ "${BACKUP_PRUNE_DAYS}" =~ ^[0-9]+$ ]] && (( BACKUP_PRUNE_DAYS > 0 )); then
  log "Pruning local backups older than ${BACKUP_PRUNE_DAYS} days in ${BACKUP_DIR}"
  find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name 'aegis_*.dump' -o -name 'aegis_*.sha256' -o -name 'aegis_*.manifest.json' \) -mtime +"${BACKUP_PRUNE_DAYS}" -delete
fi

log "Backup workflow succeeded"
