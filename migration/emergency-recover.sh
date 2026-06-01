#!/usr/bin/env bash
# 紧急恢复访问：拉起核心容器（不依赖 autoheal / Docker Hub），可选重置 zzw 密码
# 用法:
#   bash migration/emergency-recover.sh
#   bash migration/emergency-recover.sh 'YourSecurePass123!'
#   bash migration/emergency-recover.sh --skip-password
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  sed -i 's/\r$//' "$_self" migration/lib-compose-core.sh
  exec bash "$_self" "$@"
fi
unset _self
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lib-compose-core.sh
source "${ROOT}/migration/lib-compose-core.sh"

ADMIN_PW=""
SKIP_PASSWORD=0
for arg in "$@"; do
  case "$arg" in
    --skip-password) SKIP_PASSWORD=1 ;;
    -h|--help)
      echo "用法: bash migration/emergency-recover.sh ['管理员密码≥12位'] [--skip-password]"
      exit 0
      ;;
    *)
      if [ -z "$ADMIN_PW" ] && [ "${#arg}" -ge 12 ]; then
        ADMIN_PW="$arg"
      fi
      ;;
  esac
done

echo "========== 1/5 最小登录栈（mysql + htmlsystm + gateway）=========="
echo "（网关不等待 NEO backend healthy，/login 可走管理系统）"
compose_up_minimal_login
bash "${ROOT}/migration/clear-startup-lock.sh" || true

echo ""
echo "========== 2/5 尝试拉起 NEO（失败不影响登录）=========="
compose_up_neo_optional || true

echo ""
echo "========== 3/5 等待健康检查 =========="
for name in stack-mysql stack-htmlsystm stack-gateway stack-neo-backend stack-neo-web; do
  for i in $(seq 1 45); do
    if ! docker ps --format '{{.Names}}' | grep -qx "$name"; then
      if [ "$name" = "stack-gateway" ] && [ "$i" -gt 5 ]; then
        echo "  ⚠️  $name 未运行，尝试强制启动..." >&2
        docker compose "${COMPOSE_EMERGENCY[@]}" up -d gateway 2>/dev/null || true
      fi
      sleep 2
      continue
    fi
    hs="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$name" 2>/dev/null || echo missing)"
    if [ "$hs" = "healthy" ] || [ "$hs" = "running" ]; then
      echo "  OK  $name ($hs)"
      break
    fi
    if [ "$i" -eq 45 ]; then
      echo "  ⚠️  $name 未 healthy ($hs)" >&2
      if [ "$name" = "stack-neo-backend" ]; then
        echo "      诊断: bash migration/diagnose-neo-backend.sh" >&2
      fi
    fi
    sleep 2
  done
done

echo ""
echo "========== 4/5 容器状态 =========="
docker compose ps -a

if [ "$SKIP_PASSWORD" -eq 0 ] && [ -n "$ADMIN_PW" ]; then
  echo ""
  echo "========== 5/5 重置 zzw 登录密码 =========="
  if ! docker ps --format '{{.Names}}' | grep -q '^stack-htmlsystm$'; then
    echo "错误: stack-htmlsystm 未运行" >&2
    exit 1
  fi
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py \
    --reset zzw --password "$ADMIN_PW"
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --clear-blocks || true
  docker compose restart htmlsystm
  sleep 8
  echo ""
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py \
    --diagnose zzw --password "$ADMIN_PW" || true
  echo ""
  echo "登录: https://<本机IP>:${GATEWAY_PUBLISH_PORT:-8000}/login"
  echo "  用户名: zzw"
  echo "  密码:   ${ADMIN_PW}"
else
  echo ""
  echo "========== 5/5 跳过改密 =========="
  echo "  bash migration/emergency-recover.sh 'YourSecurePass123!'"
fi

PORT="${GATEWAY_PUBLISH_PORT:-8000}"
if [ -f .env ]; then
  # shellcheck disable=SC1091
  . ./.env 2>/dev/null || true
  PORT="${GATEWAY_PUBLISH_PORT:-$PORT}"
fi
echo ""
echo "HTTPS 探测:"
if docker ps --format '{{.Names}}' | grep -q '^stack-gateway$'; then
  curl -sk -o /dev/null -w "  /api/health -> %{http_code}\n" "https://127.0.0.1:${PORT}/api/health" 2>/dev/null || true
  curl -sk -o /dev/null -w "  /login -> %{http_code}\n" "https://127.0.0.1:${PORT}/login" 2>/dev/null || true
else
  echo "  stack-gateway 未运行，请执行:"
  echo "    docker compose -f docker-compose.yml -f docker-compose.emergency.yml up -d gateway"
fi
echo ""
echo "完成。"
