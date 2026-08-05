#!/usr/bin/env bash
# 部署后快速自检（在项目根目录执行：bash migration/check-stack.sh）
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

sed -i 's/\r$//' .env 2>/dev/null || true

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
PORT="${GATEWAY_PUBLISH_PORT:-8000}"

echo "========== 1. 容器状态 =========="
docker compose ps

echo ""
echo "========== 1b. 健康检查（Health）=========="
for c in stack-mysql stack-htmlsystm stack-neo-backend stack-neo-web stack-gateway stack-autoheal; do
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
  hs="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$c" 2>/dev/null || echo '?')"
  echo "  ${c}: ${hs}"
  else
  echo "  ${c}: (未创建)"
  fi
done

if ! docker compose ps --status running 2>/dev/null | grep -q stack-gateway; then
  echo ""
  echo "!!! 未检测到运行中的 stack-gateway（统一 HTTPS 入口）"
  echo "    浏览器访问 https://127.0.0.1:${PORT} 会「无法连接」。"
  echo "    请执行: docker compose up -d gateway"
  echo "    若启动失败: docker compose logs gateway --tail 50"
  if [[ "${ROOT}" == /media/* ]]; then
    echo ""
    echo "    提示: 项目在 VirtualBox 共享目录下时，开机常因挂载晚于 Docker 导致仅 gateway 起不来"
    echo "    （其它服务用命名卷可自启）。一次性修复: sudo bash migration/install-boot-service.sh"
  fi
  if ! systemctl is-enabled docker-stack.service &>/dev/null; then
    echo "    未配置开机自启: sudo bash migration/install-boot-service.sh"
  fi
fi

echo ""
echo "========== 2. 网关日志（末 15 行）=========="
docker logs stack-gateway --tail 15 2>&1 || true

echo ""
echo "========== 3. TLS 证书文件 =========="
if [ -f gateway/certs/server.crt ] && [ -f gateway/certs/server.key ]; then
  echo "OK: gateway/certs/server.crt 与 server.key 存在"
else
  echo "缺失证书！执行："
  echo "  mkdir -p gateway/certs"
  echo "  openssl req -x509 -nodes -days 825 -newkey rsa:2048 \\"
  echo "    -keyout gateway/certs/server.key -out gateway/certs/server.crt \\"
  echo "    -subj '/CN=localhost'"
fi

echo ""
echo "========== 4. 网关存活 + HTTPS 登录页（127.0.0.1:${PORT}）=========="
curl -skI "https://127.0.0.1:${PORT}/gateway-health" 2>&1 | head -5 || echo "gateway-health 失败：stack-gateway 未运行或未监听 ${PORT}"
echo "---"
curl -skI "https://127.0.0.1:${PORT}/login" 2>&1 | head -8 || echo "连接失败：gateway 未监听 ${PORT} 或 SSL 配置错误"

echo ""
echo "========== 5. auth/check API =========="
curl -sk "https://127.0.0.1:${PORT}/api/auth/check" 2>&1 | head -3 || true

echo ""
echo "========== 5a. 轻量存活 /api/health（经 gateway）=========="
HEALTH_BODY="$(curl -sk "https://127.0.0.1:${PORT}/api/health" 2>&1 || true)"
echo "$HEALTH_BODY" | head -1
if echo "$HEALTH_BODY" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
  echo "OK: htmlsystm /api/health"
else
  echo "提示: 若失败请 docker compose up -d --build htmlsystm gateway"
fi
echo "---"
echo "深度巡检（含 MySQL）:"
curl -sk "https://127.0.0.1:${PORT}/api/health?db=1" 2>&1 | head -1 || true

echo ""
echo "========== 5b. 登录 API 路由（须走 htmlsystm，勿进 NEO）=========="
LOGIN_PROBE="$(curl -sk -X POST "https://127.0.0.1:${PORT}/api/auth/login" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=__route_probe__&password=__route_probe__' 2>&1 || true)"
echo "$LOGIN_PROBE" | head -3
if echo "$LOGIN_PROBE" | grep -q '"detail"[[:space:]]*:[[:space:]]*"Not Found"'; then
  echo "!!! POST /api/auth/login 返回 FastAPI 404，说明请求进了 NEO 而非 htmlsystm"
  echo "    请执行: docker compose up -d --force-recreate gateway"
  echo "    并确认 gateway/proxy_locations.conf 含 location ^~ /api/auth/"
elif echo "$LOGIN_PROBE" | grep -q '"success"'; then
  echo "OK: 登录接口由管理系统处理（success 字段，非 detail: Not Found）"
else
  echo "提示: 若上方无 success 字段，请检查 stack-htmlsystm 日志"
fi

echo ""
echo "========== 6. NEO 积分表（MySQL）=========="
if docker ps --format '{{.Names}}' | grep -q '^stack-mysql$'; then
  NEO_TBL="$(docker exec stack-mysql mysql -u"${MYSQL_USER:-htmlsystm_user}" -p"${MYSQL_PASSWORD}" -N -e \
    "USE \`${MYSQL_DATABASE:-htmlsystm}\`; SHOW TABLES LIKE 'neo_point_events';" 2>&1 || true)"
  if echo "$NEO_TBL" | grep -q '^neo_point_events$'; then
    echo "OK: neo_point_events 存在"
  else
    echo "缺失 neo_point_events！"
    if [ "${AUTO_FIX_NEO_TABLES:-1}" = "1" ]; then
      echo "正在自动执行 migration/ensure-neo-mysql-tables.sh ..."
      bash migration/ensure-neo-mysql-tables.sh
    else
      echo "请手动执行: bash migration/ensure-neo-mysql-tables.sh"
    fi
  fi
else
  echo "跳过: stack-mysql 未运行"
fi

echo ""
echo "========== 7. 登录会话（MySQL sessions）=========="
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stack-mysql$'; then
  bash "$ROOT/migration/verify-login-sessions.sh" 2>/dev/null || echo "verify-login-sessions 失败"
else
  echo "跳过: stack-mysql 未运行"
fi

echo ""
echo "========== 8. .env 关键项 =========="
# 非敏感项照常显示：排障时要靠它们判断端口和外部地址是否配对。
grep -E '^(COMPOSE_PROJECT_NAME|GATEWAY_PUBLISH_PORT|PUBLIC_BASE_URL|MYSQL_HOST|MYSQL_DATABASE|MYSQL_USER)=' .env 2>/dev/null || true
# 密钥只报告"是否已配置"。本节曾直接 grep 出 MYSQL_PASSWORD=，而 deploy.sh 会把整个
# 验收输出 tee 进日志文件，等于每次部署都把明文密码写盘一次。
for _k in MYSQL_PASSWORD MYSQL_ROOT_PASSWORD NEO_INTERNAL_SECRET AUTH_SESSION_SECRET \
          BI_EXPORT_API_KEY DINGTALK_CLIENT_SECRET YIDA_SYSTEM_TOKEN YIDA_LIBRARY_PASSWORD; do
  if grep -qE "^${_k}=.+" .env 2>/dev/null; then
    echo "${_k}=<已配置>"
  else
    echo "${_k}=<未配置>"
  fi
done
unset _k
if grep -q 'PUBLIC_BASE_URL=HTTPS://' .env 2>/dev/null; then
  echo "警告: PUBLIC_BASE_URL 须为小写 https:// 不是 HTTPS://"
fi
if grep -q '^GATEWAY_HTTPS_PORT=' .env 2>/dev/null; then
  echo "提示: 已废弃 GATEWAY_HTTPS_PORT，请删除；仅保留 GATEWAY_PUBLISH_PORT=8000"
fi

echo ""
echo "浏览器请访问: https://<虚拟机IP>:${PORT}/login （须 https://，自签证书需点「继续访问」）"
