#!/usr/bin/env bash
# 阶段 B3：目标机创建卷并解压导入四个 tar.gz
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_docker

BACKUP_DIR="${1:-}"
if [[ -z "${BACKUP_DIR}" || ! -d "${BACKUP_DIR}" ]]; then
  echo "用法: $0 <备份目录（含 *.tar.gz）>" >&2
  exit 1
fi

export VOLUME_PREFIX="${VOLUME_PREFIX:-$(get_compose_project_name)}"
echo "卷前缀: ${VOLUME_PREFIX}"

for vol in "${DATA_VOLUMES[@]}"; do
  archive="${BACKUP_DIR}/${vol}.tar.gz"
  fq="$(volume_fq_name "${vol}")"
  if [[ ! -f "${archive}" ]]; then
    echo "错误: 缺少备份文件 ${archive}" >&2
    exit 1
  fi
  echo "恢复 ${archive} -> 卷 ${fq}"
  ensure_image "${BACKUP_HELPER_IMAGE}"
  docker volume create "${fq}" >/dev/null 2>&1 || true
  docker run --rm \
    -v "${fq}:/data" \
    -v "${BACKUP_DIR}:/backup:ro" \
    "${BACKUP_HELPER_IMAGE}" sh -c "cd /data && tar xzf /backup/${vol}.tar.gz"
done

echo ""
echo "卷恢复完成。请确认 .env 中 MySQL 密码与源机一致，且 COMPOSE_PROJECT_NAME=${VOLUME_PREFIX}"
