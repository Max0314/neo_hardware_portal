#!/usr/bin/env bash
# 部署/启动流水线公共函数：startup_lock、容器 health 等待、HTTPS 探活
# 被 stack-startup.sh 与 deploy.sh source

deploy_wait_init() {
  PROJECT="${COMPOSE_PROJECT_NAME:-docker}"
  VOLUME_DATA="${PROJECT}_htmlsystm_data"
  PORT="${GATEWAY_PUBLISH_PORT:-8000}"
  deploy_resolve_log
}

# 解析部署日志路径。/var/log 下的默认位置只有 root 可写；以普通用户部署时，重定向本身
# 就会失败，命令根本没执行，调用处却报出与真实原因无关的错误。不可写时回退到项目内。
deploy_resolve_log() {
  if [[ -n "${DEPLOY_LOG:-}" ]]; then
    return 0
  fi
  DEPLOY_LOG=/var/log/docker-stack-deploy.log
  if ( : >>"$DEPLOY_LOG" ) 2>/dev/null; then
    return 0
  fi
  DEPLOY_LOG="${ROOT:-$PWD}/log/deploy.log"
  if ! mkdir -p "$(dirname "$DEPLOY_LOG")" 2>/dev/null || ! ( : >>"$DEPLOY_LOG" ) 2>/dev/null; then
    DEPLOY_LOG=/tmp/docker-stack-deploy.log
  fi
}

volume_write_lock() {
  local pct="$1"
  local msg="$2"
  if ! docker volume inspect "$VOLUME_DATA" >/dev/null 2>&1; then
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  MSG="$msg" PCT="$pct" python3 -c "
import json, os
p = int(os.environ.get('PCT', 0))
print(json.dumps({'percent': p, 'message': os.environ.get('MSG', ''), 'ready': False}, ensure_ascii=False))
" >"$tmp" 2>/dev/null || echo '{"percent":0,"message":"启动中","ready":false}' >"$tmp"
  docker run --rm \
    -v "${VOLUME_DATA}:/app/data" \
    -v "${tmp}:/tmp/lock.json:ro" \
    alpine:3.20 \
    sh -c 'mkdir -p /app/data && cp /tmp/lock.json /app/data/.startup_lock.json && rm -f /app/data/.startup_ready' \
    >/dev/null 2>&1 || true
  rm -f "$tmp"
}

volume_clear_lock() {
  if ! docker volume inspect "$VOLUME_DATA" >/dev/null 2>&1; then
    return 0
  fi
  docker run --rm -v "${VOLUME_DATA}:/app/data" alpine:3.20 \
    sh -c "rm -f /app/data/.startup_lock.json && date +%s > /app/data/.startup_ready" \
    >/dev/null 2>&1 || true
}

sync_lock_to_container() {
  local pct="$1"
  local msg="$2"
  local py_msg
  py_msg="${msg//\'/\\\'}"
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stack-htmlsystm$'; then
    docker exec stack-htmlsystm python -c "
from server.startup_gate import write_lock
write_lock(${pct}, '${py_msg}')
" 2>/dev/null || true
  else
    volume_write_lock "$pct" "$msg"
  fi
}

clear_startup_lock_all() {
  volume_clear_lock
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stack-htmlsystm$'; then
    docker exec stack-htmlsystm python -c \
      "from server.startup_gate import clear_lock_and_mark_ready; clear_lock_and_mark_ready()" \
      2>/dev/null || true
  fi
}

wait_container_healthy() {
  local name="$1"
  local max="${2:-60}"
  local i hs
  for i in $(seq 1 "$max"); do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
      hs="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$name" 2>/dev/null || echo missing)"
      if [[ "$hs" == "healthy" || "$hs" == "running" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

_curl_health_ok() {
  local url="$1"
  curl -s "$url" 2>/dev/null | grep -qF '"ok"'
}

wait_https_health() {
  local max="${1:-15}"
  local i
  for i in $(seq 1 "$max"); do
    if _curl_health_ok "http://127.0.0.1:${PORT}/api/health"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_https_db_health() {
  local max="${1:-10}"
  local i
  for i in $(seq 1 "$max"); do
    if _curl_health_ok "http://127.0.0.1:${PORT}/api/health?db=1"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# 等待外部数据库（NeoFlowData）可达。本栈内没有数据库容器，无法用 healthcheck 判断，
# 因此直接用应用自己的凭据尝试连一次；连得上才算就绪。
wait_external_mysql() {
  local root="$1"
  local timeout="${2:-45}"
  local deadline=$(( SECONDS + timeout ))

  # _log 原本只定义在 ensure_mysql_password_synced 内部，此处直接用会是未定义命令
  local _log
  if declare -f progress_log >/dev/null 2>&1; then
    _log() { progress_log "$@"; }
  else
    _log() { echo "$@"; }
  fi

  local host port user pass db
  host="$(grep -E '^MYSQL_HOST=' "${root}/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)"
  port="$(grep -E '^MYSQL_PORT=' "${root}/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)"
  user="$(grep -E '^MYSQL_USER=' "${root}/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)"
  pass="$(grep -E '^MYSQL_PASSWORD=' "${root}/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)"
  db="$(grep -E '^MYSQL_DATABASE=' "${root}/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)"
  port="${port:-3306}"

  if [ -z "$host" ] || [ -z "$user" ] || [ -z "$pass" ] || [ -z "$db" ]; then
    _log "错误: .env 缺少 MYSQL_HOST/USER/PASSWORD/DATABASE"
    return 1
  fi

  while [ "$SECONDS" -lt "$deadline" ]; do
    # 密码走环境变量，不进 ps 输出；失败详情不回显，避免把凭据写进部署日志
    if MYSQL_PWD="$pass" mysql -h "$host" -P "$port" -u "$user" -D "$db" \
         -e 'SELECT 1' >/dev/null 2>&1; then
      _log "外部数据库 ${host}:${port}/${db} 可达"
      return 0
    fi
    sleep 3
  done

  _log "外部数据库 ${host}:${port}/${db} 在 ${timeout}s 内不可达"
  return 1
}

# 使用 stack-mysql 容器环境变量测试应用账号能否连库（旧的单机栈用，保留兼容）
mysql_app_can_connect() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx stack-mysql || return 1
  docker exec stack-mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "SELECT 1 AS ok" 2>/dev/null' \
    | grep -q ok
}

# .env 改密后数据卷仍为旧密码时，自动对齐（不删卷）
ensure_mysql_password_synced() {
  local root="${1:-.}"
  local _log
  if declare -f progress_log >/dev/null 2>&1; then
    _log() { progress_log "$@"; }
  else
    _log() { echo "$@"; }
  fi
  if mysql_app_can_connect; then
    return 0
  fi
  _log "MySQL 卷内密码与 .env 不一致，自动执行 reset-mysql-password.sh（不删数据）..."
  if bash "${root}/migration/reset-mysql-password.sh" >>"${DEPLOY_LOG}" 2>&1; then
    _log "MySQL 密码已与 .env 对齐"
    docker compose restart htmlsystm backend >>"${DEPLOY_LOG}" 2>&1 || true
    wait_container_healthy stack-mysql 45 || return 1
    wait_container_healthy stack-htmlsystm 90 || true
    wait_container_healthy stack-neo-backend 90 || true
    mysql_app_can_connect
    return $?
  fi
  _log "警告: MySQL 密码自动对齐失败，请手动 bash migration/reset-mysql-password.sh"
  return 1
}

deploy_on_exit_clear_lock() {
  clear_startup_lock_all
}
