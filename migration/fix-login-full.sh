#!/usr/bin/env bash
# 全部用户登录失败 — 一键排障与重建（对应运维手册登录排障计划）
# 用法: cd 项目根 && bash migration/fix-login-full.sh [管理员新密码]
#   可选参数: 传入新密码时执行 fix-mysql-and-admin.sh 对齐 zzw 密码
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

NEW_ADMIN_PASS="${1:-}"

echo "========== 1/6 诊断 =========="
bash migration/diagnose-web-login.sh || true
bash migration/verify-login-sessions.sh || true
bash migration/check-stack.sh || true

echo ""
echo "========== 2/6 清除封禁 / 验证码锁 =========="
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stack-htmlsystm$'; then
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --clear-blocks
  docker compose restart htmlsystm
  echo "已 clear-blocks 并重启 htmlsystm"
else
  echo "警告: stack-htmlsystm 未运行，跳过 clear-blocks"
fi

if [[ -n "$NEW_ADMIN_PASS" ]]; then
  echo ""
  echo "========== 3/6 对齐 MySQL + 管理员密码 =========="
  bash migration/fix-mysql-and-admin.sh "$NEW_ADMIN_PASS"
else
  echo ""
  echo "========== 3/6 跳过改密（未传参）=========="
  echo "  若忘记 zzw 密码: bash migration/fix-login-full.sh 'YourSecurePass123!'"
fi

echo ""
echo "========== 4/6 重建 htmlsystm / backend / gateway =========="
docker compose up -d --build --force-recreate htmlsystm backend gateway

echo ""
echo "========== 5/6 等待健康检查 =========="
sleep 8
docker compose ps

echo ""
echo "========== 6/6 curl 登录验收 =========="
PORT="${GATEWAY_PUBLISH_PORT:-8000}"
ADMIN_USER="${SUPER_ADMIN_USERNAME:-zzw}"
ADMIN_PASS="${NEW_ADMIN_PASS:-}"
if [ -z "$ADMIN_PASS" ] && docker ps --format '{{.Names}}' | grep -q '^stack-htmlsystm$'; then
  ADMIN_PASS="$(docker exec stack-htmlsystm python -c "
from server.admin_credentials import load_credentials
c = load_credentials()
print(c['password'] if c else '', end='')
" 2>/dev/null || true)"
fi

curl -s "http://127.0.0.1:${PORT}/api/auth/check" | head -1 || true
echo ""

if [[ -z "$ADMIN_PASS" ]]; then
  echo "未传新密码且 admin_credentials.json 不可用，跳过登录 curl 测试。"
  echo "可先执行: bash migration/fix-mysql-and-admin.sh 'YourPass' 或 docker exec ... --show-admin"
  echo "请浏览器: 清除 Cookie/关自动登录 → https://<IP>:${PORT}/login → 用改密后新密码手动登录"
  exit 0
fi

CJ="$(mktemp)"
trap 'rm -f "$CJ"' EXIT
LOGIN_BODY="$(curl -s -c "$CJ" -b "$CJ" -X POST "http://127.0.0.1:${PORT}/api/auth/login" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "username=${ADMIN_USER}&password=${ADMIN_PASS}" 2>&1 || true)"
echo "POST /api/auth/login: $(echo "$LOGIN_BODY" | head -c 200)"
CHECK_BODY="$(curl -s -b "$CJ" "http://127.0.0.1:${PORT}/api/auth/check" 2>&1 || true)"
echo "GET /api/auth/check: $CHECK_BODY"

if echo "$CHECK_BODY" | grep -q '"authenticated"[[:space:]]*:[[:space:]]*true'; then
  echo "OK: 登录与会话校验通过"
else
  echo "!!! 登录验收失败 — 请执行: bash migration/verify-login-sessions.sh"
  echo "    并查看: docker logs stack-htmlsystm --tail 80"
  exit 1
fi

echo ""
echo "浏览器: 清除本站 Cookie；关闭自动登录；使用新密码访问 https://<局域网IP>:${PORT}/login"
