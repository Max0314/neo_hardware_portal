#!/usr/bin/env bash
# Read-only OSS migration preflight. It never uploads, deletes, or changes Compose.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
REQUIRE_OSS=0

if [[ "${1:-}" == "--require-oss" ]]; then
  REQUIRE_OSS=1
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--require-oss]" >&2
  exit 2
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[FAIL] Missing ${ENV_FILE}; copy .env.example and configure server-only values." >&2
  exit 2
fi

# Parse only KEY=value entries; do not source .env, and never print secret values.
env_value() {
  local key="$1"
  local line value
  line="$(grep -E "^[[:space:]]*${key}=" "${ENV_FILE}" | tail -n 1 || true)"
  value="${line#*=}"
  value="${value%$'\r'}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "${value}"
}

missing=0
require_value() {
  local key="$1"
  if [[ -z "$(env_value "${key}")" ]]; then
    echo "[FAIL] ${key} is required." >&2
    missing=1
  else
    echo "[ OK ] ${key} is configured."
  fi
}

backend="$(env_value STORAGE_BACKEND)"
backend="${backend:-local}"
echo "Storage backend: ${backend}"

if [[ "${backend}" != "local" && "${backend}" != "oss" ]]; then
  echo "[FAIL] STORAGE_BACKEND must be local or oss." >&2
  exit 2
fi

echo "Known local data that must be inventoried before object migration:"
echo "  - htmlsystm_data (announcements, metadata, compatibility files)"
echo "  - htmlsystm_uploads (uploaded files)"
echo "  - ai_chatroom_data (chat attachments, SQLite and vector data)"
echo "  - mysql_data (database; not an OSS object migration target)"

if [[ "${backend}" == "local" ]]; then
  echo "[INFO] Local storage is still active; no OSS cutover will occur."
  if [[ "${REQUIRE_OSS}" == "1" ]]; then
    echo "[FAIL] --require-oss was requested but STORAGE_BACKEND is local." >&2
    exit 1
  fi
  exit 0
fi

require_value OSS_ENDPOINT
require_value OSS_REGION
require_value OSS_BUCKET
prefix="$(env_value OSS_PREFIX)"
if [[ -z "${prefix}" ]]; then
  echo "[FAIL] OSS_PREFIX is required and must isolate this application." >&2
  missing=1
elif [[ "${prefix}" == /* || "${prefix}" == *".."* ]]; then
  echo "[FAIL] OSS_PREFIX must be a relative key prefix without '..'." >&2
  missing=1
else
  echo "[ OK ] OSS_PREFIX is configured."
fi

credential_mode="$(env_value OSS_CREDENTIAL_MODE)"
credential_mode="${credential_mode:-ram_role}"
case "${credential_mode}" in
  ram_role|sts|access_key)
    echo "[ OK ] OSS_CREDENTIAL_MODE=${credential_mode}"
    ;;
  *)
    echo "[FAIL] OSS_CREDENTIAL_MODE must be ram_role, sts, or access_key." >&2
    missing=1
    ;;
esac

if [[ "${credential_mode}" == "access_key" ]]; then
  require_value OSS_ACCESS_KEY_ID
  require_value OSS_ACCESS_KEY_SECRET
elif [[ "${credential_mode}" == "sts" ]]; then
  require_value OSS_ACCESS_KEY_ID
  require_value OSS_ACCESS_KEY_SECRET
  require_value OSS_SECURITY_TOKEN
fi

if [[ "${missing}" != "0" ]]; then
  echo "[FAIL] OSS is not ready. This command made no network request and changed nothing." >&2
  exit 1
fi

echo "[ OK ] Static OSS configuration is complete."
echo "[NEXT] Create a source inventory and checksum manifest, grant least-privilege access,"
echo "       then run the dual-read migration in docs/oss-migration-plan.md."
