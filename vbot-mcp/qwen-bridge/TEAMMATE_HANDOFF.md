# Engineering handoff: Qwen backend for VBOT EDU agent

## 1. Outcome achieved

A Mac Studio runs the `qwen3.8-27b:latest` model behind Ollama (`127.0.0.1:11434`). Incoming requests use the established Cloudflare hostname `https://api-qwen.urbot.ai/v1`, which routes to a Caddy gateway on Mac Studio port `8001` and then to Ollama. Caddy checks `Authorization: Bearer <QWEN_API_KEY>`.

A standalone Python HTTP MCP bridge (`server.py`) now wraps that inference API with an agent-callable read-only tool `qwen_ask(question: string)`. It implements the subset of JSON-RPC / Streamable HTTP used by VBOT's documented HTTP MCP contract, on local port `8010`, path `/mcp`. It checks a **different** credential, `QWEN_MCP_TOKEN`. Its input is text; its output is text; it does not issue robot or shell commands.

## 2. Verified tests (performed by developer)

- Ollama locally returned `READY` from `/v1/chat/completions`.
- Authenticated remote requests through Cloudflare returned `VBOT READY`; MacBook `test_qwen.py` returned `VBOT READY`.
- Remote `/v1/models` and `/v1/chat/completions` returned HTTP 200 when authenticated.
- Live local MCP smoke test passed **initialize**, **notifications/initialized**, **tools/list**, **tools/call**, with a Qwen response `VBOT MCP READY`.
- A `403` during early Python MCP requests was resolved by adding an explicit `User-Agent` header to the upstream request. This fix is included in the packaged `server.py`. This likely reflects an edge/proxy header policy; not proof of a specific Cloudflare rule.

These tests establish the *software path*: **local MCP client → MCP server → Cloudflare/Caddy → Qwen**. They do **not** establish that the physical VBOT agent has discovered the MCP tool or used it.

## 3. Teammate action items

1. **Deploy the packaged bridge** on a trusted always-on host (Mac Studio recommended). Use a persistent service process with secret environment variables and restricted permissions. Keep `MCP_HOST=127.0.0.1`, `MCP_PORT=8010`. Do not publish the Ollama port directly.
2. **Provide an accessible, protected HTTPS MCP URL**, e.g. `https://vbot-mcp.urbot.ai/mcp`, routed via the existing Cloudflare tunnel to `http://127.0.0.1:8010`. This hostname is a proposed placeholder, **not yet created**. Don't change the existing working `api-qwen.urbot.ai` route. Confirm the full MCP `test_client.py` succeeds using `MCP_URL` pointing at the HTTPS URL.
3. **Register the remote MCP tool in the VBOT device agent** when S100 access is available. Follow the vendor's MCP connection API below from the trusted `vbot` SSH shell. Use an **MCP token** in the registered `Authorization` header, **not** the Caddy Qwen key. Inspect current connections first and avoid touching existing ones. If the vendor configuration requires `workingDir`, use the same correct workspace in all calls.
4. **Refresh and validate discovery**. Check for the tool `qwen_ask`, initiate a text-only agent turn that specifically calls it, and check the result. If agent fails to choose the tool, review tool descriptions / instructions; do not assume model-provider replacement.
5. **End-to-end verification**: robot agent → exposed MCP server → authenticated Qwen API → generated answer → agent. Then document operational startup/restart procedure, logs, reliability, timeouts and credential rotation.

## 4. Vendor integration reference

- HTTP MCP contract: https://github.com/VitaDynamics/vbot-lab/blob/release/V1.6.0/docs/interfaces/agent/http-mcp.md
- Agent MCP registration: https://github.com/VitaDynamics/vbot-lab/blob/release/V1.6.0/docs/interfaces/agent/mcp-config.md

Per the vendor docs, from the S100 trusted `vbot` shell, the internal agent config service is `http://192.168.127.10:8787`, with route prefix `/api/admin/extensions/vbot-mcp/http`. First perform a `GET /servers` (with appropriate `workingDir` if needed) and inspect permissions, e.g. `canAddServers`. The documented `POST /servers` body has this shape:

```json
{
  "name": "qwen-bridge",
  "type": "http",
  "url": "https://vbot-mcp.urbot.ai/mcp",
  "headers": {"Authorization": "Bearer <ACTUAL_MCP_TOKEN>"}
}
```

**Do not execute that example with the placeholder token or URL.** The API's header values are literal strings; do not use `${ENV}` substitution. Vendor instructions also explain refresh and status checks. Do not expose its internal admin API to the public internet.

## 5. Scope boundary

This implements **Qwen as a tool used by the existing agent**, not **Qwen as the agent's foundational LLM**. The latter would require a separately documented provider override or vendor support. The bridge does not have access to sensors, motors, cameras, or motion controllers. If motion or autonomy is later requested, implement a separately reviewed robot-side integration with permission checks, safeguards, and hardware testing.

## 6. Security and troubleshooting

- `QWEN_API_KEY` authenticates MCP server → existing Qwen gateway; `QWEN_MCP_TOKEN` authenticates agent → new MCP bridge. Never share keys in chat or source control.
- The bridge is loopback-only; Cloudflare/TLS + authorization must cover the public-facing deployment. An active tunnel is not itself an access policy.
- The test client's `PASS tools/call` is proof of the **Qwen-backed MCP tool**, not proof of robot agent integration.
- `401` at `/mcp`: missing/wrong MCP token. `401` at Qwen gateway: wrong Qwen key. `403` upstream: inspect proxy/header restrictions and source host. No need to alter the working Qwen service prematurely.
- The current implementation is a small demo-oriented MCP subset; assess interoperability, concurrency, retries, and logging before production rollout.

## 7. File map

- `server.py` — bridge server; `qwen_ask` tool implementation, authorization and request validation
- `test_client.py` — live JSON-RPC + Qwen smoke test
- `tests/test_server.py` — mocked offline unit tests
- `README.md` — rapid start
- `TEAMMATE_HANDOFF.md` — this implementation handoff
- `MESSAGE_TO_TEAMMATE.md` — copy/paste status message
