#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python || ! -d node_modules ]]; then
  echo "Run ./setup_mac.sh first."
  exit 1
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

./.venv/bin/python server/app.py &
BACKEND_PID=$!
sleep 0.6

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "Backend exited during startup."
  wait "$BACKEND_PID" || true
  exit 1
fi

npm run dev
