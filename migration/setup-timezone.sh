#!/bin/bash
# 在部署服务器（Ubuntu/Debian 等）上执行一次：系统时区设为北京时间并开启 NTP 自动对时
set -e

TZ_NAME="${TZ:-Asia/Shanghai}"

if command -v timedatectl >/dev/null 2>&1; then
  echo "==> 设置时区为 ${TZ_NAME}"
  timedatectl set-timezone "${TZ_NAME}"
  echo "==> 启用 NTP 自动同步"
  timedatectl set-ntp true
  timedatectl status
elif [ -f /etc/alpine-release ]; then
  echo "==> Alpine: 安装 tzdata 并设置时区"
  apk add --no-cache tzdata
  ln -sf "/usr/share/zoneinfo/${TZ_NAME}" /etc/localtime
  echo "${TZ_NAME}" > /etc/timezone
  date
else
  echo "==> 使用传统方式设置时区"
  if [ -f "/usr/share/zoneinfo/${TZ_NAME}" ]; then
    ln -sf "/usr/share/zoneinfo/${TZ_NAME}" /etc/localtime
    echo "${TZ_NAME}" > /etc/timezone
  fi
  if command -v systemctl >/dev/null 2>&1; then
    for svc in systemd-timesyncd chrony ntp; do
      if systemctl list-unit-files "${svc}.service" 2>/dev/null | grep -q enabled; then
        systemctl enable --now "${svc}" 2>/dev/null || true
        break
      fi
    done
  fi
  date
fi

echo ""
echo "完成后请重建容器使 compose 中 TZ 生效："
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "  cd \"${ROOT_DIR}\" && docker compose up -d"
