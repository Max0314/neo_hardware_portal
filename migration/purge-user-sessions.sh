#!/usr/bin/env bash
# 清理指定用户在 sessions 表中的全部会话（登录卡死/全站变慢后应急）
# 用法: bash migration/purge-user-sessions.sh 20461992
#       bash migration/purge-user-sessions.sh --all-stale   # 删除已过期会话
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  sed -i 's/\r$//' "$_self"
  exec bash "$_self" "$@"
fi
unset _self
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "用法: bash migration/purge-user-sessions.sh <用户名|user_id>"
  echo "      bash migration/purge-user-sessions.sh --all-stale"
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q '^stack-mysql$'; then
  echo "stack-mysql 未运行"
  exit 1
fi

if [[ "$TARGET" == "--all-stale" ]]; then
  docker exec stack-mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
DELETE FROM sessions WHERE expires_at < UNIX_TIMESTAMP();
SELECT ROW_COUNT() AS removed_expired;
"'
  echo "已删除过期会话"
  exit 0
fi

docker exec stack-mysql sh -c "mysql -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" \"\$MYSQL_DATABASE\" -e \"
SELECT id, username, status FROM users WHERE username = '${TARGET}' OR id = '${TARGET}' LIMIT 5;
DELETE s FROM sessions s
INNER JOIN users u ON s.user_id = u.id
WHERE u.username = '${TARGET}' OR u.id = '${TARGET}';
SELECT ROW_COUNT() AS sessions_removed;
\""
echo "完成。建议: docker compose restart htmlsystm"
