#!/usr/bin/env bash
# 统一备份：MySQL dump + 四个命名卷（公告/物料/看板积分在 MySQL，AI 库在 ai_chatroom_data）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [[ -f "${ROOT}/migration/_common.sh" ]]; then
  # shellcheck source=/dev/null
  source "${ROOT}/migration/_common.sh"
else
  echo "错误: 未找到 migration/_common.sh" >&2
  exit 1
fi

require_compose

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${1:-${ROOT}/backup/backup_${STAMP}}"
export VOLUME_PREFIX="${VOLUME_PREFIX:-$(get_compose_project_name)}"
mkdir -p "${BACKUP_DIR}"

MANIFEST="${BACKUP_DIR}/manifest.txt"
{
  echo "backup_time=${STAMP}"
  echo "compose_project=${VOLUME_PREFIX}"
  echo "backup_dir=${BACKUP_DIR}"
} > "${MANIFEST}"

echo "========== 统一备份 =========="
echo "卷前缀: ${VOLUME_PREFIX}"
echo "输出目录: ${BACKUP_DIR}"

# MySQL
MYSQL_OK=0
if docker compose ps mysql 2>/dev/null | grep -qE 'running|Up'; then
  DUMP_FILE="${BACKUP_DIR}/mysql_${STAMP}.sql"
  echo "导出 MySQL -> ${DUMP_FILE}"
  docker compose exec -T mysql sh -c \
    'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --single-transaction --routines --databases "$MYSQL_DATABASE"' \
    > "${DUMP_FILE}"
  MYSQL_OK=1
  echo "mysql_dump=ok" >> "${MANIFEST}"
else
  echo "警告: mysql 服务未运行，跳过 mysqldump" >&2
  echo "mysql_dump=skipped" >> "${MANIFEST}"
fi

# 命名卷
for vol in "${DATA_VOLUMES[@]}"; do
  fq="$(volume_fq_name "${vol}")"
  out="${BACKUP_DIR}/${vol}.tar.gz"
  if docker volume inspect "${fq}" >/dev/null 2>&1; then
    echo "备份卷 ${fq} -> ${out}"
    ensure_image "${BACKUP_HELPER_IMAGE:-alpine:3.19}"
    docker run --rm \
      -v "${fq}:/data:ro" \
      -v "${BACKUP_DIR}:/backup" \
      "${BACKUP_HELPER_IMAGE:-alpine:3.19}" \
      tar czf "/backup/${vol}.tar.gz" -C /data .
    echo "${vol}=ok" >> "${MANIFEST}"
  else
    echo "警告: 卷不存在，跳过: ${fq}" >&2
    echo "${vol}=missing" >> "${MANIFEST}"
  fi
done

# .env（含密钥，请妥善保管）
if [[ -f "${ROOT}/.env" ]]; then
  cp "${ROOT}/.env" "${BACKUP_DIR}/env.snapshot"
  echo "env_snapshot=ok" >> "${MANIFEST}"
fi

echo ""
echo "备份完成: ${BACKUP_DIR}"
echo "清单: ${MANIFEST}"
[[ "${MYSQL_OK}" -eq 1 ]] && echo "  - mysql_${STAMP}.sql（含积分/物料/公告栏位等）"
ls -lh "${BACKUP_DIR}"/*.tar.gz 2>/dev/null || true
