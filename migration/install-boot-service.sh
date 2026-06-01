#!/usr/bin/env bash
# 安装 systemd 开机自启：在 Docker 与（可选）共享目录就绪后执行 docker compose up -d
# 用法（在项目根目录）：
#   sed -i 's/\r$//' migration/install-boot-service.sh migration/boot-stack.sh
#   sudo bash migration/install-boot-service.sh
# 非交互（推荐）：
#   COMPOSE_USER=zzw sudo bash migration/install-boot-service.sh
# 同时安装健康巡检 timer（每 3 分钟 + 每日 sessions 清理）：
#   INSTALL_WATCH=1 COMPOSE_USER=zzw sudo bash migration/install-boot-service.sh
set -euo pipefail

MIGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${MIGRATION_DIR}/.." && pwd)"
TEMPLATE="${MIGRATION_DIR}/systemd/docker-stack.service"
BOOT_SCRIPT_SRC="${MIGRATION_DIR}/boot-stack.sh"
BOOT_SCRIPT_DST="/usr/local/lib/docker-stack/boot-stack.sh"
UNIT_DST="/etc/systemd/system/docker-stack.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 执行: sudo bash migration/install-boot-service.sh" >&2
  exit 1
fi

if [[ ! -f "${TEMPLATE}" ]] || [[ ! -f "${BOOT_SCRIPT_SRC}" ]]; then
  echo "缺少模板或 boot-stack.sh" >&2
  exit 1
fi

sed -i 's/\r$//' "${TEMPLATE}" "${BOOT_SCRIPT_SRC}" 2>/dev/null || true

# ---------- 运行用户 ----------
COMPOSE_USER="${COMPOSE_USER:-${SUDO_USER:-}}"
if [[ -z "${COMPOSE_USER}" || "${COMPOSE_USER}" == "root" ]]; then
  if id zzw &>/dev/null; then
    COMPOSE_USER=zzw
    echo "使用默认用户: zzw"
  elif [[ -t 0 ]]; then
    read -r -p "运行 docker compose 的 Linux 用户名（非 root，须在 docker 组）: " COMPOSE_USER
  else
    echo "请设置环境变量 COMPOSE_USER=你的用户名 后重试" >&2
    exit 1
  fi
fi
if ! id "${COMPOSE_USER}" &>/dev/null; then
  echo "用户不存在: ${COMPOSE_USER}" >&2
  exit 1
fi
if ! groups "${COMPOSE_USER}" | grep -q '\bdocker\b'; then
  echo "警告: ${COMPOSE_USER} 不在 docker 组，服务启动可能失败。" >&2
  echo "  执行: usermod -aG docker ${COMPOSE_USER}  后重新登录" >&2
fi

COMPOSE_HOME="$(getent passwd "${COMPOSE_USER}" | cut -d: -f6)"

# ---------- 项目目录 ----------
WR_DIR="${STACK_DIR:-${ROOT}}"
# 已设置 COMPOSE_USER 或 STACK_DIR 时视为非交互，不再询问路径
if [[ -t 0 && -z "${STACK_DIR:-}" && -z "${COMPOSE_USER:-}" ]]; then
  echo "项目目录: ${ROOT}"
  read -r -p "确认 STACK_DIR [${ROOT}]: " _input
  WR_DIR="${_input:-${ROOT}}"
else
  echo "项目目录: ${WR_DIR}"
fi
WR_DIR="$(cd "${WR_DIR}" && pwd)"

