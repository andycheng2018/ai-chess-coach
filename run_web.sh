#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d node_modules ]]; then
  echo "Run ./setup_mac.sh first."
  exit 1
fi
exec npm run dev
