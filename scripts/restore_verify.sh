#!/usr/bin/env bash
# =============================================================================
# AEGIS PostgreSQL Backup Restore & Integrity Verification Script
#
# Restores a custom-format pg_dump artifact into a strictly ephemeral database
# (either a temporary DB on PG_RESTORE_ADMIN_URL / DATABASE_URL or a disposable
# postgres:16-alpine Docker container), verifies SHA-256 checksum, Alembic
# migration state, table/row sanity counts, and financial_events immutability
# trigger presence, then cleans up all temporary resources.
#
# Usage:
#   ./scripts/restore_verify.sh /path/to/aegis_20261112T000000Z.dump
#
# Options / Environment variables:
#   BACKUP_FILE                   Path to .dump file (or pass as $1)
#   PG_RESTORE_ADMIN_URL          Admin Postgres URI to create/drop ephemeral DB
#   RESTORE_USE_DOCKER            "true" | "false" | "auto" (default: auto)
#   POSTGRES_IMAGE                Docker image for container mode (default: postgres:16-alpine)
#   REQUIRE_IMMUTABILITY_TRIGGER  "true" | "false" (default: true)
#   REQUIRE_CHECKSUM              "true" | "false" (default: false; verifies if .sha256 exists)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,23p' "${BASH_SOURCE[0]}"
  exit 0
fi

ALLOW_MISSING_TRIGGER=false
BACKUP_FILE="${BACKUP_FILE:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-missing-trigger)
      ALLOW_MISSING_TRIGGER=true
      shift
      ;;
    *)
      if [[ -z "${BACKUP_FILE}" ]]; then
        BACKUP_FILE="$1"
      fi
      shift
      ;;
  esac
done

RESTORE_USE_DOCKER="${RESTORE_USE_DOCKER:-auto}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"
REQUIRE_IMMUTABILITY_TRIGGER="${REQUIRE_IMMUTABILITY_TRIGGER:-true}"
REQUIRE_CHECKSUM="${REQUIRE_CHECKSUM:-false}"
if [[ "${ALLOW_MISSING_TRIGGER}" == "true" ]]; then
  REQUIRE_IMMUTABILITY_TRIGGER="false"
fi

