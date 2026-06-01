#!/usr/bin/env bash
# 前台/后台：每 60 秒执行一次 collect-stack-logs.sh，写入 log/
# 用法:
#   bash migration/start-log-collector.sh          # 前台
#   bash migration/start-log-collector.sh --daemon # 后台（nohup）
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  _realdir="$(cd "$(dirname "$_self")" && pwd)"
  _realroot="$(cd "${_realdir}/.." && pwd)"
  _tmp="$(mktemp /tmp/start-log-collector.XXXXXX.sh)"
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

COLLECT="${ROOT}/migration/collect-stack-logs.sh"
INTERVAL="${STACK_LOG_INTERVAL_SEC:-60}"
PID_FILE="${ROOT}/log/collector.pid"
SELF_SCRIPT="${ROOT}/migration/start-log-collector.sh"
DAEMON=0

for arg in "$@"; do
  case "$arg" in
    --daemon|-d) DAEMON=1 ;;
    -h|--help)
      echo "用法: bash migration/start-log-collector.sh [--daemon]"
      echo "  每 ${INTERVAL}s 写入 ${ROOT}/log/YYYY-MM-DD/HHMMSS.log"
      exit 0
      ;;
  esac
done

mkdir -p "${ROOT}/log"

run_loop() {
  cd "$ROOT"
  echo "[log-collector] 启动，间隔 ${INTERVAL}s，目录 ${ROOT}/log"
  while true; do
    bash "$COLLECT" >>"${ROOT}/log/collector-runner.log" 2>&1 || true
    sleep "$INTERVAL"
  done
}

if [[ "$DAEMON" -eq 1 ]]; then
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "日志采集已在运行，PID=$(cat "$PID_FILE")"
    exit 0
  fi
  nohup bash "$SELF_SCRIPT" >>"${ROOT}/log/collector-runner.log" 2>&1 &
  echo $! >"$PID_FILE"
  echo "后台日志采集已启动 PID=$(cat "$PID_FILE")"
  echo "  快照: ${ROOT}/log/"
  echo "  运行日志: ${ROOT}/log/collector-runner.log"
  echo "  停止: kill \$(cat ${PID_FILE})"
  exit 0
fi

run_loop
