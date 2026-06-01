#!/usr/bin/env bash
# 将 MySQL 卷内 root / htmlsystm_user 密码重置为当前 .env 中的值（不删数据卷）
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "错误: 未找到 $ROOT/.env" >&2
  exit 1
fi

if grep -q $'\r' .env 2>/dev/null; then
  echo "==> 修复 .env 的 Windows 换行 (CRLF -> LF)..."
  sed -i 's/\r$//' .env
fi

# shellcheck disable=SC1091
set -a
. ./.env
set +a

for v in MYSQL_ROOT_PASSWORD MYSQL_PASSWORD MYSQL_USER MYSQL_DATABASE; do
  eval "val=\${$v:-}"
  if [ -z "$val" ]; then
    echo "错误: .env 中 ${v} 为空" >&2
    exit 1
  fi
done

if printf '%s' "$MYSQL_ROOT_PASSWORD" | LC_ALL=C grep -q '[^ -~]'; then
  echo "错误: MYSQL_ROOT_PASSWORD 须为 ASCII（勿用中文）" >&2
  exit 1
fi
if printf '%s' "$MYSQL_PASSWORD" | LC_ALL=C grep -q '[^ -~]'; then
  echo "错误: MYSQL_PASSWORD 须为 ASCII" >&2
  exit 1
fi

escape_sql() {
  printf '%s' "$1" | sed "s/'/''/g"
}

ROOT_PW_SQL="$(escape_sql "$MYSQL_ROOT_PASSWORD")"
APP_PW_SQL="$(escape_sql "$MYSQL_PASSWORD")"
DB_SQL="$(escape_sql "$MYSQL_DATABASE")"
USER_SQL="$(escape_sql "$MYSQL_USER")"

PROJECT="${COMPOSE_PROJECT_NAME:-docker}"
VOL="${PROJECT}_mysql_data"
RESET_CTN="stack-mysql-password-reset"

if ! docker volume inspect "$VOL" >/dev/null 2>&1; then
  echo "错误: 卷 ${VOL} 不存在" >&2
  exit 1
fi

# shellcheck source=lib-compose-core.sh
source "$(dirname "$0")/lib-compose-core.sh"

restore_stack() {
  docker rm -f "$RESET_CTN" 2>/dev/null || true
  echo "==> 恢复核心服务（不含 autoheal）..."
  compose_up_core
}

echo "==> 项目: ${PROJECT}  数据卷: ${VOL}"
echo "==> 同步 MySQL 密码为 .env 中的值（不删除数据）..."
docker compose stop gateway web backend htmlsystm 2>/dev/null || true
docker compose stop mysql 2>/dev/null || true
docker rm -f "$RESET_CTN" 2>/dev/null || true

docker run -d --name "$RESET_CTN" \
  -v "${VOL}:/var/lib/mysql" \
  mysql:8.0 \
  mysqld --skip-grant-tables --character-set-server=utf8mb4

# skip-grant-tables 时 MySQL 可能 port:0，仅用 socket；失败时也要恢复栈
trap restore_stack EXIT

echo "==> 等待临时 MySQL 就绪（socket，RK3568 可能较慢）..."
i=1
while [ "$i" -le 90 ]; do
  if docker exec "$RESET_CTN" mysql -uroot -e "SELECT 1" >/dev/null 2>&1; then
    echo "==> 临时 MySQL 已就绪"
    break
  fi
  sleep 2
  if [ "$i" -eq 90 ]; then
    echo "错误: 临时 MySQL 未就绪（90 次重试）" >&2
    docker logs "$RESET_CTN" --tail 30 >&2
    exit 1
  fi
  i=$((i + 1))
done

docker exec -i "$RESET_CTN" mysql -uroot <<EOSQL
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED BY '${ROOT_PW_SQL}';
ALTER USER 'root'@'%' IDENTIFIED BY '${ROOT_PW_SQL}';
CREATE USER IF NOT EXISTS '${USER_SQL}'@'localhost' IDENTIFIED BY '${APP_PW_SQL}';
CREATE USER IF NOT EXISTS '${USER_SQL}'@'%' IDENTIFIED BY '${APP_PW_SQL}';
ALTER USER '${USER_SQL}'@'localhost' IDENTIFIED BY '${APP_PW_SQL}';
ALTER USER '${USER_SQL}'@'%' IDENTIFIED BY '${APP_PW_SQL}';
GRANT ALL PRIVILEGES ON \`${DB_SQL}\`.* TO '${USER_SQL}'@'localhost';
GRANT ALL PRIVILEGES ON \`${DB_SQL}\`.* TO '${USER_SQL}'@'%';
FLUSH PRIVILEGES;
EOSQL

docker rm -f "$RESET_CTN"
trap - EXIT

compose_up_core
echo "==> 等待 stack-mysql 健康..."
sleep 8
for i in $(seq 1 30); do
  st="$(docker inspect stack-mysql --format '{{.State.Health.Status}}' 2>/dev/null || echo none)"
  if [ "$st" = "healthy" ]; then
    break
  fi
  sleep 2
done

docker exec stack-mysql mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -e "SELECT 1 AS ok;" >/dev/null
echo "完成。root 与 ${MYSQL_USER} 密码已与 .env 一致。"
