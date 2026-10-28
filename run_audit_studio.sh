#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

AUDIT_STUDIO_URL="${AUDIT_STUDIO_URL:-http://127.0.0.1:${PORT:-${CHESS_SERVER_PORT:-8765}}/audit}"
echo "== Opening Chess Coach Audit Studio at $AUDIT_STUDIO_URL (start the backend first) =="
exec ./.venv/bin/python -m webbrowser "$AUDIT_STUDIO_URL"
