#!/usr/bin/env bash
set -euo pipefail

# 将已绑定钉钉的 20461992 提升为 super_admin，并执行钉钉登录上线前审计。
# 用法: cd 项目根 && bash migration/enable-dingtalk-super-admin.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET_USERNAME="${DINGTALK_SUPER_ADMIN_USERNAME:-20461992}"

# shellcheck source=_common.sh
source "${ROOT}/migration/_common.sh"
if ! mysql_reachable; then
  echo "外部数据库不可达（核对 .env 的 MYSQL_*）" >&2
  exit 1
fi

mysql_exec() {
  mysql_cli -N -B -e "$MYSQL_SQL" 2>/dev/null
}

echo "========== 1. 检查目标钉钉管理员 =========="
MYSQL_SQL="
SELECT id, username, status,
       IF(dingtalk_userid IS NULL OR dingtalk_userid='', 'NO', 'YES') AS has_dingtalk,
       roles
FROM users
WHERE username='${TARGET_USERNAME}'
LIMIT 1;
"
target_row="$(MYSQL_SQL="$MYSQL_SQL" mysql_exec || true)"
if [ -z "$target_row" ]; then
  echo "未找到目标用户: ${TARGET_USERNAME}" >&2
  exit 1
fi
echo "$target_row"

has_dingtalk="$(printf '%s\n' "$target_row" | awk -F'\t' '{print $4}')"
status="$(printf '%s\n' "$target_row" | awk -F'\t' '{print $3}')"
if [ "$has_dingtalk" != "YES" ]; then
  echo "目标用户 ${TARGET_USERNAME} 未绑定 dingtalk_userid，不能关闭密码入口。" >&2
  exit 1
fi
if [ "$status" != "active" ]; then
  echo "目标用户 ${TARGET_USERNAME} 状态不是 active: ${status}" >&2
  exit 1
fi

echo "========== 2. 提升 super_admin =========="
MYSQL_SQL="
UPDATE users
SET roles = CASE
    WHEN roles IS NULL OR roles = '' THEN 'super_admin'
    WHEN FIND_IN_SET('super_admin', roles) > 0 THEN roles
    ELSE CONCAT(roles, ',super_admin')
  END,
  updated_time = NOW()
WHERE username='${TARGET_USERNAME}'
  AND dingtalk_userid IS NOT NULL
  AND dingtalk_userid <> '';
SELECT id, username, roles, status,
       IF(dingtalk_userid IS NULL OR dingtalk_userid='', 'NO', 'YES') AS has_dingtalk
FROM users
WHERE username='${TARGET_USERNAME}'
LIMIT 1;
"
MYSQL_SQL="$MYSQL_SQL" mysql_exec

echo "========== 3. 审计 dingtalk_userid 重复 =========="
MYSQL_SQL="
SELECT COUNT(*) FROM (
  SELECT dingtalk_userid
  FROM users
  WHERE dingtalk_userid IS NOT NULL AND dingtalk_userid <> ''
  GROUP BY dingtalk_userid
  HAVING COUNT(*) > 1
) t;
"
dup_count="$(MYSQL_SQL="$MYSQL_SQL" mysql_exec | tr -d '\r\n ')"
echo "duplicate_dingtalk_userid=${dup_count}"
if [ "${dup_count:-0}" != "0" ]; then
  echo "存在重复 dingtalk_userid，请先处理后再上线。" >&2
  exit 1
fi

echo "========== 4. 审计已绑定钉钉的 super_admin =========="
MYSQL_SQL="
SELECT COUNT(*)
FROM users
WHERE status='active'
  AND FIND_IN_SET('super_admin', roles) > 0
  AND dingtalk_userid IS NOT NULL
  AND dingtalk_userid <> '';
"
bound_super_count="$(MYSQL_SQL="$MYSQL_SQL" mysql_exec | tr -d '\r\n ')"
echo "bound_active_super_admin=${bound_super_count}"
if [ "${bound_super_count:-0}" -lt 1 ]; then
  echo "没有已绑定钉钉的 active super_admin，禁止关闭密码入口。" >&2
  exit 1
fi

echo "完成：钉钉 super_admin 迁移与审计通过。"
