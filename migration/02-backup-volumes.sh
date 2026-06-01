#!/usr/bin/env bash
# 阶段 A3–A4：停栈并打包四个命名卷为 tar.gz
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_compose

BACKUP_DIR="${1:-$(default_backup_dir)}"
SKIP_STOP="${SKIP_STOP:-0}"

export VOLUME_PREFIX="${VOLUME_PREFIX:-$(get_compose_project_name)}"
mkdir -p "${BACKUP_DIR}"

echo "卷前缀: ${VOLUME_PREFIX}"
echo "备份目录: ${BACKUP_DIR}"

if [[ "${SKIP_STOP}" != "1" ]]; then
  echo "正在停止 compose 栈..."
  docker compose stop
else
  echo "SKIP_STOP=1，跳过 docker compose stop"
fi

for vol in "${DATA_VOLUMES[@]}"; do
  fq="$(volume_fq_name "${vol}")"
  if ! docker volume inspect "${fq}" >/dev/null 2>&1; then
    echo "错误: 卷不存在: ${fq}" >&2
    echo "请检查 COMPOSE_PROJECT_NAME 或先执行 ./migration/01-record-state.sh" >&2
    exit 1
  fi
  out="${BACKUP_DIR}/${vol}.tar.gz"
  echo "备份 ${fq} -> ${out}"
  ensure_image "${BACKUP_HELPER_IMAGE}"
  docker run --rm \
    -v "${fq}:/data:ro" \
    -v "${BACKUP_DIR}:/backup" \
    "${BACKUP_HELPER_IMAGE}" tar czf "/backup/${vol}.tar.gz" -C /data .
done

ls -lh "${BACKUP_DIR}"/*.tar.gz 2>/dev/null || true
echo ""
echo "卷备份完成: ${BACKUP_DIR}"
