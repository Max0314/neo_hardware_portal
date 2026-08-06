#!/usr/bin/env bash
# 统一备份：外部 MySQL（NeoFlowData）逻辑导出 + 三个本地缓存卷。
#
# 架构说明：数据库在 NeoFlowData（172.16.0.244），不在本栈内；文件持久层在
# OSS（写通镜像），本地卷只是缓存——备卷是为了缩短故障恢复时间，不是唯一副本。
#
# 本脚本不再保存 .env 快照：备份目录常被拷来拷去，凭据明文落进备份等于多一份
# 泄露面。需要恢复配置时以服务器上的 .env（chmod 600）为准。
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

# 外部 MySQL（凭据取自 .env；密码走环境变量，不进 ps 输出）
env_value() {
  grep -E "^$1=" "${ROOT}/.env" 2>/dev/null | tail -n1 | cut -d= -f2-
}

MYSQL_OK=0
DB_HOST="$(env_value MYSQL_HOST)"
DB_PORT="$(env_value MYSQL_PORT)"; DB_PORT="${DB_PORT:-3306}"
DB_USER="$(env_value MYSQL_USER)"
DB_PASS="$(env_value MYSQL_PASSWORD)"
DB_NAME="$(env_value MYSQL_DATABASE)"

if [[ -z "${DB_HOST}" || -z "${DB_USER}" || -z "${DB_PASS}" || -z "${DB_NAME}" ]]; then
  echo "警告: .env 缺少 MYSQL_HOST/USER/PASSWORD/DATABASE，跳过 mysqldump" >&2
  echo "mysql_dump=skipped" >> "${MANIFEST}"
elif ! command -v mysqldump >/dev/null 2>&1; then
  echo "警告: 本机无 mysqldump，跳过数据库导出" >&2
  echo "mysql_dump=skipped" >> "${MANIFEST}"
else
  DUMP_FILE="${BACKUP_DIR}/mysql_${STAMP}.sql.gz"
  echo "导出 MySQL ${DB_HOST}:${DB_PORT}/${DB_NAME} -> ${DUMP_FILE}"
  MYSQL_PWD="${DB_PASS}" mysqldump --default-character-set=utf8mb4 \
    --single-transaction --no-tablespaces --set-gtid-purged=OFF --routines \
    -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" "${DB_NAME}" \
    | gzip > "${DUMP_FILE}"
  MYSQL_OK=1
  echo "mysql_dump=ok" >> "${MANIFEST}"
  sha256sum "${DUMP_FILE}" >> "${MANIFEST}"
fi

# 本地缓存卷（文件持久层在 OSS；备卷用于快速恢复）
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

echo ""
echo "备份完成: ${BACKUP_DIR}"
echo "清单: ${MANIFEST}"
[[ "${MYSQL_OK}" -eq 1 ]] && echo "  - mysql_${STAMP}.sql.gz（积分/物料/公告栏位/聊天室）"
ls -lh "${BACKUP_DIR}"/*.tar.gz 2>/dev/null || true
