#!/usr/bin/env bash
# 离线整机迁移 — 公共函数（在仓库根目录的 migration/ 下调用）
set -euo pipefail

MIGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${MIGRATION_DIR}/.." && pwd)"
cd "${ROOT}"

# 数据库在 NeoFlowData（外部），mysql_data 卷已随迁移退役
DATA_VOLUMES=(htmlsystm_data htmlsystm_uploads ai_chatroom_data)

# ---------- 外部 MySQL（NeoFlowData）----------
# 数据库不在本栈内，统一用宿主机 mysql 客户端 + .env 凭据访问。
# 密码经 MYSQL_PWD 环境变量传递，不进入 ps 输出与 shell 历史。

_env_value() {
  local root="${ROOT:-$(pwd)}"
  grep -E "^$1=" "${root}/.env" 2>/dev/null | tail -n1 | cut -d= -f2-
}

mysql_cli() {
  local host port user pass db
  host="$(_env_value MYSQL_HOST)"
  port="$(_env_value MYSQL_PORT)"; port="${port:-3306}"
  user="$(_env_value MYSQL_USER)"
  pass="$(_env_value MYSQL_PASSWORD)"
  db="$(_env_value MYSQL_DATABASE)"
  if [[ -z "$host" || -z "$user" || -z "$pass" || -z "$db" ]]; then
    echo "错误: .env 缺少 MYSQL_HOST/USER/PASSWORD/DATABASE" >&2
    return 1
  fi
  MYSQL_PWD="$pass" mysql --default-character-set=utf8mb4     -h "$host" -P "$port" -u "$user" "$db" "$@"
}

mysql_dump_cli() {
  local host port user pass db
  host="$(_env_value MYSQL_HOST)"
  port="$(_env_value MYSQL_PORT)"; port="${port:-3306}"
  user="$(_env_value MYSQL_USER)"
  pass="$(_env_value MYSQL_PASSWORD)"
  db="$(_env_value MYSQL_DATABASE)"
  MYSQL_PWD="$pass" mysqldump --default-character-set=utf8mb4     --single-transaction --no-tablespaces --set-gtid-purged=OFF     -h "$host" -P "$port" -u "$user" "$db" "$@"
}

mysql_reachable() {
  mysql_cli -N -e "SELECT 1" >/dev/null 2>&1
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "错误: 未找到 docker 命令" >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "错误: 无法连接 Docker（权限或 daemon 未启动）" >&2
    exit 1
  fi
}

require_compose() {
  require_docker
  if ! docker compose version >/dev/null 2>&1; then
    echo "错误: 未找到 docker compose（请安装 Compose V2 插件）" >&2
    exit 1
  fi
}

# 从 .env 读取 COMPOSE_PROJECT_NAME；未设置则尝试从已有卷名推断
get_compose_project_name() {
  if [[ -f "${ROOT}/.env" ]]; then
    local from_env
    from_env="$(grep -E '^[[:space:]]*COMPOSE_PROJECT_NAME=' "${ROOT}/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr -d '"' | tr -d "'")"
    if [[ -n "${from_env}" ]]; then
      echo "${from_env}"
      return 0
    fi
  fi
  detect_volume_prefix_from_docker
}

detect_volume_prefix_from_docker() {
  local vol line prefix
  vol="$(docker volume ls -q 2>/dev/null | grep '_mysql_data$' | head -1 || true)"
  if [[ -z "${vol}" ]]; then
    # 默认：目录名规范化（与 Compose 行为接近，仅作兜底）
    local base
    base="$(basename "${ROOT}")"
    echo "${base}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//'
    return 0
  fi
  prefix="${vol%_mysql_data}"
  echo "${prefix}"
}

volume_fq_name() {
  local suffix="$1"
  local prefix="${VOLUME_PREFIX:-$(get_compose_project_name)}"
  echo "${prefix}_${suffix}"
}

default_backup_dir() {
  echo "${ROOT}/migration_backup_$(date +%Y%m%d_%H%M%S)"
}

# 本地已有镜像则绝不 pull（避免弱网下重复下载）
image_exists() {
  docker image inspect "$1" >/dev/null 2>&1
}

ensure_image() {
  local img="$1"
  if image_exists "${img}"; then
    echo "本地已有，跳过拉取: ${img}"
    return 0
  fi
  echo "本地无此镜像，正在拉取: ${img}"
  docker pull "${img}"
}

# 备份卷用的临时容器镜像（默认 alpine）
BACKUP_HELPER_IMAGE="${BACKUP_HELPER_IMAGE:-alpine:3.19}"

compose_images_for_save() {
  require_compose
  local project imgs=()
  project="$(get_compose_project_name)"
  while IFS= read -r line; do
    [[ -n "${line}" ]] && imgs+=("${line}")
  done < <(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^${project}-" || true)
  echo "mysql:8.0"
  echo "nginx:alpine"
  printf '%s\n' "${imgs[@]}"
}
