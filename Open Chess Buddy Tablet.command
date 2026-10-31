#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup_mac.sh first."
  read -r -p "Press Return to close. "
  exit 1
fi
if ! .venv/bin/python -c 'import qrcode' >/dev/null 2>&1; then
  echo "Install updated backend dependencies first: .venv/bin/python -m pip install -r requirements.txt"
  read -r -p "Press Return to close. "
  exit 1
fi
exec .venv/bin/python scripts/tablet_backend.py
