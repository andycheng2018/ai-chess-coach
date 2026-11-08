#!/bin/bash
# Shows the cloud server's pairing QR in this terminal, for Studio or Chess Buddy on a tablet.
#   bash vbot-mcp/deploy/show_pairing_qr.sh
# The key is never written to a file. The screen and scrollback are cleared when you press Return.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
MAIN=$(git -C "$ROOT" worktree list --porcelain | sed -n '1s/^worktree //p')
MS=urbot@ssh-macstudio.urbot.ai
URL=https://chess-api.urbot.ai
[ -t 1 ] || { echo "Run this in a terminal window so the QR code can be shown."; exit 1; }

KEY=$(ssh -o "ProxyCommand=cloudflared access ssh --hostname %h" "$MS" "sed -nE 's/^CHESS_TABLET_TOKEN=//p' ~/chess-coach/.env")
[ -n "$KEY" ] || { echo "Could not read the pairing key from the server."; exit 1; }

clear_screen() { printf '\033[3J\033[2J\033[H'; }
trap clear_screen EXIT
clear_screen
# On stdin, so the key never appears in the process list.
printf '%s' "$KEY" | URL="$URL" "$MAIN/.venv/bin/python" -I -c '
import json, os, sys
import qrcode
code = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_L)
code.add_data(json.dumps({"type": "chessbuddy-tablet-v1", "url": os.environ["URL"], "token": sys.stdin.read().strip()}, separators=(",", ":")))
code.make(fit=True)
code.print_ascii(tty=True)
'
unset KEY
echo
echo "In the app, tap Scan pairing QR and point the camera here."
echo "Anyone who scans this can control the dog, so don't share or photograph it."
read -r -p "Press Return when done to clear the screen. " _
