#!/usr/bin/env bash
# 阶段 B5–B6 + C：启动栈并做基本 HTTP 自检
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_compose

PORT="${GATEWAY_PUBLISH_PORT:-8000}"
if [[ -f "${ROOT}/.env" ]]; then
  val="$(grep -E '^[[:space:]]*GATEWAY_PUBLISH_PORT=' "${ROOT}/.env" | tail -1 | cut -d= -f2- | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -n "${val}" ]] && PORT="${val}"
fi

NO_BUILD="${NO_BUILD:-1}"
# shellcheck source=lib-compose-core.sh
source "$(dirname "$0")/lib-compose-core.sh"
if [[ "${NO_BUILD}" == "1" ]]; then
  echo "启动核心栈（离线模式，不 --build，不含 autoheal）..."
  compose_up_core
else
  echo "启动核心栈（含 --build）..."
  compose_up_core --build
fi

echo "等待服务就绪..."
sleep 8
docker compose ps

echo ""
echo "=== HTTPS 自检 (127.0.0.1:${PORT}，-k 忽略自签) ==="
for path in "/login" "/neo/"; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}${path}" 2>/dev/null || echo "000")"
  echo "  ${path} -> HTTPS ${code}"
done

if [[ -f "${ROOT}/.env" ]]; then
  pub="$(grep -E '^[[:space:]]*PUBLIC_BASE_URL=' "${ROOT}/.env" | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
  echo ""
  echo "PUBLIC_BASE_URL=${pub:-（未设置，钉钉跳转可能异常）}"
fi

echo ""
echo "请用浏览器访问: https://<目标机局域网IP>:${PORT}/login 与 /neo/"
echo "验收: 登录管理系统、NEO 历史数据、上传文件、钉钉通知 URL。"
