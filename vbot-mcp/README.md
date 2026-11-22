# VBOT agent ↔ Qwen MCP bridge

Gives the S100's built-in agent a `qwen_ask` tool backed by Qwen 27B on the Mac Studio,
plus read-only tools for the time, the weather and the Chess Buddy game (see
[Read-only tools](#read-only-tools)). Qwen is a **tool** the agent calls, not the agent's
own model. The bridge has no robot, shell or file access, and cannot make chess moves.

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
| `../server/vbot_live_context.py` | Time and weather, shared with voice mode (copied next to `server.py` when deployed) |
| `../server/vbot_game_context.py` | Read-only game snapshot and its token check, served by the chess server |

## Read-only tools

All five tools only read. None moves the robot, plays a move on the board or runs
commands. (`latestReview.bestMove` is the coach's review of a move already played.) Lumi's Nova specialist is not included (it needs Evan's OK and a Nova login).

| Tool | Arguments | Source | Needs |
| --- | --- | --- | --- |
| `qwen_ask` | `question` | Qwen on the Mac Studio | `QWEN_API_KEY` |
| `current_time` | none | `local_time()` in `server/vbot_live_context.py` | `VBOT_TIMEZONE` (default America/Los_Angeles) |
| `current_weather` | none | `WeatherLookup` in the same file (Open-Meteo, no key, 10 min cache) | `VBOT_LOCATION` |
| `chess_game_state` | none | `GET /api/vbot/game-context` on the chess server | `CHESS_CONTEXT_TOKEN` on both sides |
| `chess_coach_explain` | none | the same snapshot, worded by one Qwen call | as above, plus `QWEN_API_KEY` |

The no-argument tools accept missing, `null` or `{}` arguments, because the S100's client
has not been observed calling them. Results are JSON text. Errors come back as
`isError: true` with a plain reason, for example "location is not configured", so
the agent can say why.

**Time and weather** reuse voice mode's code, so the two paths always agree. The bridge
calls `local_time()` and `WeatherLookup.current(VBOT_LOCATION)` directly, not the keyword
router: the agent has already decided it wants the time or weather. The weather tool takes no
place argument, because the location is the operator's setting and never guessed (the
same rule as voice mode). In the repo, `server.py` finds the module in `../../server`.
Deployed, copy `server/vbot_live_context.py` next to `server.py` in `~/vbot-qwen-mcp/`.
The import happens on first use, so a missing file breaks only these two tools, not
`qwen_ask`.

**Chess Buddy context.** The live game is held by the chess server (Docker,
127.0.0.1:8765): `vbot_demo.game_id` names the game the dog follows, and the bot runtime's
per-game cache (`runtime.game_state()`) has the moves. `server/vbot_game_context.py`
builds a snapshot from those two sources. It contains the session kind, reactions
(`off`/`rehearsal`/`live`), and the game: `live`, `status`, `fen`, `sideToMove`,
`moveNumber`, `lastMove` (UCI, SAN, who played it), `inCheck`, `humanColor`/`botColor`,
player display names (cut to 40 characters) and `winner`. It also carries `latestReview`,
the coach's newest engine review for that game (move, classification, centipawn loss,
best move). If no game is connected, it falls back to the bot's most recent game
(`source: "bot"`). "No game" and an active practice or performance session are normal
answers with a `note`, not errors. A finished practice or performance does not hide the bot's game.
`latestReview` can be about an earlier move than `lastMove` (after the bot replies, for example).

Why this read path:

- **Not the pairing key.** Every `/api/` route is behind `TabletAccess`, and the pairing key
  authorizes robot controls. The bridge faces the internet, so it must not hold that key.
- **Not `/api/vbot/status`.** That route calls `touch_operator()`, the presence signal
  behind `VBOT_OPERATOR_TIMEOUT_S`. Polling it from the bridge would keep server-started
  motion alive with no operator present. `vbot_demo.status()` can also disarm or retarget
  through `_sync_network()`. The snapshot reads the fields directly under `demo.lock`.
- **Its own token.** Through Docker's port proxy, the container sees the bridge and the
  public tunnel (`chess-api.urbot.ai`) as the same private address. So
  `/api/vbot/game-context` is treated as public, and it is the only route checked before the pairing
  gate. It needs `X-Chess-Buddy-Context-Token`, matched with
  `compare_digest` against `CHESS_CONTEXT_TOKEN` (at least 40 characters; off when unset), and it
  refuses any browser `Origin`. The pairing key alone gets 403. The response leaves out
  robot addresses, events, accounts and tokens.
- **No new engine work.** `chess_coach_explain` sends Qwen only the snapshot's facts and the
  already-computed review. Its prompt forbids invented evaluations or moves, and it leaves
  out player names. With no game, it returns the note without calling Qwen.

The bridge only accepts `CHESS_CONTEXT_URL` over HTTPS or on localhost; the default is
`http://127.0.0.1:8765/api/vbot/game-context`. Player names and moves are marked as data,
not instructions (`dataNote`).

### Turning the new tools on (not done yet: after the Nov 11–12 demos)

Nothing below has been deployed. Until the chess container runs the new server, the
chess tools return "Chess Buddy server has no game-context route yet" and everything
else is unaffected.

1. Back up `~/vbot-qwen-mcp/{server.py,env}` and `~/chess-coach/.env` with timestamps.
2. Generate one `CHESS_CONTEXT_TOKEN`, for example `python3 -c 'import secrets;print(secrets.token_urlsafe(32))'`
   (43 characters), straight into both env files with mode 0600, never echoed. Check that the
   compose file passes it to the container: with `env_file`, any key passes; with an
   `environment:` list, add it there.
3. Add `VBOT_TIMEZONE` and `VBOT_LOCATION` to `~/vbot-qwen-mcp/env` (the same values as voice mode).
4. Redeploy the chess container (the user runs it; see `deploy/deploy_test_dashboard.sh`
   for the pattern). **Do not deploy this branch's whole `server/` as it stands.** The live
   container runs voice mode's time, weather and Big Head changes (`vbot_voice.py`,
   `vbot_live_context.py`). As of Nov 11 those are uncommitted in the main checkout, so this
   branch's `vbot_voice.py` does not have them, and deploying it would roll them back. Merge
   that work with this branch first, or ship only `app.py`, `bot_runtime.py`, `vbot_demo.py`
   and `vbot_game_context.py`.
5. Copy `qwen-bridge/server.py` and `server/vbot_live_context.py` to `~/vbot-qwen-mcp/`, then
   `launchctl kickstart -k gui/$(id -u)/ai.urbot.vbot-qwen-mcp`.
6. Run `test_client.py` (below). The S100 keeps the tool list from discovery, so refresh
   the `qwen-bridge` connection or wait for its catalog to refresh before a robot turn.

## Voice mode: keep the keyword router or use Qwen tool calling?

**Recommendation: keep the keyword router in `server/vbot_voice.py` for now.** Revisit tool
calling after the demos, starting with chess context.

What the repo shows today (the voice-mode `ask_qwen` with `live_instructions` is the
uncommitted version in the main checkout as of Nov 11; this branch's `vbot_voice.py` predates it):

- `ask_qwen` makes **one** model call per spoken turn. The live data is chosen by
  `live_instructions(heard)` before the call, and the reply comes back in a strict JSON
  schema (`understood` / `clarifying` / `reply`) through `QwenClient.create(text=REPLY_FORMAT)`.
- `QwenClient` (`server/coach/qwen_adapter.py`) has no `tools` parameter and no
  tool-call loop. Switching means adding both, and handling `tool_calls` responses,
  arguments, follow-up messages and errors.
- With tool calling, any turn that needs data becomes at least **two** sequential calls to a
  27B model (decide, then answer), and every turn sends the tool definitions. On a
  spoken turn the person is waiting in silence.
- The router is deterministic and covered by offline tests (`tests/test_vbot_live_context.py`).
  It covers both English and Chinese, and when it misses, the model still answers, just without live data.

What we have not tested: whether Ollama's OpenAI-compatible endpoint and `qwen3.8-27b`
reliably combine tool calls with a strict `response_format` JSON schema in the same
conversation, and how much latency the second call adds on the Mac Studio. Measure both
before switching.

When to switch: once voice needs data the router can't detect well. Chess context is the
likely first case: "how am I doing?" or "what should I watch out for?" have no reliable
keywords. Then add tool calling for those tools only, in `QwenClient`. Reuse the same
functions the bridge calls (`vbot_live_context`, `vbot_game_context`), so voice and the dog's
agent stay in agreement. Keep the router as the fast path for time and weather.

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

Local smoke test (real Qwen call, expects `PASS tools/list: qwen_ask, current_time, …` and
`PASS tools/call: VBOT MCP READY`; add `MCP_SKIP_QWEN=1` to skip the Qwen calls):

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
- The chess snapshot waits up to 5 s. Weather waits up to 3 s per Open-Meteo request (two
  per lookup) and is cached for 10 minutes.
- Offline tests: `python3 -m unittest discover -s tests` in `qwen-bridge/` (stdlib only,
  also passes under the Mac Studio's `/usr/bin/python3` 3.9), and
  `.venv/bin/python -m unittest tests.test_vbot_game_context` at the repo root.
- No Cloudflare Access app on `vbot-mcp.urbot.ai`: the robot cannot do a browser login. The
  bridge's bearer token is the gate. If Cloudflare's bot rules 403 the robot's HTTP client,
  relax them for this hostname rather than changing the bridge.
