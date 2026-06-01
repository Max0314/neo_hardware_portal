#!/usr/bin/env bash
# 检查 sessions 表与用户账号状态（登录排障）
# 用法: cd 项目根 && bash migration/verify-login-sessions.sh
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

echo "========== MySQL sessions / users =========="
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stack-mysql$'; then
  echo "跳过: stack-mysql 未运行"
  exit 0
fi

docker exec stack-mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
SELECT COUNT(*) AS session_count FROM sessions;
SELECT user_id, LEFT(session_id,8) AS sid, FROM_UNIXTIME(last_access) AS last_seen
FROM sessions ORDER BY last_access DESC LIMIT 10;
SELECT id, username, status, LEFT(password,4) AS pwd_prefix, updated_time
FROM users WHERE username IN (\"zzw\",\"20461992\") OR id = 30
ORDER BY id;
SELECT status, COUNT(*) AS n FROM users GROUP BY status;
"'
echo ""
echo "说明: pwd_prefix 应为 \$2b\$（bcrypt）；status 须为 active；登录后 session_count 应增加。"
