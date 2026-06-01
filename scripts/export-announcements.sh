#!/usr/bin/env bash
# 从运行中的栈导出公告栏数据（文件 announcements/ + MySQL 分类/待办表）
# 用法: ./scripts/export-announcements.sh [输出目录]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=/dev/null
source "${ROOT}/migration/_common.sh"
require_compose

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${1:-${ROOT}/backup/announce_export_${STAMP}}"
export VOLUME_PREFIX="${VOLUME_PREFIX:-$(get_compose_project_name)}"
mkdir -p "${BACKUP_DIR}"

VOL_FQ="$(volume_fq_name htmlsystm_data)"
ANN_ARCHIVE="${BACKUP_DIR}/announcements_only.tar.gz"
META_SQL="${BACKUP_DIR}/announcement_meta.sql"
MANIFEST="${BACKUP_DIR}/manifest.txt"

echo "========== 公告栏导出 =========="
echo "卷前缀: ${VOLUME_PREFIX}"
echo "输出目录: ${BACKUP_DIR}"

if ! docker volume inspect "${VOL_FQ}" >/dev/null 2>&1; then
  echo "错误: 卷不存在: ${VOL_FQ}" >&2
  exit 1
fi

ensure_image "${BACKUP_HELPER_IMAGE:-alpine:3.19}"
echo "导出 announcements/ -> ${ANN_ARCHIVE}"
docker run --rm \
  -v "${VOL_FQ}:/data:ro" \
  -v "${BACKUP_DIR}:/backup" \
  "${BACKUP_HELPER_IMAGE:-alpine:3.19}" \
  tar czf "/backup/announcements_only.tar.gz" -C /data announcements

MYSQL_OK=0
if docker compose ps mysql 2>/dev/null | grep -qE 'running|Up'; then
  echo "导出 MySQL 表 primary_boards, sub_boards, todos -> ${META_SQL}"
  docker compose exec -T mysql sh -c \
    'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --single-transaction "$MYSQL_DATABASE" primary_boards sub_boards todos' \
    > "${META_SQL}"
  MYSQL_OK=1
else
  echo "警告: mysql 未运行，跳过 announcement_meta.sql" >&2
fi

{
  echo "export_time=${STAMP}"
  echo "compose_project=${VOLUME_PREFIX}"
  echo "announcements_archive=announcements_only.tar.gz"
  echo "mysql_meta=announcement_meta.sql"
  echo "mysql_ok=${MYSQL_OK}"
} > "${MANIFEST}"

echo ""
echo "导出完成: ${BACKUP_DIR}"
ls -lh "${BACKUP_DIR}"
echo ""
echo "请将整个目录拷贝到 U 盘/NAS，在新服务器 deploy 后执行:"
echo "  ./scripts/import-announcements.sh ${BACKUP_DIR}"
