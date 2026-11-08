#!/bin/bash
# LaunchAgent entry point for the VBOT Qwen MCP bridge on the Mac Studio.
# Secrets live in ~/vbot-qwen-mcp/env (mode 0600), never in this file or the plist:
#   QWEN_API_KEY    Caddy gateway key (same value as ~/qwen-api-proxy/Caddyfile)
#   QWEN_MCP_TOKEN  bearer the robot sends to /mcp (a different secret)
set -euo pipefail
cd "$HOME/vbot-qwen-mcp"
# Read KEY=value lines literally (no shell expansion of the secret values).
while IFS='=' read -r k v; do
  [[ "$k" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$k=$v"
done < "$HOME/vbot-qwen-mcp/env"
# Same machine as Caddy, so skip the public Cloudflare hop for the upstream call.
export QWEN_BASE_URL="${QWEN_BASE_URL:-http://127.0.0.1:8001/v1}"
export MCP_HOST=127.0.0.1
export MCP_PORT="${MCP_PORT:-8010}"
exec /usr/bin/python3 -u server.py
