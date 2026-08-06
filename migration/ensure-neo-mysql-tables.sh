#!/usr/bin/env bash
# 为已有 MySQL 库补建 NEO 积分/看板表（neo_point_events 等），并重启 neo-backend
# 用法: cd 项目根目录 && bash migration/ensure-neo-mysql-tables.sh
# VirtualBox 共享文件夹常为 CRLF，须在 set -o pipefail 之前自修复
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  sed -i 's/\r$//' "$_self"
  exec bash "$_self" "$@"
fi
unset _self
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

MYSQL_USER="${MYSQL_USER:-htmlsystm_user}"
MYSQL_DATABASE="${MYSQL_DATABASE:-htmlsystm}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?请在 .env 中设置 MYSQL_PASSWORD}"

# shellcheck source=_common.sh
source "${ROOT}/migration/_common.sh"
if ! mysql_reachable; then
  echo "错误: 外部数据库不可达（核对 .env 的 MYSQL_*）" >&2
  exit 1
fi

neo_table_exists() {
  mysql_cli -N -e "SHOW TABLES LIKE 'neo_point_events';" 2>/dev/null \
    | grep -q '^neo_point_events$'
}

echo "========== 补建 NEO MySQL 表 =========="
if docker ps --format '{{.Names}}' | grep -q '^stack-htmlsystm$'; then
  if docker exec stack-htmlsystm python -c "
from server.db_adapter import get_connection_pool
from server.mysql_schema import create_neo_metrics_tables
pool = get_connection_pool()
with pool.get_cursor() as c:
    create_neo_metrics_tables(c)
print('OK')
" 2>/dev/null; then
    echo "已通过 stack-htmlsystm 创建/确认 NEO 表"
  else
    echo "htmlsystm Python 建表失败，改为直连外部库执行 SQL..."
    mysql_cli <<'EOSQL'
CREATE TABLE IF NOT EXISTS neo_point_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    user_key VARCHAR(128) NOT NULL,
    points DOUBLE NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    INDEX idx_neo_point_events_user (user_key),
    INDEX idx_neo_point_events_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS neo_user_point_balances (
    user_key VARCHAR(128) PRIMARY KEY,
    total_points DOUBLE NOT NULL DEFAULT 0,
    month_points DOUBLE NOT NULL DEFAULT 0,
    month_id VARCHAR(16) NOT NULL DEFAULT '',
    updated_at VARCHAR(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS neo_feature_uses (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    feature VARCHAR(128) NOT NULL,
    user_key VARCHAR(128) NULL,
    created_at VARCHAR(32) NOT NULL,
    INDEX idx_neo_feature_uses_created (created_at),
    INDEX idx_neo_feature_uses_user (user_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS neo_bom_info_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    info_count INT NOT NULL,
    user_key VARCHAR(128) NULL,
    created_at VARCHAR(32) NOT NULL,
    INDEX idx_neo_bom_info_created (created_at),
    INDEX idx_neo_bom_info_user (user_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
EOSQL
    echo "已直连外部库创建/确认 NEO 表"
  fi
else
  mysql_cli <<'EOSQL'
CREATE TABLE IF NOT EXISTS neo_point_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    user_key VARCHAR(128) NOT NULL,
    points DOUBLE NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    INDEX idx_neo_point_events_user (user_key),
    INDEX idx_neo_point_events_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS neo_user_point_balances (
    user_key VARCHAR(128) PRIMARY KEY,
    total_points DOUBLE NOT NULL DEFAULT 0,
    month_points DOUBLE NOT NULL DEFAULT 0,
    month_id VARCHAR(16) NOT NULL DEFAULT '',
    updated_at VARCHAR(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS neo_feature_uses (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    feature VARCHAR(128) NOT NULL,
    user_key VARCHAR(128) NULL,
    created_at VARCHAR(32) NOT NULL,
    INDEX idx_neo_feature_uses_created (created_at),
    INDEX idx_neo_feature_uses_user (user_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS neo_bom_info_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    info_count INT NOT NULL,
    user_key VARCHAR(128) NULL,
    created_at VARCHAR(32) NOT NULL,
    INDEX idx_neo_bom_info_created (created_at),
    INDEX idx_neo_bom_info_user (user_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
EOSQL
  echo "已直连外部库创建/确认 NEO 表"
fi

if neo_table_exists; then
  echo "校验: neo_point_events 已存在"
else
  echo "错误: 建表后仍未发现 neo_point_events，请检查 MYSQL_USER/MYSQL_PASSWORD 与 .env 是否一致" >&2
  exit 1
fi

echo ""
echo "========== 重启 NEO 后端 =========="
docker compose restart backend

echo ""
echo "========== 校验日志（应含 storage=mysql）=========="
sleep 4
docker logs stack-neo-backend --tail 25 2>&1 || true
