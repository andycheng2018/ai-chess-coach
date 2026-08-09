#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup_mac.sh first."
  exit 1
fi
exec ./.venv/bin/python server/app.py
