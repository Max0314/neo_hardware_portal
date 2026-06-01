#!/usr/bin/env bash
# 开机自启辅助脚本（由 install-boot-service.sh 安装到 /usr/local/lib/docker-stack/）
# 不依赖 WorkingDirectory，使用绝对路径，先等共享盘挂载再等 compose 文件。
set -euo pipefail

STACK_DIR="${STACK_DIR:-/media/sf_awei/docker版本}"
MOUNT_POINT="${MOUNT_POINT:-/media/sf_awei}"
MAX_WAIT_MOUNT="${MAX_WAIT_MOUNT:-120}"
MAX_WAIT_FILES="${MAX_WAIT_FILES:-120}"
MAX_WAIT_DOCKER="${MAX_WAIT_DOCKER:-90}"
MAX_GATEWAY_RETRY="${MAX_GATEWAY_RETRY:-24}"

log() { echo "[docker-stack-boot] $*" >&2; }

need_media_mount() {
  [[ "${STACK_DIR}" == /media/* ]]
}

wait_mount() {
  if ! need_media_mount; then
    return 0
  fi
  log "等待挂载点就绪: ${MOUNT_POINT}"
  for _ in $(seq 1 "${MAX_WAIT_MOUNT}"); do
    if mountpoint -q "${MOUNT_POINT}" 2>/dev/null && [[ -d "${MOUNT_POINT}" ]]; then
      log "挂载点已就绪: ${MOUNT_POINT}"
      return 0
    fi
    sleep 2
  done
  log "超时: 挂载点 ${MOUNT_POINT} 未就绪（VirtualBox 共享文件夹是否已挂载？）"
  return 1
}

wait_stack_files() {
  log "等待项目文件: ${STACK_DIR}"
  for _ in $(seq 1 "${MAX_WAIT_FILES}"); do
    if [[ -f "${STACK_DIR}/docker-compose.yml" && -f "${STACK_DIR}/gateway/certs/server.crt" ]]; then
      log "项目文件已就绪"
      return 0
    fi
    sleep 2
  done
  log "超时: 缺少 docker-compose.yml 或 gateway/certs/server.crt"
  return 1
}

wait_docker() {
  log "等待 Docker 守护进程"
  for _ in $(seq 1 "${MAX_WAIT_DOCKER}"); do
    if docker info >/dev/null 2>&1; then
      log "Docker 已就绪"
      return 0
    fi
    sleep 2
  done
  log "超时: docker info 失败（用户是否在 docker 组？）"
  return 1
}

cmd_wait_ready() {
  wait_mount
  wait_stack_files
  wait_docker
}

cmd_up() {
  cd "${STACK_DIR}"
  local startup="${STACK_DIR}/migration/stack-startup.sh"
  if [[ -f "${startup}" ]]; then
    log "执行 stack-startup.sh（进度条 + 更新 + 就绪后开放登录）"
    bash "${startup}"
    return $?
  fi
  cmd_wait_ready
  log "执行 docker compose up -d（未找到 stack-startup.sh，跳过维护门）"
  docker compose up -d
}

cmd_ensure_gateway() {
  cd "${STACK_DIR}"
  for _ in $(seq 1 "${MAX_GATEWAY_RETRY}"); do
    if docker compose ps --status running 2>/dev/null | grep -q stack-gateway; then
      log "stack-gateway 已运行"
      return 0
    fi
    log "重试拉起 stack-gateway ..."
    docker compose up -d gateway 2>/dev/null || true
    sleep 5
  done
  log "stack-gateway 仍未运行，请检查: docker compose logs gateway --tail 50"
  return 1
}

cmd_startup() {
  cd "${STACK_DIR}"
  local startup="${STACK_DIR}/migration/stack-startup.sh"
  if [[ ! -f "${startup}" ]]; then
    log "缺少 ${startup}"
    return 1
  fi
  bash "${startup}"
}

usage() {
  echo "用法: $0 {wait-ready|up|startup|ensure-gateway}" >&2
  exit 2
}

case "${1:-}" in
  wait-ready) cmd_wait_ready ;;
  up) cmd_up ;;
  startup) cmd_startup ;;
  ensure-gateway) cmd_ensure_gateway ;;
  *) usage ;;
esac
