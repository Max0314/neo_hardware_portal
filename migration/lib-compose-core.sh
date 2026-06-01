#!/usr/bin/env bash
# 核心栈服务（不含 autoheal，避免离线环境拉取 Docker Hub 失败导致整栈起不来）
STACK_CORE_SERVICES=(mysql htmlsystm backend web gateway)
COMPOSE_FILES=(-f docker-compose.yml)
COMPOSE_EMERGENCY=(-f docker-compose.yml -f docker-compose.emergency.yml)

compose_up_core() {
  docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans "${STACK_CORE_SERVICES[@]}" "$@"
}

# 最小可登录：mysql + htmlsystm + gateway（不等待 NEO healthy）
compose_up_minimal_login() {
  docker compose "${COMPOSE_FILES[@]}" up -d mysql htmlsystm "$@"
  local i
  for i in $(seq 1 60); do
    local hm hi
    hm="$(docker inspect stack-mysql --format '{{.State.Health.Status}}' 2>/dev/null || echo none)"
    hi="$(docker inspect stack-htmlsystm --format '{{.State.Health.Status}}' 2>/dev/null || echo none)"
    if [ "$hm" = "healthy" ] && [ "$hi" = "healthy" ]; then
      break
    fi
    sleep 2
  done
  docker compose "${COMPOSE_EMERGENCY[@]}" up -d gateway
}

compose_up_neo_optional() {
  docker compose "${COMPOSE_FILES[@]}" up -d backend web "$@" || true
}

compose_start_core() {
  docker compose "${COMPOSE_FILES[@]}" start "${STACK_CORE_SERVICES[@]}" 2>/dev/null || compose_up_core
}
