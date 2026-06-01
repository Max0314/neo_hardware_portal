#!/usr/bin/env bash
# VirtualBox 共享目录：sed -i 常失败；用 /tmp 副本 exec 并保留真实路径。
# 用法: migration_source /path/to/lib.sh ; migration_resolve_root

migration_fix_crlf_exec() {
  local self="$1"
  shift
  if [[ ! -f "$self" ]] || ! grep -q $'\r' "$self" 2>/dev/null; then
    return 1
  fi
  local realdir realroot tmp
  realdir="$(cd "$(dirname "$self")" && pwd)"
  realroot="$(cd "${realdir}/.." && pwd)"
  tmp="$(mktemp /tmp/migration-script.XXXXXX.sh)"
  sed 's/\r$//' "$self" >"$tmp"
  chmod 700 "$tmp"
  MIGRATION_SCRIPT_DIR="$realdir" MIGRATION_ROOT="$realroot" exec bash "$tmp" "$@"
}

migration_resolve_root() {
  if [[ -n "${MIGRATION_ROOT:-}" && -f "${MIGRATION_ROOT}/docker-compose.yml" ]]; then
    ROOT="${MIGRATION_ROOT}"
    SCRIPT_DIR="${MIGRATION_SCRIPT_DIR:-${ROOT}/migration}"
    return 0
  fi
  local src="${1:-${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}}"
  SCRIPT_DIR="$(cd "$(dirname "$src")" && pwd)"
  case "$SCRIPT_DIR" in
    /dev/fd/*|/proc/self/fd/*)
      ROOT="$(pwd)"
      if [[ ! -f "${ROOT}/docker-compose.yml" ]]; then
        echo "错误: 请在含 docker-compose.yml 的项目根目录执行本脚本" >&2
        exit 1
      fi
      SCRIPT_DIR="${ROOT}/migration"
      ;;
    *)
      ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
      ;;
  esac
}

migration_source() {
  local f="$1"
  if [[ -f "$f" ]] && grep -q $'\r' "$f" 2>/dev/null; then
    # shellcheck disable=SC1090
    source <(sed 's/\r$//' "$f")
  else
    # shellcheck disable=SC1090
    source "$f"
  fi
}
