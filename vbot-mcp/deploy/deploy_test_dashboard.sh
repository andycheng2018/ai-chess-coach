#!/bin/bash
# Puts the Test Dashboard's server checks on the Mac Studio. Run from this MacBook:
#   bash vbot-mcp/deploy/deploy_test_dashboard.sh
# Backs up the files it changes, gives the backend the MCP token, and rebuilds only
# the chess container. Refuses to run while robot reactions are on.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
MS=urbot@ssh-macstudio.urbot.ai
PX='ProxyCommand=cloudflared access ssh --hostname %h'

# shellcheck disable=SC2029
ssh -o "$PX" "$MS" 'bash -s' <<'EOF'
set -euo pipefail
cd ~/chess-coach
H=$(mktemp); chmod 600 "$H"; trap 'rm -f "$H"' EXIT
printf 'X-Chess-Buddy-Token: %s\nOrigin: http://localhost:5173\n' "$(sed -nE 's/^CHESS_TABLET_TOKEN=//p' .env)" > "$H"
curl -fsS -m 15 -H @"$H" http://127.0.0.1:8765/api/vbot/status |
  python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit("Turn robot reactions off first." if d["armed"] or d["busy"] else 0)'
TS=$(date +%Y%m%d-%H%M%S)
cp -p .env ".env.bak-$TS"
cp -p ai-chess-coach/server/app.py "ai-chess-coach/server/app.py.bak-$TS"
[ ! -f ai-chess-coach/server/diagnostics.py ] || cp -p ai-chess-coach/server/diagnostics.py "ai-chess-coach/server/diagnostics.py.bak-$TS"
cp -p ai-chess-coach/server/coach/qwen_adapter.py "ai-chess-coach/server/coach/qwen_adapter.py.bak-$TS"
echo "Backups: ~/chess-coach/.env.bak-$TS, server/app.py.bak-$TS and server/coach/qwen_adapter.py.bak-$TS"
EOF

scp -q -o "$PX" "$ROOT/server/app.py" "$ROOT/server/diagnostics.py" "$ROOT/server/vbot_speech.py" "$ROOT/server/vbot_voice.py" "$MS:chess-coach/ai-chess-coach/server/"
scp -q -o "$PX" "$ROOT/server/coach/qwen_adapter.py" "$MS:chess-coach/ai-chess-coach/server/coach/"

ssh -o "$PX" "$MS" 'bash -s' <<'EOF'
set -euo pipefail
cd ~/chess-coach
PATH=/usr/local/bin:$PATH
if ! grep -q '^QWEN_MCP_TOKEN=' .env; then
  { echo '# Bearer for the VBOT Qwen MCP bridge. Same value as ~/vbot-qwen-mcp/env.'; grep '^QWEN_MCP_TOKEN=' ~/vbot-qwen-mcp/env; } >> .env
fi
docker compose up -d --build 2>&1 | tail -3
sleep 5
docker ps --filter name=chess-coach-backend-1 --format '{{.Names}}: {{.Status}}'
EOF
# Links VBOT Studio on this Mac to the cloud server. The key stays in .env (git-ignored).
MAIN=$(git -C "$ROOT" worktree list --porcelain | sed -n '1s/^worktree //p')
if ! grep -q '^CHESS_CLOUD_TOKEN=' "$MAIN/.env"; then
  cp -p "$MAIN/.env" "$MAIN/.env.bak-$(date +%Y%m%d-%H%M%S)"
  KEY=$(ssh -o "$PX" "$MS" "sed -nE 's/^CHESS_TABLET_TOKEN=//p' ~/chess-coach/.env")
  [ -n "$KEY" ] && printf '\nCHESS_CLOUD_URL=https://chess-api.urbot.ai\nCHESS_CLOUD_TOKEN=%s\n' "$KEY" >> "$MAIN/.env"
  unset KEY
fi
echo "Done. Open the app, then Menu > Test Dashboard > Run all tests."
