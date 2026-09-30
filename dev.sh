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
  if [[ -n "${AUDIT_PID:-}" ]]; then
    kill "$AUDIT_PID" 2>/dev/null || true
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

./run_audit_studio.sh >/dev/null 2>&1 &
AUDIT_PID=$!
echo "⚡ LLM Audit Studio running at: http://localhost:3333"

npm run dev
