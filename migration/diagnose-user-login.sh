#!/usr/bin/env bash
# 诊断单个用户登录是否可能拖垮全站（sessions 堆积、dingtalk_data 过大）
# 用法: bash migration/diagnose-user-login.sh 20461992
_self="${BASH_SOURCE[0]}"
if [ -f "$_self" ] && grep -q $'\r' "$_self" 2>/dev/null; then
  sed -i 's/\r$//' "$_self"
  exec bash "$_self" "$@"
fi
unset _self
set -euo pipefail

USERNAME="${1:-20461992}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "========== 用户 $USERNAME =========="
if docker ps --format '{{.Names}}' | grep -q '^stack-mysql$'; then
  docker exec stack-mysql sh -c "mysql -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" \"\$MYSQL_DATABASE\" -e \"
SELECT id, username, status, LEFT(password,4) AS pwd_prefix,
       CHAR_LENGTH(COALESCE(dingtalk_data,'')) AS dingtalk_chars,
       updated_time
FROM users WHERE username = '${USERNAME}' LIMIT 1;
SELECT COUNT(*) AS session_rows, MAX(FROM_UNIXTIME(last_access)) AS last_sess
FROM sessions s JOIN users u ON s.user_id = u.id WHERE u.username = '${USERNAME}';
\""
else
  echo "stack-mysql 未运行"
fi

echo ""
echo "判断: session_rows 若 >500 登录时会触发大量 DELETE，请先:"
echo "  bash migration/purge-user-sessions.sh ${USERNAME}"
echo "dingtalk_chars 若 >262144(256KB) 可能撑爆 worker，需检查钉钉同步数据。"
