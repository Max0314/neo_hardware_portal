#!/usr/bin/env bash
# 检查 MySQL 应用账号、容器环境变量、.env 是否一致（排查「改密后仍登录失败」）
# 用法: cd 项目根 && bash migration/check-db-config.sh
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  sed -i 's/\r$//' "$_self"
  exec bash "$_self" "$@"
fi
unset _self
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi

echo "========== 1. .env 中的 MySQL / 管理员相关 =========="
grep -E '^(COMPOSE_PROJECT_NAME|MYSQL_|SUPER_ADMIN_)' .env 2>/dev/null || echo "(无 .env)"
echo ""
echo "说明:"
echo "  - 应用连接 MySQL 使用 MYSQL_USER + MYSQL_PASSWORD（不是 SUPER_ADMIN_PASSWORD）"
echo "  - zzw 登录密码保存在数据卷 htmlsystm_data 内 admin_credentials.json，与 .env 无关"
if grep -q '^SUPER_ADMIN_PASSWORD=' .env 2>/dev/null; then
  echo "  ⚠️  .env 中仍有 SUPER_ADMIN_PASSWORD，已不再用于 zzw 登录（可删除该行）"
fi
if [[ -n "${MYSQL_PASSWORD:-}" && -n "${SUPER_ADMIN_PASSWORD:-}" && "${MYSQL_PASSWORD}" != "${SUPER_ADMIN_PASSWORD}" ]]; then
  echo "  ⚠️  MYSQL_PASSWORD 与 SUPER_ADMIN_PASSWORD 不一致（正常：二者用途不同）"
fi

echo ""
echo "========== 2. 外部数据库目标（NeoFlowData）=========="
grep -E '^MYSQL_(HOST|PORT|USER|DATABASE)=' .env 2>/dev/null || echo ".env 缺少 MYSQL_* 配置"
echo "(MYSQL_PASSWORD 不打印，避免泄露)"

echo ""
echo "========== 3. stack-htmlsystm 容器 MySQL 连接变量 =========="
if docker ps --format '{{.Names}}' | grep -q '^stack-htmlsystm$'; then
  docker exec stack-htmlsystm printenv MYSQL_HOST MYSQL_USER MYSQL_DATABASE 2>/dev/null || true
else
  echo "stack-htmlsystm 未运行"
fi

echo ""
echo "========== 4. MySQL 连接测试（.env 凭据直连 NeoFlowData）=========="
# shellcheck source=_common.sh
source "${ROOT}/migration/_common.sh"
if mysql_reachable; then
  echo "OK: .env 的 MYSQL_* 可连接外部数据库"
else
  echo "失败: 外部数据库不可达，核对 .env 的 MYSQL_HOST/PORT/USER/PASSWORD 与内网连通性"
fi

echo ""
echo "========== 5. zzw 管理员凭据与登录校验 =========="
if docker ps --format '{{.Names}}' | grep -q '^stack-htmlsystm$'; then
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --show-admin 2>/dev/null || true
  echo "---"
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --diagnose zzw 2>/dev/null || true
else
  echo "stack-htmlsystm 未运行"
fi

echo ""
echo "========== 6. users 表 zzw 行（仅状态与哈希前缀）=========="
mysql_cli -e '
SELECT id, username, status, LEFT(password,7) AS pwd_prefix, CHAR_LENGTH(password) AS pwd_len
FROM users WHERE username="zzw" OR roles LIKE "%super_admin%" LIMIT 5;
' 2>/dev/null || echo "查询失败"
