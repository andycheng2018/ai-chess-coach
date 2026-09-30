#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT=3333
echo "== Launching Chess Coach LLM Audit Studio on http://localhost:$PORT =="
python3 -m http.server "$PORT" --directory audit-dashboard
