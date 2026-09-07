#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="/tmp/grove-dialogue-workbench.pid"

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(tr -cd '0-9' < "$PID_FILE")"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "实验工作台已在运行（PID $EXISTING_PID）" >&2
    exit 1
  fi
fi

cd "$REPO_DIR/frontend"
npm run build

cd "$REPO_DIR/backend"
exec .venv/bin/python -m evals.dialogue_workbench --pid-file "$PID_FILE" "$@"
