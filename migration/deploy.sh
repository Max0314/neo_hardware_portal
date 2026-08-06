#!/usr/bin/env bash
# 一键部署：docker compose up -d --build + 启动锁 + 健康/数据库检查 + 验收
# 用法: cd 项目根 && bash migration/deploy.sh [--no-build]
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  _realdir="$(cd "$(dirname "$_self")" && pwd)"
  _realroot="$(cd "${_realdir}/.." && pwd)"
  _tmp="$(mktemp /tmp/migration-deploy.XXXXXX.sh)"
  sed 's/\r$//' "$_self" >"$_tmp"
  chmod 700 "$_tmp"
  MIGRATION_SCRIPT_DIR="$_realdir" MIGRATION_ROOT="$_realroot" exec bash "$_tmp" "$@"
fi
unset _self
set -euo pipefail

if [[ -n "${MIGRATION_ROOT:-}" && -f "${MIGRATION_ROOT}/docker-compose.yml" ]]; then
  ROOT="${MIGRATION_ROOT}"
  SCRIPT_DIR="${MIGRATION_SCRIPT_DIR:-${ROOT}/migration}"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  case "$SCRIPT_DIR" in
    /dev/fd/*|/proc/self/fd/*)
      ROOT="$(pwd)"
      SCRIPT_DIR="${ROOT}/migration"
      ;;
    *)
      ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
      ;;
  esac
fi
cd "$ROOT"

_lc="${ROOT}/migration/lib-crlf.sh"
if [[ -f "$_lc" ]] && grep -q $'\r' "$_lc" 2>/dev/null; then
  # shellcheck source=/dev/null
  source <(sed 's/\r$//' "$_lc")
else
  # shellcheck source=lib-crlf.sh
  source "$_lc"
fi
unset _lc

DO_BUILD=1
for arg in "$@"; do
  case "$arg" in
    --no-build) DO_BUILD=0 ;;
    -h|--help)
      echo "用法: bash migration/deploy.sh [--no-build]"
      echo "  默认: docker compose up -d --build + 健康/DB 检查"
      exit 0
      ;;
    *)
      echo "未知参数: $arg（支持 --no-build）" >&2
      exit 1
      ;;
  esac
done

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi

# shellcheck source=lib-progress.sh
migration_source "${ROOT}/migration/lib-progress.sh"
# shellcheck source=lib-compose-core.sh
migration_source "${ROOT}/migration/lib-compose-core.sh"
# shellcheck source=lib-deploy-wait.sh
migration_source "${ROOT}/migration/lib-deploy-wait.sh"

deploy_wait_init

TOTAL_STEPS=10
STEP=0
DEPLOY_FAILED=0

fail() {
  DEPLOY_FAILED=1
  progress_finish "部署失败: $*"
  echo "" >&2
  echo "排障建议:" >&2
  echo "  bash migration/check-stack.sh" >&2
  echo "  bash migration/check-db-config.sh" >&2
  echo "  bash migration/clear-startup-lock.sh" >&2
  echo "  bash migration/fix-login-full.sh" >&2
  exit 1
}

next_step() {
  STEP=$((STEP + 1))
  progress_draw "$STEP" "$TOTAL_STEPS" "$1"
}

trap deploy_on_exit_clear_lock EXIT

progress_log "========== 硬件研发部系统部署流水线 =========="
volume_write_lock 0 "正在部署，请稍候"
sync_lock_to_container 0 "正在部署，请稍候"

next_step "检查环境"
if [[ ! -f docker-compose.yml ]]; then
  fail "缺少 docker-compose.yml"
fi
if [[ ! -f .env ]]; then
  fail "缺少 .env，请先 cp .env.example .env 并填写"
fi
# 网关已改为明文 HTTP（TLS 由平台 Nginx 终止），不再需要自签证书
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "检查环境"

next_step "构建并启动 Docker 服务"
if [[ "$DO_BUILD" -eq 1 ]]; then
  compose_up_core --build --remove-orphans >>"${DEPLOY_LOG}" 2>&1 \
    || fail "docker compose up -d --build 失败"
else
  compose_up_core --remove-orphans >>"${DEPLOY_LOG}" 2>&1 \
    || fail "docker compose up -d 失败"
fi
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "构建并启动 Docker 服务"

next_step "检查外部数据库连通"
# 数据库由 NeoFlowData 提供，本机没有 stack-mysql 容器可等；改为直接测连通性。
wait_external_mysql "$ROOT" 45 || fail "外部数据库不可达，请检查 .env 的 MYSQL_HOST/PORT/USER/PASSWORD"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "检查外部数据库连通"

next_step "更新数据库结构"
export AUTO_FIX_NEO_TABLES=1
bash "${ROOT}/migration/ensure-neo-mysql-tables.sh" >>"${DEPLOY_LOG}" 2>&1 \
  || progress_log "警告: ensure-neo-mysql-tables 未完全成功"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "更新数据库结构"

next_step "等待管理系统就绪"
wait_container_healthy stack-htmlsystm 90 || fail "stack-htmlsystm 未就绪"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待管理系统就绪"

next_step "等待 NEO 后端就绪"
wait_container_healthy stack-neo-backend 90 || fail "stack-neo-backend 未就绪"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待 NEO 后端就绪"

next_step "等待 NEO 前端就绪"
wait_container_healthy stack-neo-web 60 || fail "stack-neo-web 未就绪"
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待 NEO 前端就绪"

next_step "等待统一网关就绪"
# NEO 重建后容器 IP 变化，gateway 内 nginx 会缓存旧 upstream IP，须重启以免 /neo/、/api/leaderboard 502
docker compose restart gateway >>"${DEPLOY_LOG}" 2>&1 || true
sleep 3
if [[ -x /usr/local/lib/docker-stack/boot-stack.sh ]]; then
  /usr/local/lib/docker-stack/boot-stack.sh ensure-gateway >>"${DEPLOY_LOG}" 2>&1 || true
fi
wait_container_healthy stack-gateway 30 \
  || docker compose up -d gateway >>"${DEPLOY_LOG}" 2>&1
sync_lock_to_container $((STEP * 100 / TOTAL_STEPS)) "等待统一网关就绪"

next_step "HTTPS 与数据库探活"
wait_https_health 15 || fail "经网关 /api/health 探活失败"
if ! wait_https_db_health 10; then
  progress_log "警告: /api/health?db=1 未通过，重启应用后重试..."
  docker compose restart gateway htmlsystm >>"${DEPLOY_LOG}" 2>&1 || true
  sleep 5
  wait_https_db_health 15 || progress_log "警告: /api/health?db=1 仍未通过，请核对 .env 的 MYSQL_* 与 NeoFlowData 连通性"
fi
curl -s "http://127.0.0.1:${PORT}/api/startup/status" >/dev/null 2>&1 || true
sync_lock_to_container 95 "HTTPS 与数据库探活"

next_step "数据库配置与栈验收"
if ! bash "${ROOT}/migration/check-db-config.sh" >>"${DEPLOY_LOG}" 2>&1; then
  progress_log "警告: check-db-config 未完全通过（核对 .env 的 MYSQL_* 配置）"
fi
bash "${ROOT}/migration/check-stack.sh" | tee -a "${DEPLOY_LOG}" || true

clear_startup_lock_all
trap - EXIT

progress_draw "$TOTAL_STEPS" "$TOTAL_STEPS" "部署完成"
progress_finish "系统已就绪，可以登录 https://<本机IP>:${PORT}/login"

progress_log "容器状态:"
docker compose ps 2>/dev/null | tee -a "${DEPLOY_LOG}" || true

mkdir -p "${ROOT}/log"
bash "${ROOT}/migration/collect-stack-logs.sh" >>"${DEPLOY_LOG}" 2>&1 || true
if ! [[ -f "${ROOT}/log/collector.pid" ]] || ! kill -0 "$(cat "${ROOT}/log/collector.pid" 2>/dev/null)" 2>/dev/null; then
  bash "${ROOT}/migration/start-log-collector.sh" --daemon >>"${DEPLOY_LOG}" 2>&1 || true
fi
progress_log "日志采集: ${ROOT}/log/ （每分钟一份快照）"
