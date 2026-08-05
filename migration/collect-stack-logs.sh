#!/usr/bin/env bash
# 每分钟采集一次 Docker 栈快照到项目 log/ 目录（排查登录/健康问题时用）
# 手动: cd 项目根 && bash migration/collect-stack-logs.sh
# 后台循环: bash migration/start-log-collector.sh
# systemd: INSTALL_LOG_COLLECTOR=1 sudo bash migration/install-boot-service.sh
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  _realdir="$(cd "$(dirname "$_self")" && pwd)"
  _realroot="$(cd "${_realdir}/.." && pwd)"
  _tmp="$(mktemp /tmp/collect-stack-logs.XXXXXX.sh)"
  sed 's/\r$//' "$_self" >"$_tmp"
  chmod 700 "$_tmp"
  MIGRATION_SCRIPT_DIR="$_realdir" MIGRATION_ROOT="$_realroot" exec bash "$_tmp" "$@"
fi
unset _self
set -euo pipefail

if [[ -n "${MIGRATION_ROOT:-}" && -f "${MIGRATION_ROOT}/docker-compose.yml" ]]; then
  ROOT="${MIGRATION_ROOT}"
else
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$ROOT"

LOG_DIR="${STACK_LOG_DIR:-${ROOT}/log}"
TAIL_LINES="${STACK_LOG_TAIL_LINES:-40}"
RETENTION_DAYS="${STACK_LOG_RETENTION_DAYS:-7}"
PORT="${GATEWAY_PUBLISH_PORT:-8000}"

TS="$(date '+%Y-%m-%d %H:%M:%S %z')"
DAY="$(date '+%Y-%m-%d')"
STAMP="$(date '+%Y%m%d_%H%M%S')"
OUT_DIR="${LOG_DIR}/${DAY}"
OUT_FILE="${OUT_DIR}/${STAMP}.log"

mkdir -p "$OUT_DIR"

{
  echo "========== Docker 栈日志快照 =========="
  echo "时间: ${TS}"
  echo "项目: ${ROOT}"
  echo ""

  if ! docker info >/dev/null 2>&1; then
    echo "!!! docker 不可用，跳过后续采集"
    exit 0
  fi

  echo "--- docker compose ps ---"
  docker compose ps 2>&1 || true
  echo ""

  echo "--- 容器 Health ---"
  for c in stack-mysql stack-htmlsystm stack-neo-backend stack-neo-web stack-gateway; do
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
      hs="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$c" 2>/dev/null || echo '?')"
      echo "  ${c}: ${hs}"
    else
      echo "  ${c}: (未创建)"
    fi
  done
  echo ""

  echo "--- HTTPS 探活 ---"
  curl -s "http://127.0.0.1:${PORT}/api/health" 2>&1 | head -1 || echo "(health 失败)"
  echo ""
  curl -s "http://127.0.0.1:${PORT}/api/startup/status" 2>&1 | head -1 || echo "(startup/status 失败)"
  echo ""

  for c in stack-mysql stack-htmlsystm stack-neo-backend stack-neo-web stack-gateway; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
      echo "--- ${c} logs (tail ${TAIL_LINES}) ---"
      docker logs "$c" --tail "$TAIL_LINES" 2>&1 || true
      echo ""
    fi
  done

  echo "========== 快照结束 =========="
} >>"$OUT_FILE" 2>&1

# 清理过期目录（按日期文件夹）
if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] && [[ "$RETENTION_DAYS" -gt 0 ]]; then
  find "$LOG_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} + 2>/dev/null || true
fi

echo "[collect-stack-logs] ${OUT_FILE}"
