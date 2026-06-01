#!/usr/bin/env bash
# 阶段 A1：记录迁移前状态（架构、卷名、镜像、compose ps）
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_compose

BACKUP_DIR="${1:-$(default_backup_dir)}"
mkdir -p "${BACKUP_DIR}"

export VOLUME_PREFIX="$(get_compose_project_name)"
OUT="${BACKUP_DIR}/migration_state.txt"

{
  echo "=== 记录时间 ==="
  date -Iseconds 2>/dev/null || date
  echo
  echo "=== 项目根目录 ==="
  echo "${ROOT}"
  echo
  echo "=== COMPOSE_PROJECT_NAME（卷前缀）==="
  echo "${VOLUME_PREFIX}"
  echo
  echo "=== 架构 ==="
  uname -m
  uname -a
  echo
  echo "=== Docker / Compose ==="
  docker version 2>/dev/null || true
  docker compose version
  echo
  echo "=== docker compose ps ==="
  docker compose ps -a 2>/dev/null || true
  echo
  echo "=== 相关数据卷 ==="
  docker volume ls
  echo
  echo "=== 预期恢复的四个卷（全名）==="
  for v in "${DATA_VOLUMES[@]}"; do
    echo "$(volume_fq_name "${v}")"
  done
  echo
  echo "=== 本地镜像 ==="
  docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}'
  echo
  echo "=== compose config（卷段）==="
  docker compose config --volumes 2>/dev/null || true
} | tee "${OUT}"

echo ""
echo "已写入: ${OUT}"
echo "请将本文件与后续备份一并拷贝到目标机。"
