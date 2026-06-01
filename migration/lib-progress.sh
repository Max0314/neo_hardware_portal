#!/usr/bin/env bash
# 命令行进度条（被 stack-startup.sh source）
# shellcheck shell=bash

PROGRESS_WIDTH="${PROGRESS_WIDTH:-48}"

progress_draw() {
  local current="${1:-0}"
  local total="${2:-100}"
  local message="${3:-}"
  if [[ "$total" -lt 1 ]]; then
    total=1
  fi
  if [[ "$current" -gt "$total" ]]; then
    current=$total
  fi
  local pct=$((current * 100 / total))
  local filled=$((current * PROGRESS_WIDTH / total))
  local empty=$((PROGRESS_WIDTH - filled))
  local bar_f bar_e
  bar_f="$(printf '%*s' "$filled" '' | tr ' ' '█')"
  bar_e="$(printf '%*s' "$empty" '' | tr ' ' '░')"
  printf '\r\033[K[%s%s] %3d%% %s' "$bar_f" "$bar_e" "$pct" "$message"
}

progress_finish() {
  local message="${1:-完成}"
  printf '\n%s\n' "$message"
}

progress_log() {
  printf '\n[stack-startup] %s\n' "$*"
}
