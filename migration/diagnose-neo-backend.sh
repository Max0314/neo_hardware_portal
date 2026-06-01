#!/usr/bin/env bash
# NEO backend 健康检查失败时诊断
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "========== 容器状态 =========="
docker compose ps backend 2>/dev/null || docker ps -a --filter name=stack-neo-backend

echo ""
echo "========== Health 详情 =========="
docker inspect stack-neo-backend --format '{{json .State.Health}}' 2>/dev/null | python3 -m json.tool 2>/dev/null || \
  docker inspect stack-neo-backend --format '{{.State.Health.Status}}' 2>/dev/null || echo "容器不存在"

echo ""
echo "========== 最近日志 =========="
docker logs stack-neo-backend --tail 60 2>&1 || true

echo ""
echo "========== 容器内探活 =========="
docker exec stack-neo-backend python -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=8)
    print('health/live:', r.status, r.read()[:200])
except Exception as e:
    print('FAILED:', e)
" 2>&1 || echo "exec 失败（容器可能未运行）"

echo ""
echo "若探活失败但进程在跑，可临时放宽后重启:"
echo "  docker compose restart backend"
echo "或查看 .env 中 MEMORY_VECTOR_BACKEND=none 是否已设置"
