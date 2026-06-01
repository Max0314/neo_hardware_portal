#!/usr/bin/env bash
# 清除启动维护门（.startup_lock.json），恢复登录页可点击
# 用法: bash migration/clear-startup-lock.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi
PROJECT="${COMPOSE_PROJECT_NAME:-docker}"
VOL="${PROJECT}_htmlsystm_data"

if docker ps --format '{{.Names}}' | grep -q '^stack-htmlsystm$'; then
  docker exec stack-htmlsystm python -c "
from server.startup_gate import clear_lock_and_mark_ready, get_startup_status
clear_lock_and_mark_ready()
print(get_startup_status())
" 2>/dev/null && { echo "已通过 stack-htmlsystm 清除启动锁"; exit 0; }
fi

if docker volume inspect "$VOL" >/dev/null 2>&1; then
  docker run --rm -v "${VOL}:/app/data" alpine:3.20 \
    sh -c 'rm -f /app/data/.startup_lock.json && date +%s > /app/data/.startup_ready && ls -la /app/data/.startup* 2>/dev/null || true'
  echo "已从卷 ${VOL} 清除 .startup_lock.json"
else
  echo "未找到卷 ${VOL} 且 stack-htmlsystm 未运行" >&2
  exit 1
fi
