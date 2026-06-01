#!/usr/bin/env bash
# 1) 将 MySQL 卷密码对齐 .env  2) 重置 zzw 管理员登录密码（不删业务数据）
# 用法: bash migration/fix-mysql-and-admin.sh '新登录密码至少12位'
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_MYSQL=0
NEW_ADMIN_PW=""
for arg in "$@"; do
  case "$arg" in
    --skip-mysql) SKIP_MYSQL=1 ;;
    -h|--help)
      echo "用法: bash migration/fix-mysql-and-admin.sh ['密码≥12位'] [--skip-mysql]"
      echo "  --skip-mysql  仅改 zzw 密码，不重置 MySQL 卷（推荐，离线/栈已停时用 emergency-recover.sh）"
      exit 0
      ;;
    *)
      if [ -z "$NEW_ADMIN_PW" ]; then NEW_ADMIN_PW="$arg"; fi
      ;;
  esac
done
if [ -z "$NEW_ADMIN_PW" ]; then
  echo "用法: bash migration/fix-mysql-and-admin.sh 'YourSecurePass123!'" >&2
  echo "说明: zzw 密码不再从 .env 的 SUPER_ADMIN_PASSWORD 读取，必须显式传入。" >&2
  exit 1
fi
if [ "${#NEW_ADMIN_PW}" -lt 12 ]; then
  echo "错误: 管理员新密码至少 12 位" >&2
  exit 1
fi

sed -i 's/\r$//' .env migration/reset-mysql-password.sh 2>/dev/null || true

# shellcheck source=lib-compose-core.sh
source "${ROOT}/migration/lib-compose-core.sh"

if [ "$SKIP_MYSQL" -eq 1 ]; then
  echo "========== 步骤 1/3: 跳过 MySQL 卷重置（--skip-mysql）=========="
  compose_up_core || { echo "核心服务启动失败" >&2; exit 1; }
else
  echo "========== 步骤 1/3: 对齐 MySQL 与 .env 密码 =========="
  if ! bash migration/reset-mysql-password.sh; then
    echo "MySQL 对齐失败，尝试仅拉起核心服务..." >&2
    compose_up_core || exit 1
    exit 1
  fi
fi

echo ""
echo "========== 步骤 2/3: 等待 htmlsystm 健康 =========="
for i in $(seq 1 30); do
  st="$(docker inspect stack-htmlsystm --format '{{.State.Health.Status}}' 2>/dev/null || echo none)"
  if [ "$st" = "healthy" ]; then
    break
  fi
  sleep 2
done

echo ""
echo "========== 步骤 3/3: 重置 zzw 登录密码 =========="
docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --reset zzw --password "$NEW_ADMIN_PW"
docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --clear-blocks || true
docker compose restart htmlsystm

echo ""
echo "完成。请使用 https://<IP>:8000/login"
echo "  用户名: zzw"
echo "  密码:   ${NEW_ADMIN_PW}"
