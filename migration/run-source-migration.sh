#!/usr/bin/env bash
# 源机一键：记录状态 → 停栈备份卷 → 导出镜像 → 生成拷贝清单
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_common.sh
source "${DIR}/_common.sh"
BACKUP_DIR="${1:-$(default_backup_dir)}"
mkdir -p "${BACKUP_DIR}"

echo "========== 源机离线迁移（备份目录: ${BACKUP_DIR}）=========="
bash "${DIR}/01-record-state.sh" "${BACKUP_DIR}"
bash "${DIR}/02-backup-volumes.sh" "${BACKUP_DIR}"
bash "${DIR}/03-export-images.sh" "${BACKUP_DIR}"
bash "${DIR}/04-transfer-checklist.sh" "${BACKUP_DIR}"

echo ""
echo "========== 源机步骤完成 =========="
echo "请将项目目录、.env 与 ${BACKUP_DIR} 拷到 U 盘，在目标机按 migration/04 清单操作。"
