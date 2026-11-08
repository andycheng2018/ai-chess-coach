#!/bin/bash
# Adds vbot-mcp.urbot.ai -> http://127.0.0.1:8010 to the Mac Studio tunnel, then restarts ONLY
# the cloudflared system service. Run on the Mac Studio: sudo bash ~/vbot-qwen-mcp/add_vbot_mcp_ingress.sh
# The bridge checks its own bearer token. Do not put a Cloudflare Access app on this hostname:
# the robot's agent runtime cannot do an Access browser login.
set -euo pipefail
CFG=/etc/cloudflared/config.yml
CF=/opt/homebrew/bin/cloudflared
TS=$(date +%Y%m%d-%H%M%S)
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
if grep -q "hostname: vbot-mcp.urbot.ai" "$CFG"; then
  echo "Rule already present; not editing."
else
  cp -p "$CFG" "$CFG.bak-$TS"; echo "Backup: $CFG.bak-$TS"
  trap "echo \"Failed; restoring backup.\"; cp -p \"$CFG.bak-$TS\" \"$CFG\"" ERR
  /usr/bin/python3 - "$CFG" <<"EOF"
import sys
p = sys.argv[1]; lines = open(p).read().splitlines(True)
idx = next(i for i, l in enumerate(lines) if l.strip() == "- service: http_status:404")
pad = lines[idx][:len(lines[idx]) - len(lines[idx].lstrip())]
lines[idx:idx] = [pad + "- hostname: vbot-mcp.urbot.ai\n", pad + "  service: http://127.0.0.1:8010\n"]
open(p, "w").writelines(lines)
EOF
fi
"$CF" tunnel --config "$CFG" ingress validate
"$CF" tunnel --config "$CFG" ingress rule https://vbot-mcp.urbot.ai/mcp
trap - ERR
# Proxied CNAME vbot-mcp.urbot.ai -> this tunnel, using the urbot account's origin cert.
# Prints a notice instead of failing if the record already exists.
sudo -u "${SUDO_USER:-urbot}" "$CF" tunnel route dns e17076b5-0ed9-4d17-b792-3901a002d347 vbot-mcp.urbot.ai || true
echo "Restarting the tunnel. Every urbot.ai hostname blinks for a few seconds, and this SSH session will drop."
sleep 2
launchctl kickstart -k system/com.cloudflare.cloudflared
