#!/usr/bin/env bash
# 重复测试：登录 → 校验 → 退出 → 再校验
# VirtualBox 共享目录 /media/sf_* 下文件带 CRLF，必须在第 2 行就 re-exec，不能先 cd。
if [[ -z "${MIGRATION_REEXEC_DONE:-}" && "${PWD:-}" == /media/sf_* ]]; then
  export MIGRATION_REEXEC_DONE=1 MIGRATION_ROOT="${MIGRATION_ROOT:-$PWD}"
  exec bash <(sed 's/\r$//' "${BASH_SOURCE[0]}") "$@"
fi
set -euo pipefail

ROOT="${MIGRATION_ROOT:-$(pwd)}"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi

USE_CONTAINER=0
PY_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --in-container)
      USE_CONTAINER=1
      shift
      ;;
    *)
      PY_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${AUTH_TEST_PASSWORD:-}" && -z "${AUTH_TEST_PASS:-}" ]]; then
  if [[ " ${PY_ARGS[*]} " != *" --password "* ]]; then
    echo "错误: 请 export AUTH_TEST_PASSWORD='...' 或传入 --password" >&2
    exit 2
  fi
fi

echo "========== 前置检查 =========="
if ! curl -sk --connect-timeout 5 "https://127.0.0.1:${GATEWAY_PUBLISH_PORT:-8000}/api/health" | grep -q '"ok"'; then
  echo "警告: 网关 /api/health 未就绪，测试可能超时"
fi

host_python_ok=0
if command -v python3 >/dev/null 2>&1; then
  if python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 6) else 1)' 2>/dev/null; then
    host_python_ok=1
  else
    echo "宿主机 Python 版本低于 3.6"
  fi
fi

if [[ "$USE_CONTAINER" -eq 0 && "$host_python_ok" -eq 0 ]]; then
  USE_CONTAINER=1
  echo "改用 stack-htmlsystm 容器内 Python"
fi

_copy_py_to_container() {
  local tmp
  tmp="$(mktemp /tmp/auth-test.XXXXXX.py)"
  sed 's/\r$//' "$ROOT/migration/test-auth-logout-loop.py" >"$tmp"
  docker cp "$tmp" stack-htmlsystm:/tmp/test-auth-logout-loop.py
  rm -f "$tmp"
}

if [[ "$USE_CONTAINER" -eq 1 ]]; then
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'stack-htmlsystm'; then
    echo "错误: stack-htmlsystm 未运行" >&2
    exit 1
  fi
  echo "模式: 容器内直连 http://127.0.0.1:8000"
  _copy_py_to_container
  docker exec \
    -e AUTH_TEST_USER="${AUTH_TEST_USER:-}" \
    -e AUTH_TEST_PASSWORD="${AUTH_TEST_PASSWORD:-${AUTH_TEST_PASS:-}}" \
    stack-htmlsystm \
    python3 /tmp/test-auth-logout-loop.py \
      --base "http://127.0.0.1:8000" \
      --insecure \
      "${PY_ARGS[@]}"
else
  echo "模式: 本机经网关 https://127.0.0.1:${GATEWAY_PUBLISH_PORT:-8000}"
  python3 "$ROOT/migration/test-auth-logout-loop.py" "${PY_ARGS[@]}"
fi
