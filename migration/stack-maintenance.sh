#!/usr/bin/env bash
# 预防性维护：清理过期 sessions、记录会话表规模
# 用法: bash migration/stack-maintenance.sh
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  sed -i 's/\r$//' "$_self"
  exec bash "$_self" "$@"
fi
unset _self
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${STACK_DIR:-$ROOT}"
LOG_FILE="${STACK_MAINT_LOG:-/var/log/docker-stack-maintenance.log}"

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || LOG_FILE="${TMPDIR:-/tmp}/docker-stack-maintenance.log"

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" >>"$LOG_FILE" 2>/dev/null || true
  echo "$msg"
}

cd "$STACK_DIR"
log "========== stack maintenance 开始 =========="

# shellcheck source=_common.sh
source "${ROOT}/migration/_common.sh"
if mysql_reachable; then
  bash "${ROOT}/migration/purge-user-sessions.sh" --all-stale >>"$LOG_FILE" 2>&1 || log "purge-user-sessions 失败"
  mysql_cli -N -e "SELECT COUNT(*) FROM sessions;" 2>>"$LOG_FILE" \
    | while read -r n; do log "sessions 表当前行数: ${n:-?}"; done || true
else
  log "外部数据库不可达，跳过 sessions 清理"
fi

log "========== stack maintenance 结束 =========="
