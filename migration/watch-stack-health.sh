#!/usr/bin/env bash
# 宿主机巡检：容器未运行 / 持续 unhealthy 时 compose 拉起或 restart
# 由 systemd docker-stack-watch.timer 调用；也可手动: bash migration/watch-stack-health.sh
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  sed -i 's/\r$//' "$_self"
  exec bash "$_self" "$@"
fi
unset _self
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${STACK_DIR:-$ROOT}"
STATE_DIR="${STACK_STATE_DIR:-/var/lib/docker-stack}"
LOG_FILE="${STACK_WATCH_LOG:-/var/log/docker-stack-watch.log}"
UNHEALTHY_THRESHOLD="${STACK_UNHEALTHY_THRESHOLD:-2}"

mkdir -p "$STATE_DIR" 2>/dev/null || STATE_DIR="${TMPDIR:-/tmp}/docker-stack-state"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || LOG_FILE="${STATE_DIR}/watch.log"

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" >>"$LOG_FILE" 2>/dev/null || true
  echo "$msg" >&2
}

cd "$STACK_DIR"

if ! docker info >/dev/null 2>&1; then
  log "跳过: docker 不可用"
  exit 0
fi

SERVICES=(stack-htmlsystm stack-neo-backend stack-neo-web stack-gateway)

health_status() {
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || echo "missing"
}

running() {
  docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -q true
}

bump_unhealthy() {
  local name="$1"
  local f="${STATE_DIR}/unhealthy_${name}"
  local n=0
  if [[ -f "$f" ]]; then
    n="$(cat "$f" 2>/dev/null || echo 0)"
  fi
  n=$((n + 1))
  echo "$n" >"$f"
  echo "$n"
}

clear_unhealthy() {
  rm -f "${STATE_DIR}/unhealthy_${1}"
}

restart_service() {
  local cname="$1"
  local svc=""
  case "$cname" in
    stack-htmlsystm) svc="htmlsystm" ;;
    stack-neo-backend) svc="backend" ;;
    stack-neo-web) svc="web" ;;
    stack-gateway) svc="gateway" ;;
    *) return 1 ;;
  esac
  log "重启服务: $svc (容器 $cname)"
  docker compose restart "$svc" >>"$LOG_FILE" 2>&1 || true
}

for cname in "${SERVICES[@]}"; do
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$cname"; then
    log "容器不存在: $cname，尝试 compose up -d"
    docker compose up -d >>"$LOG_FILE" 2>&1 || true
    continue
  fi

  if ! running "$cname"; then
    log "容器未运行: $cname，尝试 compose up -d"
    docker compose up -d >>"$LOG_FILE" 2>&1 || true
    clear_unhealthy "$cname"
    continue
  fi

  hs="$(health_status "$cname")"
  case "$hs" in
    healthy|none)
      clear_unhealthy "$cname"
      ;;
    starting)
      clear_unhealthy "$cname"
      ;;
    unhealthy)
      n="$(bump_unhealthy "$cname")"
      log "$cname health=$hs 连续 ${n}/${UNHEALTHY_THRESHOLD}"
      if [[ "$n" -ge "$UNHEALTHY_THRESHOLD" ]]; then
        restart_service "$cname"
        clear_unhealthy "$cname"
      fi
      ;;
    *)
      log "$cname 未知 health=$hs"
      ;;
  esac
done

if ! running stack-gateway; then
  log "gateway 未运行，强制 up gateway"
  docker compose up -d gateway >>"$LOG_FILE" 2>&1 || true
fi

exit 0
