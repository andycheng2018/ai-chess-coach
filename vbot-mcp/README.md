# VBOT agent ↔ Qwen MCP bridge

Gives the S100's built-in agent a `qwen_ask` tool backed by Qwen 27B on the Mac Studio.
Qwen is a **tool** the agent calls, not the agent's own model. The bridge has no robot,
shell or file access.

```text
S100 agent runtime (192.168.127.10)
  └─ https://vbot-mcp.urbot.ai/mcp        Bearer QWEN_MCP_TOKEN
       └─ Cloudflare Tunnel → Mac Studio 127.0.0.1:8010   (server.py, LaunchAgent)
            └─ http://127.0.0.1:8001/v1   Bearer QWEN_API_KEY (Caddy)
                 └─ Ollama :11434 → qwen3.8-27b:latest
```

The bridge calls Caddy on loopback, not `api-qwen.urbot.ai`, because both run on the
same machine. The public `api-qwen` route is unchanged.

## Files

| Path | What |
| --- | --- |
| `qwen-bridge/` | Teammate's package as received (server, tests, handoff notes) |
| `deploy/start.sh` | LaunchAgent entry point; loads `~/vbot-qwen-mcp/env` literally |
| `deploy/ai.urbot.vbot-qwen-mcp.plist` | User LaunchAgent, `KeepAlive`, logs in `~/Library/Logs/vbot-qwen-mcp/` |
| `deploy/add_vbot_mcp_ingress.sh` | Adds the tunnel rule + DNS record (run once with sudo) |
| `deploy/register_on_dog.sh` | Registers `qwen-bridge` with the S100 agent and waits for discovery |

## Where things live

**Mac Studio (`urbot`)**: `~/vbot-qwen-mcp/` holds `server.py`, `start.sh`, `test_client.py`,
`tests/` and `env` (0600: `QWEN_API_KEY`, copied from `~/qwen-api-proxy/env.sh`, and
`QWEN_MCP_TOKEN`). LaunchAgent: `~/Library/LaunchAgents/ai.urbot.vbot-qwen-mcp.plist`.

**S100 (`vbot`)**: `~/vbot-qwen-mcp/register_on_dog.sh`. The agent's saved connection is
named `qwen-bridge`, `workingDir=/app/vbot-agent-harness`, protocol pinned to `2025-06-18`
(`server.py` rejects any other version in `initialize`).

## Operate

On the Mac Studio:

```bash
launchctl print gui/$(id -u)/ai.urbot.vbot-qwen-mcp | grep -E 'state|last exit'
```

```bash
launchctl kickstart -k gui/$(id -u)/ai.urbot.vbot-qwen-mcp
```

```bash
tail -f ~/Library/Logs/vbot-qwen-mcp/mcp-error.log
```

The log has one line per request (no prompts, headers or secrets). A robot turn that
uses the tool shows as `initialize` / `tools/list` POSTs at discovery, then a POST per call.

Local smoke test (real Qwen call, expects `PASS tools/call: VBOT MCP READY`):

```bash
cd ~/vbot-qwen-mcp && ( while IFS='=' read -r k v; do export "$k=$v"; done < env; python3 test_client.py )
```

On the S100, check the agent's view:

```bash
curl --noproxy '*' -fsS --get http://192.168.127.10:8787/api/admin/extensions/vbot-mcp/http/servers --data-urlencode workingDir=/app/vbot-agent-harness | jq '{catalogReady,refreshPending,servers:[.servers[]|select(.name=="qwen-bridge")]}'
```

Turn it off without deleting it (there is no DELETE API):

```bash
curl --noproxy '*' -fsS -X PATCH 'http://192.168.127.10:8787/api/admin/extensions/vbot-mcp/http/servers/qwen-bridge?workingDir=/app/vbot-agent-harness' -H 'Content-Type: application/json' --data-binary '{"enabled":false}' | jq .
```

## Rotate the MCP token

1. Generate a new value into `QWEN_MCP_TOKEN` in `~/vbot-qwen-mcp/env` and kickstart the agent.
2. On the S100, GET `/servers/qwen-bridge/config` for a fresh `revision`, then PUT
   `{"revision":…, "url":"https://vbot-mcp.urbot.ai/mcp", "headers":{"Authorization":"Bearer <new>"}, "envHttpHeaders":{}}`
   from a 0600 file, and delete the file.

Rotating `QWEN_API_KEY` means updating both `~/qwen-api-proxy/env.sh` and `~/vbot-qwen-mcp/env`.

## Limits

- Tool calls wait up to 75 s for Qwen, `max_tokens` 256, one question of ≤2000 characters.
- No Cloudflare Access app on `vbot-mcp.urbot.ai`: the robot cannot do a browser login. The
  bridge's bearer token is the gate. If Cloudflare's bot rules 403 the robot's HTTP client,
  relax them for this hostname rather than changing the bridge.
