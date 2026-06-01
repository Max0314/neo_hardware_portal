#!/usr/bin/env bash
# .env 中改了 MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD 后，将 MySQL 数据卷内密码对齐（不删数据）
# 用法: cd 项目根 && bash migration/fix-mysql-env-password.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f .env ] && grep -q $'\r' .env 2>/dev/null; then
  sed -i 's/\r$//' .env
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi

# shellcheck source=lib-deploy-wait.sh
source "${ROOT}/migration/lib-deploy-wait.sh"
deploy_wait_init

echo "========== 1. 对齐 MySQL 卷密码与 .env =========="
bash "${ROOT}/migration/reset-mysql-password.sh"

echo ""
echo "========== 2. 重启依赖 MySQL 的服务 =========="
docker compose restart htmlsystm backend gateway

echo ""
echo "========== 3. 等待服务就绪 =========="
wait_container_healthy stack-mysql 45
wait_container_healthy stack-htmlsystm 90 || true
wait_container_healthy stack-neo-backend 90 || true
wait_container_healthy stack-gateway 30 || true

echo ""
echo "========== 4. 清除启动维护门 =========="
clear_startup_lock_all

echo ""
echo "========== 5. 验收 =========="
bash "${ROOT}/migration/check-db-config.sh" || true
echo ""
if wait_https_db_health 10; then
  echo "OK: /api/health?db=1 通过，可以登录 https://<IP>:${PORT}/login"
else
  echo "仍失败: 请执行 bash migration/check-stack.sh 并查看 docker logs stack-htmlsystm --tail 80"
  exit 1
fi
