#!/usr/bin/env bash
# 阶段 A5：构建并 docker save 全部镜像（离线迁移用）
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_compose

BACKUP_DIR="${1:-$(default_backup_dir)}"
mkdir -p "${BACKUP_DIR}"

OUT="${BACKUP_DIR}/stack_images.tar"

# 栈已在跑、镜像齐全时：SKIP_BUILD=1 SKIP_PULL=1 ./migration/03-export-images.sh
if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
  echo "SKIP_BUILD=1，跳过 docker compose build（使用本地已构建镜像）"
else
  echo "构建 compose 镜像（仅缺层时才会下载；已有可设 SKIP_BUILD=1）..."
  docker compose build
fi

if [[ "${SKIP_PULL:-0}" == "1" ]]; then
  echo "SKIP_PULL=1，跳过 mysql/nginx 拉取检查"
else
  echo "检查基础镜像（本地已有则不会访问仓库）..."
  ensure_image mysql:8.0
  ensure_image nginx:alpine
fi

mapfile -t IMAGES < <(compose_images_for_save | sort -u)
# 过滤空行与本地不存在的镜像
SAVE_LIST=()
for img in "${IMAGES[@]}"; do
  [[ -z "${img}" ]] && continue
  if docker image inspect "${img}" >/dev/null 2>&1; then
    SAVE_LIST+=("${img}")
  else
    echo "跳过（本地不存在）: ${img}" >&2
  fi
done

if [[ ${#SAVE_LIST[@]} -eq 0 ]]; then
  echo "错误: 没有可保存的镜像" >&2
  exit 1
fi

echo "将保存以下镜像:"
printf '  %s\n' "${SAVE_LIST[@]}"
echo "${SAVE_LIST[@]}" | tr ' ' '\n' > "${BACKUP_DIR}/images_list.txt"

docker save -o "${OUT}" "${SAVE_LIST[@]}"
ls -lh "${OUT}"
echo ""
echo "镜像包已生成: ${OUT}"
echo "镜像列表: ${BACKUP_DIR}/images_list.txt"
