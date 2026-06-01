#!/usr/bin/env bash
# 开机/自启：带命令行进度条完成更新与健康等待，完成后才允许用户登录
# 用法: STACK_DIR=/path/to/docker版本 bash migration/stack-startup.sh
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  _realdir="$(cd "$(dirname "$_self")" && pwd)"
  _realroot="$(cd "${_realdir}/.." && pwd)"
  _tmp="$(mktemp /tmp/migration-startup.XXXXXX.sh)"
  sed 's/\r$//' "$_self" >"$_tmp"
  chmod 700 "$_tmp"
  MIGRATION_SCRIPT_DIR="$_realdir" MIGRATION_ROOT="$_realroot" exec bash "$_tmp" "$@"
fi
unset _self
set -euo pipefail

if [[ -n "${MIGRATION_ROOT:-}" && -f "${MIGRATION_ROOT}/docker-compose.yml" ]]; then
  ROOT="${MIGRATION_ROOT}"
  STACK_DIR="${MIGRATION_ROOT}"
  SCRIPT_DIR="${MIGRATION_SCRIPT_DIR:-${ROOT}/migration}"
elif [[ "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" == */docker-stack ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  STACK_DIR="${STACK_DIR:-/media/sf_awei/docker版本}"
  ROOT="${STACK_DIR}"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  case "$SCRIPT_DIR" in
    /dev/fd/*|/proc/self/fd/*)
      ROOT="$(pwd)"
      STACK_DIR="${ROOT}"
      SCRIPT_DIR="${ROOT}/migration"
      ;;
    *)
      ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
      STACK_DIR="${STACK_DIR:-$ROOT}"
      ;;
  esac
fi
cd "$STACK_DIR"

_lc="${ROOT}/migration/lib-crlf.sh"
if [[ -f "$_lc" ]] && grep -q $'\r' "$_lc" 2>/dev/null; then
  # shellcheck source=/dev/null
  source <(sed 's/\r$//' "$_lc")
else
  # shellcheck source=lib-crlf.sh
  source "$_lc"
fi
unset _lc

if [[ "$SCRIPT_DIR" == */docker-stack ]]; then
  migration_source "${SCRIPT_DIR}/lib-progress.sh"
else
  migration_source "${ROOT}/migration/lib-progress.sh"
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi

# shellcheck source=lib-compose-core.sh
migration_source "${ROOT}/migration/lib-compose-core.sh"
# shellcheck source=lib-deploy-wait.sh
migration_source "${ROOT}/migration/lib-deploy-wait.sh"

deploy_wait_init

TOTAL_STEPS=10
STEP=0

fail() {
  progress_finish "启动失败: $*"
  exit 1
}

next_step() {
  STEP=$((STEP + 1))
  progress_draw "$STEP" "$TOTAL_STEPS" "$1"
}

trap deploy_on_exit_clear_lock EXIT

progress_log "========== 硬件研发部系统启动流水线 =========="
volume_write_lock 0 "准备启动环境"
sync_lock_to_container 0 "准备启动环境"

# 1 环境就绪
next_step "等待挂载与 Docker"
if [[ -x /usr/local/lib/docker-stack/boot-stack.sh ]]; then
  /usr/local/lib/docker-stack/boot-stack.sh wait-ready || fail "环境未就绪"
else
  bash "${ROOT}/migration/boot-stack.sh" wait-ready || fail "环境未就绪"
fi
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待挂载与 Docker"

# 2 拉起容器
next_step "启动 Docker 服务"
compose_up_core >>/var/log/docker-stack-startup.log 2>&1 || fail "docker compose up 失败"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "启动 Docker 服务"

# 3 MySQL
next_step "等待 MySQL 就绪"
wait_container_healthy stack-mysql 45 || fail "MySQL 未就绪"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待 MySQL 就绪"

# 4 NEO 表 / 库结构
next_step "更新数据库结构"
export AUTO_FIX_NEO_TABLES=1
bash "${ROOT}/migration/ensure-neo-mysql-tables.sh" >>/var/log/docker-stack-startup.log 2>&1 || progress_log "警告: ensure-neo-mysql-tables 未完全成功"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "更新数据库结构"

# 5 htmlsystm
next_step "等待管理系统就绪"
wait_container_healthy stack-htmlsystm 60 || fail "stack-htmlsystm 未就绪"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待管理系统就绪"

# 6 backend
next_step "等待 NEO 后端就绪"
wait_container_healthy stack-neo-backend 60 || fail "stack-neo-backend 未就绪"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待 NEO 后端就绪"

# 7 web
next_step "等待 NEO 前端就绪"
wait_container_healthy stack-neo-web 40 || fail "stack-neo-web 未就绪"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待 NEO 前端就绪"

# 8 gateway
next_step "等待统一网关就绪"
if [[ -x /usr/local/lib/docker-stack/boot-stack.sh ]]; then
  /usr/local/lib/docker-stack/boot-stack.sh ensure-gateway >>/var/log/docker-stack-startup.log 2>&1 || true
fi
wait_container_healthy stack-gateway 30 || docker compose up -d gateway >>/var/log/docker-stack-startup.log 2>&1
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待统一网关就绪"

# 9 HTTPS 自检
next_step "HTTPS 服务自检"
wait_https_health 15 || progress_log "警告: /api/health 探活未通过"
curl -sk "https://127.0.0.1:${PORT}/api/startup/status" >/dev/null 2>&1 || true
sync_lock_to_container 95 "HTTPS 服务自检"

# 10 开放登录
next_step "开放用户登录"
clear_startup_lock_all
trap - EXIT

progress_draw "$TOTAL_STEPS" "$TOTAL_STEPS" "启动完成"
progress_finish "系统已就绪，可以登录 https://<本机IP>:${PORT}/login"

progress_log "容器状态:"
docker compose ps 2>/dev/null | tee -a /var/log/docker-stack-startup.log || true
