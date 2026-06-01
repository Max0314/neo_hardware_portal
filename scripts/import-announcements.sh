#!/usr/bin/env bash
# 在全新 deploy 成功后，导入公告栏数据（announcements/ + MySQL 分类/待办）
# 用法: ./scripts/import-announcements.sh <备份目录>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

# shellcheck source=/dev/null
source "${ROOT}/migration/_common.sh"
require_compose

BACKUP_DIR="${1:-}"
if [[ -z "${BACKUP_DIR}" || ! -d "${BACKUP_DIR}" ]]; then
  echo "用法: $0 <备份目录>" >&2
  echo "  目录须含 announcements_only.tar.gz 或 htmlsystm_data.tar.gz，以及 announcement_meta.sql" >&2
  exit 1
fi

BACKUP_DIR="$(cd "${BACKUP_DIR}" && pwd)"
export VOLUME_PREFIX="${VOLUME_PREFIX:-$(get_compose_project_name)}"
VOL_FQ="$(volume_fq_name htmlsystm_data)"

ANN_TAR=""
if [[ -f "${BACKUP_DIR}/announcements_only.tar.gz" ]]; then
  ANN_TAR="${BACKUP_DIR}/announcements_only.tar.gz"
elif [[ -f "${BACKUP_DIR}/htmlsystm_data.tar.gz" ]]; then
  ANN_TAR="${BACKUP_DIR}/htmlsystm_data.tar.gz"
else
  echo "错误: 未找到 announcements_only.tar.gz 或 htmlsystm_data.tar.gz" >&2
  exit 1
fi

META_SQL="${BACKUP_DIR}/announcement_meta.sql"
if [[ ! -f "${META_SQL}" ]]; then
  # 兼容 backup-all 产出的完整 dump（仅导入公告相关表需手动筛选时仍可用 meta 文件）
  CANDIDATE="$(ls -1 "${BACKUP_DIR}"/mysql_*.sql 2>/dev/null | head -1 || true)"
  if [[ -n "${CANDIDATE}" ]]; then
    echo "未找到 announcement_meta.sql，将使用完整 MySQL dump: ${CANDIDATE}"
    echo "警告: 完整 dump 会覆盖用户/积分等全部表；若只需公告分类请先用 export-announcements.sh" >&2
    META_SQL="${CANDIDATE}"
    FULL_DUMP=1
  else
    echo "错误: 未找到 announcement_meta.sql 或 mysql_*.sql" >&2
    exit 1
  fi
fi

echo "========== 公告栏导入 =========="
echo "卷前缀: ${VOLUME_PREFIX}"
echo "备份目录: ${BACKUP_DIR}"
echo "公告归档: ${ANN_TAR}"
echo "MySQL 文件: ${META_SQL}"

if ! docker volume inspect "${VOL_FQ}" >/dev/null 2>&1; then
  echo "错误: 卷不存在: ${VOL_FQ}（请先 bash migration/deploy.sh）" >&2
  exit 1
fi

ensure_image "${BACKUP_HELPER_IMAGE:-alpine:3.19}"

echo "停止 htmlsystm（避免写入冲突）..."
docker compose stop htmlsystm

echo "恢复 announcements/ -> 卷 ${VOL_FQ}"
docker run --rm \
  -v "${VOL_FQ}:/data" \
  -v "${BACKUP_DIR}:/backup:ro" \
  "${BACKUP_HELPER_IMAGE:-alpine:3.19}" sh -c \
  "cd /data && rm -rf announcements && tar xzf /backup/$(basename "${ANN_TAR}") announcements"

if [[ "${FULL_DUMP:-0}" == "1" ]]; then
  echo "导入完整 MySQL dump..."
  docker compose start mysql
  sleep 10
  docker compose exec -T mysql sh -c \
    'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
    < "${META_SQL}"
else
  echo "清空并导入公告相关 MySQL 表..."
  docker compose start mysql
  sleep 10
  docker compose exec -T mysql sh -c \
    'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "SET FOREIGN_KEY_CHECKS=0; TRUNCATE todos; TRUNCATE sub_boards; TRUNCATE primary_boards; SET FOREIGN_KEY_CHECKS=1;"'
  docker compose exec -T mysql sh -c \
    'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
    < "${META_SQL}"
fi

echo "启动全栈..."
docker compose up -d
sleep 5
bash migration/check-stack.sh

echo ""
echo "导入完成。请登录后验收："
echo "  - 公告栏分类与正文、附件是否正常"
echo "  - 用户账号未包含在本导入中，需在新环境单独建用户或同步钉钉"
