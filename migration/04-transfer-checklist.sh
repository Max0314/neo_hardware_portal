#!/usr/bin/env bash
# 阶段 A6：列出需拷贝到 U 盘 / 目标机的文件清单
set -euo pipefail
source "$(dirname "$0")/_common.sh"

BACKUP_DIR="${1:-}"
if [[ -z "${BACKUP_DIR}" ]]; then
  # 找最新的 migration_backup_* 
  BACKUP_DIR="$(ls -dt "${ROOT}"/migration_backup_* 2>/dev/null | head -1 || true)"
fi

LIST="${ROOT}/migration/TRANSFER_MANIFEST.txt"

{
  echo "=== Docker 离线迁移 — 拷贝清单 ==="
  date -Iseconds 2>/dev/null || date
  echo
  echo "【必拷 — 项目目录】"
  echo "  整个目录: ${ROOT}"
  echo "  必须含: docker-compose.yml, gateway/, htmlsystm/, AI聊天室/, .env"
  echo "  可省略: node_modules/（目标机离线 up 时用已 load 镜像，无需 build）"
  echo
  echo "【必拷 — migration 脚本】"
  echo "  ${ROOT}/migration/"
  echo
  if [[ -n "${BACKUP_DIR}" && -d "${BACKUP_DIR}" ]]; then
    echo "【必拷 — 备份目录】"
    echo "  ${BACKUP_DIR}/"
    for f in migration_state.txt mysql_data.tar.gz htmlsystm_data.tar.gz \
             htmlsystm_uploads.tar.gz ai_chatroom_data.tar.gz \
             stack_images.tar images_list.txt; do
      if [[ -f "${BACKUP_DIR}/${f}" ]]; then
        echo "    [有] ${f}"
      else
        echo "    [缺] ${f}  ← 请先运行对应迁移脚本"
      fi
    done
  else
    echo "【备份目录】未指定或未找到 migration_backup_*"
    echo "  请先执行: ./migration/01-record-state.sh"
    echo "            ./migration/02-backup-volumes.sh <备份目录>"
    echo "            ./migration/03-export-images.sh <同一备份目录>"
  fi
  echo
  echo "【目标机可选】"
  echo "  Docker / Compose 离线 deb 或 compose 插件二进制"
  echo "  见 运维手册.md 第 2.1 节"
  echo
  echo "【目标机执行顺序】"
  echo "  1. 安装 Docker + Compose"
  echo "  2. 放置项目到目标路径（建议与源机相同的 COMPOSE_PROJECT_NAME）"
  echo "  3. ./migration/05-target-load-images.sh <备份目录>/stack_images.tar"
  echo "  4. ./migration/06-target-restore-volumes.sh <备份目录>"
  echo "  5. 编辑 .env 中 PUBLIC_BASE_URL 为新 IP"
  echo "  6. ./migration/07-target-up-verify.sh"
} | tee "${LIST}"

echo ""
echo "清单已写入: ${LIST}"
