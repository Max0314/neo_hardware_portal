#!/usr/bin/env bash
# 目标机一键：load 镜像 → 恢复卷 → up 并自检（需先放好项目与 .env）
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_common.sh
source "${DIR}/_common.sh"

BACKUP_DIR="${1:-}"
TAR="${2:-}"

if [[ -z "${BACKUP_DIR}" || ! -d "${BACKUP_DIR}" ]]; then
  echo "用法: $0 <备份目录> [stack_images.tar 路径，默认同目录/stack_images.tar]" >&2
  exit 1
fi

TAR="${TAR:-${BACKUP_DIR}/stack_images.tar}"

echo "========== 目标机离线恢复（备份: ${BACKUP_DIR}）=========="
bash "${DIR}/05-target-load-images.sh" "${TAR}"
bash "${DIR}/06-target-restore-volumes.sh" "${BACKUP_DIR}"
echo ""
echo "请确认已编辑 .env 中的 PUBLIC_BASE_URL 为新服务器地址，然后继续..."
bash "${DIR}/07-target-up-verify.sh"
