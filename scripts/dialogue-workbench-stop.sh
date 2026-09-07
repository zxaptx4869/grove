#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/grove-dialogue-workbench.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "实验工作台当前未运行。"
  exit 0
fi

WORKBENCH_PID="$(tr -cd '0-9' < "$PID_FILE")"
if [[ -z "$WORKBENCH_PID" ]]; then
  echo "PID 文件无效，未停止任何进程。" >&2
  exit 1
fi
if kill -0 "$WORKBENCH_PID" 2>/dev/null; then
  kill "$WORKBENCH_PID"
  echo "已停止实验工作台（PID ${WORKBENCH_PID}）。"
else
  echo "实验工作台当前未运行。"
fi
rm -f "$PID_FILE"
