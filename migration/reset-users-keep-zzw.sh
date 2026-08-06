#!/usr/bin/env bash
# 清空 MySQL 用户数据，仅保留 zzw，便于重新手动钉钉同步
# 用法:
#   bash migration/reset-users-keep-zzw.sh --dry-run
#   bash migration/reset-users-keep-zzw.sh --confirm
#   bash migration/reset-users-keep-zzw.sh --confirm --password 'YourSecurePass123!'
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

DRY_RUN=0
CONFIRM=0
ADMIN_PW=""
ADMIN_USER="${SUPER_ADMIN_USERNAME:-zzw}"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --confirm) CONFIRM=1 ;;
    --password=*) ADMIN_PW="${arg#*=}" ;;
    -h|--help)
      echo "用法:"
      echo "  bash migration/reset-users-keep-zzw.sh --dry-run"
      echo "  bash migration/reset-users-keep-zzw.sh --confirm [--password '新密码≥12位']"
      exit 0
      ;;
    *)
      if [ -z "$ADMIN_PW" ] && [ "${#arg}" -ge 12 ]; then
        ADMIN_PW="$arg"
      fi
      ;;
  esac
done

if [ "$DRY_RUN" -eq 0 ] && [ "$CONFIRM" -eq 0 ]; then
  echo "请先预览: bash migration/reset-users-keep-zzw.sh --dry-run" >&2
  echo "确认执行: bash migration/reset-users-keep-zzw.sh --confirm" >&2
  exit 1
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
  ADMIN_USER="${SUPER_ADMIN_USERNAME:-zzw}"
fi

echo "========== 0/5 确保核心服务运行 + 清除启动锁 =========="
compose_up_minimal_login || compose_up_core || true
bash "${ROOT}/migration/clear-startup-lock.sh" || true

if ! docker ps --format '{{.Names}}' | grep -q '^stack-htmlsystm$'; then
  echo "错误: stack-htmlsystm 未运行，请先 bash migration/emergency-recover.sh --skip-password" >&2
  exit 1
fi

# shellcheck source=_common.sh
source "${ROOT}/migration/_common.sh"

echo ""
echo "========== 1/5 MySQL 连接检查 =========="
mysql_cli -e "SELECT COUNT(*) AS users FROM users" \
  || { echo "MySQL 连接失败，检查 .env 的 MYSQL_*" >&2; exit 1; }

echo ""
echo "========== 2/5 备份 users 表（可选）=========="
BACKUP_DIR="${ROOT}/migration/backups"
mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/users_before_reset_${TS}.sql"
mysql_dump_cli users sessions todos neo_point_events neo_user_point_balances \
  > "$BACKUP_FILE" 2>/dev/null || true
if [ -s "$BACKUP_FILE" ]; then
  echo "已备份到: $BACKUP_FILE"
else
  echo "警告: 备份未生成（可能 mysqldump 权限不足），继续..." >&2
  rm -f "$BACKUP_FILE"
fi

echo ""
echo "========== 3/5 执行用户清空（保留 ${ADMIN_USER}）=========="
if docker exec stack-htmlsystm test -f scripts/reset_users_keep_admin.py 2>/dev/null; then
  PY_ARGS=(scripts/reset_users_keep_admin.py --admin "$ADMIN_USER")
  if [ "$DRY_RUN" -eq 1 ]; then
    PY_ARGS+=(--dry-run)
  else
    PY_ARGS+=(--confirm)
  fi
  docker exec stack-htmlsystm python "${PY_ARGS[@]}"
else
  echo "容器内无 reset_users_keep_admin.py，使用 MySQL 直接执行（请先 rebuild 以使用 Python 版）"
  ADMIN_ESC="$(printf '%s' "$ADMIN_USER" | sed "s/'/''/g")"
  if [ "$DRY_RUN" -eq 1 ]; then
    mysql_cli -e "
SELECT COUNT(*) AS users_total FROM users;
SELECT COUNT(*) AS users_to_delete FROM users WHERE username != '${ADMIN_ESC}';
SELECT id, username, status FROM users WHERE username = '${ADMIN_ESC}';
"
  else
    mysql_cli -e "
SET FOREIGN_KEY_CHECKS=0;
DELETE FROM sessions;
DELETE FROM login_attempts;
DELETE FROM ip_blacklist;
DELETE FROM neo_point_events;
DELETE FROM neo_user_point_balances;
DELETE FROM neo_feature_uses;
DELETE FROM neo_bom_info_snapshots;
DELETE FROM todos;
DELETE FROM audit_logs;
DELETE FROM material_db_audit;
DELETE FROM users WHERE username != '${ADMIN_ESC}';
UPDATE users SET status='active', roles='admin,management,super_admin',
  dingtalk_data=NULL, dingtalk_userid=NULL, dingtalk_unionid=NULL,
  job_number=NULL, user_source='local', updated_time=NOW()
WHERE username='${ADMIN_ESC}';
SET FOREIGN_KEY_CHECKS=1;
SELECT COUNT(*) AS users_remaining FROM users;
"
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "dry-run 完成，未修改数据。"
  exit 0
fi

echo ""
echo "========== 4/5 清理登录限制 / 可选重置 zzw 密码 =========="
docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --clear-blocks || true
if [ -n "$ADMIN_PW" ]; then
  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py \
    --reset "$ADMIN_USER" --password "$ADMIN_PW"
fi

echo ""
echo "========== 5/5 重启服务 =========="
docker compose restart htmlsystm backend 2>/dev/null || docker compose restart htmlsystm
sleep 5
docker compose "${COMPOSE_EMERGENCY[@]}" up -d gateway 2>/dev/null || \
  docker compose up -d gateway --no-deps 2>/dev/null || true

echo ""
echo "当前 users 表:"
mysql_cli -e '
SELECT id, username, status, user_source,
       CASE WHEN dingtalk_data IS NULL THEN 0 ELSE CHAR_LENGTH(dingtalk_data) END AS dingtalk_chars
FROM users ORDER BY id;
'

echo ""
echo "完成。请登录 zzw 后在管理界面手动「同步钉钉用户」。"
echo "NEO 积分/看板 MySQL 表已清空；若仍用 SQLite 看板库，可删卷内 dashboard_metrics.db 后 restart backend。"
