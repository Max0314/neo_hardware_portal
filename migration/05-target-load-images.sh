#!/usr/bin/env bash
# 阶段 B2：目标机 docker load 离线镜像包
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_docker

TAR="${1:-}"
if [[ -z "${TAR}" || ! -f "${TAR}" ]]; then
  echo "用法: $0 <stack_images.tar 路径>" >&2
  exit 1
fi

echo "加载镜像: ${TAR}"
docker load -i "${TAR}"
echo ""
echo "当前镜像:"
docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}'
echo ""
echo "若 compose up 仍尝试拉取或 build，请核对镜像 tag 与源机 images_list.txt 一致。"