log() {
  printf '[%s] [restore_verify] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  printf '[%s] [restore_verify] ERROR: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

normalize_pg_url() {
  local raw="$1"
  echo "${raw/postgresql+psycopg:\/\//postgresql:\/\/}" | sed 's|^postgresql+psycopg2://|postgresql://|'
}

if [[ -z "${BACKUP_FILE}" ]]; then
  BACKUP_DIR="${BACKUP_DIR:-${REPO_ROOT}/var/backups/postgres}"
  if [[ -d "${BACKUP_DIR}" ]]; then
    BACKUP_FILE="$(ls -1t "${BACKUP_DIR}"/aegis_*.dump 2>/dev/null | head -n1 || true)"
  fi
fi

[[ -n "${BACKUP_FILE}" ]] || fail "No backup file provided and none found in BACKUP_DIR"
[[ -f "${BACKUP_FILE}" ]] || fail "Backup file does not exist: ${BACKUP_FILE}"

BACKUP_FILE="$(cd "$(dirname "${BACKUP_FILE}")" && pwd)/$(basename "${BACKUP_FILE}")"
SHA_FILE="${BACKUP_FILE}.sha256"

# ---------------------------------------------------------------------------
# 1. SHA-256 checksum verification
# ---------------------------------------------------------------------------
if [[ -f "${SHA_FILE}" ]]; then
  log "Verifying SHA-256 checksum using ${SHA_FILE}"
  EXPECTED_SHA="$(awk '{print $1}' "${SHA_FILE}")"
  if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_SHA="$(sha256sum "${BACKUP_FILE}" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    ACTUAL_SHA="$(shasum -a 256 "${BACKUP_FILE}" | awk '{print $1}')"
  else
    fail "Neither sha256sum nor shasum is installed"
  fi
  [[ "${ACTUAL_SHA}" == "${EXPECTED_SHA}" ]] || fail "Checksum mismatch: ${ACTUAL_SHA} != ${EXPECTED_SHA}"
  log "Checksum verified: ${ACTUAL_SHA}"
elif [[ "${REQUIRE_CHECKSUM}" == "true" ]]; then
  fail "Checksum file missing and REQUIRE_CHECKSUM=true: ${SHA_FILE}"
else
  log "WARN: Checksum manifest ${SHA_FILE} not found; skipping checksum verification"
fi

# ---------------------------------------------------------------------------
# 2. Provision ephemeral PostgreSQL restore target + cleanup trap
# ---------------------------------------------------------------------------
EPHEMERAL_DB="aegis_restore_verify_$(date -u +%Y%m%d%H%M%S)_$$"
CONTAINER_NAME=""
ADMIN_PG_URL=""
EPHEMERAL_PG_URL=""

cleanup() {
  set +e
  if [[ -n "${CONTAINER_NAME}" ]]; then
    log "Removing ephemeral Docker PostgreSQL container ${CONTAINER_NAME}"
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  elif [[ -n "${ADMIN_PG_URL}" && -n "${EPHEMERAL_DB}" ]]; then
    log "Dropping ephemeral verification database ${EPHEMERAL_DB}"
    psql "${ADMIN_PG_URL}" -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${EPHEMERAL_DB}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
    psql "${ADMIN_PG_URL}" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"${EPHEMERAL_DB}\";" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ADMIN_RAW="${PG_RESTORE_ADMIN_URL:-${DATABASE_URL:-}}"
USE_DOCKER=false
if [[ "${RESTORE_USE_DOCKER}" == "true" ]]; then
  USE_DOCKER=true
elif [[ "${RESTORE_USE_DOCKER}" == "auto" && -z "${ADMIN_RAW}" ]]; then
  USE_DOCKER=true
fi

if [[ "${USE_DOCKER}" == "true" ]]; then
  require_cmd docker
  require_cmd pg_restore
  require_cmd psql

  CONTAINER_NAME="aegis-restore-verify-$$"
  EPHEMERAL_PORT="${RESTORE_PG_PORT:-55432}"
  EPHEMERAL_PASS="aegis_verify_ephemeral_pw"
  log "Starting ephemeral PostgreSQL container ${CONTAINER_NAME} (${POSTGRES_IMAGE}) on port ${EPHEMERAL_PORT}"
  docker run -d \
    --name "${CONTAINER_NAME}" \
    -e POSTGRES_USER=aegis_verify \
    -e POSTGRES_PASSWORD="${EPHEMERAL_PASS}" \
    -e POSTGRES_DB="${EPHEMERAL_DB}" \
    -p "127.0.0.1:${EPHEMERAL_PORT}:5432" \
    "${POSTGRES_IMAGE}" >/dev/null

  READY=false
  for _ in $(seq 1 30); do
    if docker exec "${CONTAINER_NAME}" pg_isready -U aegis_verify -d "${EPHEMERAL_DB}" >/dev/null 2>&1; then
      READY=true
      break
    fi
    sleep 1
  done
  [[ "${READY}" == "true" ]] || fail "Ephemeral PostgreSQL container failed to become ready"
  EPHEMERAL_PG_URL="postgresql://aegis_verify:${EPHEMERAL_PASS}@127.0.0.1:${EPHEMERAL_PORT}/${EPHEMERAL_DB}"
else
  require_cmd pg_restore
  require_cmd psql
  [[ -n "${ADMIN_RAW}" ]] || fail "Set PG_RESTORE_ADMIN_URL / DATABASE_URL or RESTORE_USE_DOCKER=true"
  ADMIN_PG_URL="$(normalize_pg_url "${ADMIN_RAW}")"
  # Replace database name in URI path with /postgres for admin connection and /EPHEMERAL_DB for target
  BASE_PG_URL="$(sed -E 's|/[^/?]+(\?.*)?$||' <<<"${ADMIN_PG_URL}")"
  QUERY_SUFFIX="$(sed -nE 's|^.*(/[^/?]+)(\?.*)$|\2|p' <<<"${ADMIN_PG_URL}")"
  ADMIN_PG_URL="${BASE_PG_URL}/postgres${QUERY_SUFFIX}"
  EPHEMERAL_PG_URL="${BASE_PG_URL}/${EPHEMERAL_DB}${QUERY_SUFFIX}"

  log "Creating ephemeral verification database ${EPHEMERAL_DB}"
  psql "${ADMIN_PG_URL}" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${EPHEMERAL_DB}\";" >/dev/null
fi

EPHEMERAL_SA_URL="${EPHEMERAL_PG_URL/postgresql:\/\//postgresql+psycopg:\/\/}"

# ---------------------------------------------------------------------------
# 3. Restore backup into ephemeral database
# ---------------------------------------------------------------------------
log "Restoring ${BACKUP_FILE} into ephemeral database ${EPHEMERAL_DB}"
pg_restore \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  --dbname="${EPHEMERAL_PG_URL}" \
  "${BACKUP_FILE}"

# ---------------------------------------------------------------------------
# 4. Alembic current check
# ---------------------------------------------------------------------------
log "Checking Alembic migration state (alembic current)"
if command -v uv >/dev/null 2>&1; then
  ALEMBIC_OUT="$(cd "${REPO_ROOT}/packages/database" && DATABASE_URL="${EPHEMERAL_SA_URL}" uv run --no-sync alembic current)"
else
  require_cmd alembic
  ALEMBIC_OUT="$(cd "${REPO_ROOT}/packages/database" && DATABASE_URL="${EPHEMERAL_SA_URL}" alembic current)"
fi
log "alembic current: ${ALEMBIC_OUT}"
[[ -n "${ALEMBIC_OUT}" ]] || fail "alembic current returned empty output after restore"

# ---------------------------------------------------------------------------
# 5. Table & row sanity queries
# ---------------------------------------------------------------------------
log "Running table & row sanity queries"
FINANCIAL_EVENTS_COUNT="$(psql "${EPHEMERAL_PG_URL}" -Atc "SELECT count(*) FROM financial_events;")"
TENANTS_COUNT="$(psql "${EPHEMERAL_PG_URL}" -Atc "SELECT count(*) FROM tenants;")"
PAYMENT_INTENTS_COUNT="$(psql "${EPHEMERAL_PG_URL}" -Atc "SELECT count(*) FROM payment_intents;")"
EVIDENCE_ARTIFACTS_COUNT="$(psql "${EPHEMERAL_PG_URL}" -Atc "SELECT count(*) FROM evidence_artifacts;")"
OUTBOX_COUNT="$(psql "${EPHEMERAL_PG_URL}" -Atc "SELECT count(*) FROM outbox_events;")"

log "Sanity counts: tenants=${TENANTS_COUNT} payment_intents=${PAYMENT_INTENTS_COUNT} financial_events=${FINANCIAL_EVENTS_COUNT} evidence_artifacts=${EVIDENCE_ARTIFACTS_COUNT} outbox_events=${OUTBOX_COUNT}"

# ---------------------------------------------------------------------------
# 6. Immutability trigger verification on financial_events
# ---------------------------------------------------------------------------
log "Verifying immutability trigger presence on financial_events"
TRIGGER_INFO="$(psql "${EPHEMERAL_PG_URL}" -Atc "SELECT tgname || ': ' || pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid = 'financial_events'::regclass AND NOT tgisinternal;")"
if [[ -z "${TRIGGER_INFO}" ]]; then
  if [[ "${REQUIRE_IMMUTABILITY_TRIGGER}" == "true" ]]; then
    fail "No immutability trigger found on financial_events (set REQUIRE_IMMUTABILITY_TRIGGER=false or --allow-missing-trigger for pre-trigger dumps)"
  else
    log "WARN: No immutability trigger found on financial_events (allowed by configuration)"
  fi
else
  log "Verified immutability trigger(s) on financial_events:"
  while IFS= read -r line; do
    log "  ${line}"
  done <<< "${TRIGGER_INFO}"
fi

log "Restore verification succeeded"
