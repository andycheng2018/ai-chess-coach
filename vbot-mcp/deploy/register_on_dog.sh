#!/bin/bash
# Run on the S100 as vbot. Registers the Qwen MCP bridge with the device agent
# (VBOT Lab V1.6.0 connection API), then waits for discovery to settle.
#   bash register_on_dog.sh <token-file>
# <token-file> holds QWEN_MCP_TOKEN (mode 0600). It is deleted after use.
set -euo pipefail
TOKEN_FILE=${1:?token file}
NAME=qwen-bridge
URL=https://vbot-mcp.urbot.ai/mcp
API=http://192.168.127.10:8787/api/admin/extensions/vbot-mcp/http
WD=/app/vbot-agent-harness
c() { curl --noproxy '*' -fsS --connect-timeout 3 --max-time 35 "$@"; }

c --get "$API/servers" --data-urlencode "workingDir=$WD" > /tmp/servers-before.json
jq -e '.canAddServers == true' /tmp/servers-before.json >/dev/null
if jq -e --arg n "$NAME" 'any(.servers[]; .name == $n)' /tmp/servers-before.json >/dev/null; then
  echo "$NAME already registered; not POSTing again."
else
  umask 077
  BODY=$(mktemp)
  trap 'rm -f "$BODY" "$TOKEN_FILE"' EXIT
  jq -n --arg name "$NAME" --arg url "$URL" --rawfile tok "$TOKEN_FILE" \
    '{name:$name,type:"http",url:$url,protocolVersion:"2025-06-18",
      headers:{Authorization:("Bearer " + ($tok|rtrimstr("\n")))}}' > "$BODY"
  c -X POST "$API/servers?workingDir=$WD" -H 'Content-Type: application/json' \
    --data-binary "@$BODY" | jq -c '{servers:[.servers[]|{name,enabled,toolCount}]}'
fi

for i in $(seq 1 30); do
  c --get "$API/servers" --data-urlencode "workingDir=$WD" > /tmp/servers-after.json
  jq -e '.refreshPending == false' /tmp/servers-after.json >/dev/null && break
  sleep 2
done
jq --arg n "$NAME" '{catalogReady,catalogRevision,refreshPending,diagnostics,loadError,
  servers:[.servers[] | select(.name == $n)]}' /tmp/servers-after.json
