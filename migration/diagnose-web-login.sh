#!/usr/bin/env bash
# 诊断「服务已起但无法登录 / 打不开登录页」
# 用法: cd 项目根 && bash migration/diagnose-web-login.sh
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

echo "========== 容器状态 =========="
docker compose ps 2>/dev/null || docker-compose ps

PORT="${GATEWAY_PUBLISH_PORT:-8000}"
PUB="$(grep -E '^PUBLIC_BASE_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"

echo ""
echo "========== 本机 IP 与 .env =========="
echo "局域网 IP（首个）: ${LAN_IP:-未知}"
echo "PUBLIC_BASE_URL:  ${PUB:-未设置}"
if [[ -n "${LAN_IP}" && -n "${PUB}" && "${PUB}" != *"${LAN_IP}"* ]]; then
  echo "警告: PUBLIC_BASE_URL 与当前 IP 不一致，Windows 访问请用 https://${LAN_IP}:${PORT}/login"
  echo "      或在 .env 改为 PUBLIC_BASE_URL=https://${LAN_IP}:${PORT} 后 docker compose up -d"
fi

echo ""
echo "========== HTTPS 探测 =========="
if curl -sI "http://127.0.0.1:${PORT}/gateway-health" 2>/dev/null | head -1 | grep -q 200; then
  echo "OK: gateway-health"
else
  echo "失败: gateway 未响应，执行: docker compose up -d gateway"
fi
if curl -sI "http://127.0.0.1:${PORT}/login" 2>/dev/null | head -1 | grep -qE '200|405'; then
  echo "OK: /login 可达（405 为 HEAD 请求正常）"
else
  echo "失败: /login 不可达，须使用 https:// 而非 http://"
fi

echo ""
echo "========== 登录限制（验证码/封禁）=========="
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stack-htmlsystm$'; then
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --clear-blocks 2>/dev/null && \
    echo "已清除登录失败记录与 IP 封禁（建议: docker compose restart htmlsystm）" || \
    echo "无法自动清除，请手动: docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --clear-blocks"
else
  echo "stack-htmlsystm 未运行，跳过"
fi

echo ""
echo "========== 会话与用户（MySQL）=========="
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stack-mysql$'; then
  bash "$ROOT/migration/verify-login-sessions.sh" 2>/dev/null || echo "verify-login-sessions.sh 执行失败"
else
  echo "stack-mysql 未运行，跳过"
fi

echo ""
echo "========== 浏览器访问 =========="
echo "  虚拟机内: http://127.0.0.1:${PORT}/login"
if [[ -n "${LAN_IP}" ]]; then
  echo "  局域网:   https://${LAN_IP}:${PORT}/login"
fi
echo "  须 https://；自签证书点「继续访问」"
echo "  若仍失败: 浏览器清除本站缓存；关闭「自动登录」后重试；需要验证码时填写验证码"
echo "  忘记密码: bash migration/fix-mysql-and-admin.sh"