MOUNT_POINT=""
MOUNT_UNIT=""
if [[ "${WR_DIR}" == /media/* ]]; then
  # /media/sf_awei/docker版本 → /media/sf_awei（勿用 cut -f1-3，会得到 //media/...）
  MOUNT_POINT="/media/$(echo "${WR_DIR}" | cut -d/ -f3)"
  MOUNT_UNIT="$(systemd-escape --path "${MOUNT_POINT}" 2>/dev/null || true).mount"
  echo "共享/可移动目录: ${MOUNT_POINT} → systemd 单元 ${MOUNT_UNIT}"
fi

DO_ENABLE="${DO_ENABLE:-Y}"
if [[ -t 0 && -z "${DO_ENABLE:-}" ]]; then
  read -r -p "启用并立即测试启动? [Y/n]: " _en
  DO_ENABLE="${_en:-Y}"
fi

# ---------- 安装 boot-stack.sh 到本地盘（不依赖共享目录已挂载）----------
install -d -m 0755 /usr/local/lib/docker-stack
install -m 0755 "${BOOT_SCRIPT_SRC}" "${BOOT_SCRIPT_DST}"
echo "已安装: ${BOOT_SCRIPT_DST}"

STARTUP_SCRIPT_SRC="${MIGRATION_DIR}/stack-startup.sh"
PROGRESS_LIB_SRC="${MIGRATION_DIR}/lib-progress.sh"
WATCH_SCRIPT_SRC="${MIGRATION_DIR}/watch-stack-health.sh"
MAINT_SCRIPT_SRC="${MIGRATION_DIR}/stack-maintenance.sh"
if [[ -f "${PROGRESS_LIB_SRC}" ]]; then
  install -m 0644 "${PROGRESS_LIB_SRC}" /usr/local/lib/docker-stack/lib-progress.sh
fi
if [[ -f "${STARTUP_SCRIPT_SRC}" ]]; then
  install -m 0755 "${STARTUP_SCRIPT_SRC}" /usr/local/lib/docker-stack/stack-startup.sh
fi
if [[ -f "${WATCH_SCRIPT_SRC}" ]]; then
  install -m 0755 "${WATCH_SCRIPT_SRC}" /usr/local/lib/docker-stack/watch-stack-health.sh
fi
if [[ -f "${MAINT_SCRIPT_SRC}" ]]; then
  install -m 0755 "${MAINT_SCRIPT_SRC}" /usr/local/lib/docker-stack/stack-maintenance.sh
fi
COLLECT_SCRIPT_SRC="${MIGRATION_DIR}/collect-stack-logs.sh"
LOG_COLLECTOR_SRC="${MIGRATION_DIR}/start-log-collector.sh"
if [[ -f "${COLLECT_SCRIPT_SRC}" ]]; then
  install -m 0755 "${COLLECT_SCRIPT_SRC}" /usr/local/lib/docker-stack/collect-stack-logs.sh
fi
if [[ -f "${LOG_COLLECTOR_SRC}" ]]; then
  install -m 0755 "${LOG_COLLECTOR_SRC}" /usr/local/lib/docker-stack/start-log-collector.sh
fi
install -d -m 0755 /var/lib/docker-stack 2>/dev/null || true

# ---------- 生成 systemd 单元 ----------
TMP="$(mktemp)"
sed \
  -e "s|^User=.*|User=${COMPOSE_USER}|" \
  -e "s|^Group=.*|Group=docker|" \
  -e "s|^Environment=HOME=.*|Environment=HOME=${COMPOSE_HOME}|" \
  -e "s|^Environment=STACK_DIR=.*|Environment=STACK_DIR=${WR_DIR}|" \
  -e "s|^Environment=MOUNT_POINT=.*|Environment=MOUNT_POINT=${MOUNT_POINT:-/media/sf_awei}|" \
  -e "s|file://.*运维手册.md|file://${WR_DIR}/运维手册.md|" \
  "${TEMPLATE}" > "${TMP}"

if [[ -n "${MOUNT_UNIT}" ]]; then
  # 去掉模板里注释的重复 After/Requires，只保留一组
  sed -i '/^# After=media-sf_awei.mount/d' "${TMP}"
  sed -i '/^# Requires=media-sf_awei.mount/d' "${TMP}"
  sed -i "s|^After=docker.service network-online.target local-fs.target|After=docker.service network-online.target local-fs.target ${MOUNT_UNIT} vboxadd-service.service|" "${TMP}"
  if ! grep -q "^Wants=${MOUNT_UNIT}" "${TMP}"; then
    sed -i "/^Wants=docker.service network-online.target/a Wants=${MOUNT_UNIT} vboxadd-service.service" "${TMP}"
  fi
  # 若 MOUNT_POINT 与模板默认不同，更新 Environment
  sed -i "s|^Environment=MOUNT_POINT=.*|Environment=MOUNT_POINT=${MOUNT_POINT}|" "${TMP}"
fi

install -m 0644 "${TMP}" "${UNIT_DST}"
rm -f "${TMP}"

systemctl daemon-reload
systemctl reset-failed docker-stack.service 2>/dev/null || true

if [[ "${DO_ENABLE}" =~ ^[Yy]$ ]]; then
  systemctl enable docker-stack.service
  echo ""
  echo "正在执行 systemctl restart docker-stack.service ..."
  systemctl restart docker-stack.service || true
  sleep 3
  systemctl status docker-stack.service --no-pager || true
  echo ""
  echo "容器状态:"
  sudo -u "${COMPOSE_USER}" -H bash -c "cd '${WR_DIR}' && docker compose ps" 2>/dev/null || true
fi

echo ""
echo "已安装:"
echo "  单元: ${UNIT_DST}"
echo "  脚本: ${BOOT_SCRIPT_DST}"
echo "  STACK_DIR=${WR_DIR}"
echo ""
echo "  手动: systemctl restart docker-stack.service"
echo "  日志: journalctl -u docker-stack.service -b --no-pager"
echo "  跟踪: journalctl -u docker-stack.service -f"

if [[ "${INSTALL_WATCH:-0}" == "1" ]]; then
  for pair in \
    "docker-stack-watch.service:docker-stack-watch.service" \
    "docker-stack-watch.timer:docker-stack-watch.timer" \
    "docker-stack-maintenance.service:docker-stack-maintenance.service" \
    "docker-stack-maintenance.timer:docker-stack-maintenance.timer"; do
    src_name="${pair%%:*}"
    dst_name="${pair##*:}"
    src_file="${MIGRATION_DIR}/systemd/${src_name}"
    if [[ ! -f "${src_file}" ]]; then
      echo "缺少 ${src_file}" >&2
      continue
    fi
    sed -i 's/\r$//' "${src_file}" 2>/dev/null || true
    tmp_watch="$(mktemp)"
    sed \
      -e "s|^User=.*|User=${COMPOSE_USER}|" \
      -e "s|^Group=.*|Group=docker|" \
      -e "s|^Environment=HOME=.*|Environment=HOME=${COMPOSE_HOME}|" \
      -e "s|^Environment=STACK_DIR=.*|Environment=STACK_DIR=${WR_DIR}|" \
      "${src_file}" > "${tmp_watch}"
    install -m 0644 "${tmp_watch}" "/etc/systemd/system/${dst_name}"
    rm -f "${tmp_watch}"
  done
  systemctl daemon-reload
  systemctl enable docker-stack-watch.timer docker-stack-maintenance.timer
  systemctl start docker-stack-watch.timer docker-stack-maintenance.timer
  echo ""
  echo "已安装健康巡检:"
  echo "  systemctl status docker-stack-watch.timer"
  echo "  systemctl status docker-stack-maintenance.timer"
  echo "  日志: tail -f /var/log/docker-stack-watch.log"
fi

if [[ "${INSTALL_LOG_COLLECTOR:-0}" == "1" || "${INSTALL_WATCH:-0}" == "1" ]]; then
  for pair in \
    "docker-stack-log-collector.service:docker-stack-log-collector.service" \
    "docker-stack-log-collector.timer:docker-stack-log-collector.timer"; do
    src_name="${pair%%:*}"
    dst_name="${pair##*:}"
    src_file="${MIGRATION_DIR}/systemd/${src_name}"
    if [[ ! -f "${src_file}" ]]; then
      echo "缺少 ${src_file}" >&2
      continue
    fi
    sed -i 's/\r$//' "${src_file}" 2>/dev/null || true
    tmp_log="$(mktemp)"
    sed \
      -e "s|^User=.*|User=${COMPOSE_USER}|" \
      -e "s|^Group=.*|Group=docker|" \
      -e "s|^Environment=HOME=.*|Environment=HOME=${COMPOSE_HOME}|" \
      -e "s|^Environment=STACK_DIR=.*|Environment=STACK_DIR=${WR_DIR}|" \
      -e "s|^Environment=STACK_LOG_DIR=.*|Environment=STACK_LOG_DIR=${WR_DIR}/log|" \
      "${src_file}" > "${tmp_log}"
    install -m 0644 "${tmp_log}" "/etc/systemd/system/${dst_name}"
    rm -f "${tmp_log}"
  done
  systemctl daemon-reload
  systemctl enable docker-stack-log-collector.timer
  systemctl start docker-stack-log-collector.timer
  mkdir -p "${WR_DIR}/log" 2>/dev/null || true
  echo ""
  echo "已安装每分钟日志采集:"
  echo "  目录: ${WR_DIR}/log/YYYY-MM-DD/"
  echo "  systemctl status docker-stack-log-collector.timer"
  echo "  或手动: bash migration/start-log-collector.sh --daemon"
fi
