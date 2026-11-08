# VBOT ↔ Mac Studio Qwen — teammate handoff

**Status:** Software bridge tested successfully on developer MacBook. **Not yet installed, registered, or tested on physical VBOT S100.**

## Start here

Read **TEAMMATE_HANDOFF.md** first; it distinguishes what is done from what needs to be integrated. `server.py` is the stand-alone HTTP MCP service. `test_client.py` is a live smoke test. `tests/test_server.py` contains offline unit tests.

## Architecture

```text
VBOT's existing agent (MCP client)
    └─ [TO BE REGISTERED] HTTPS MCP endpoint /mcp (MCP bearer token)
         └─ Python bridge server.py, localhost:8010
              └─ HTTPS https://api-qwen.urbot.ai/v1 (Qwen API bearer key)
                   └─ Cloudflare Tunnel → Caddy :8001 → Ollama :11434 → Qwen 27B
```

The existing Mac Studio Qwen endpoint is proven usable. The endpoint for the MCP server is **not yet published**. The two bearer tokens are different secrets. Neither secret is in this package.

## Local launch (Python 3.9+, standard library only)

Run in a shell with the existing Qwen API key loaded securely; don't hardcode it:

```bash
export QWEN_API_KEY='...set securely...'
export QWEN_MCP_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
python3 server.py &
PID=$!
python3 test_client.py
kill "$PID"
```

The key may be loaded from a secret store instead of typing it inline. The example above is a placeholder, not a recommended place to store real values in shell history. The MCP token is generated for local tests and needs a stable securely stored value for deployment.

Expected: `PASS initialize`, `PASS notifications/initialized`, `PASS tools/list: qwen_ask`, `PASS tools/call: VBOT MCP READY`.

Run offline tests:

```bash
python3 -m unittest discover -s tests -v
```

Useful environment variables: `QWEN_API_KEY` (required), `QWEN_MCP_TOKEN` (required), `QWEN_BASE_URL` (default `https://api-qwen.urbot.ai/v1`), `QWEN_MODEL` (default `qwen3.8-27b:latest`), `MCP_HOST` (enforced `127.0.0.1`), `MCP_PORT` (default `8010`), `MCP_URL` (test client override).

The bridge intentionally has no robot movement or device control tools. For production, use an approved secure service manager and reverse proxy; protect and monitor the new endpoint.
