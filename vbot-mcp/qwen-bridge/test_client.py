"""Exercise MCP initialize, notification, tools/list, tools/call.

MCP_SKIP_QWEN=1 skips the two calls that reach Qwen (qwen_ask, chess_coach_explain), for a
smoke test with no model. Weather and chess context depend on the bridge's configuration
(VBOT_LOCATION, CHESS_CONTEXT_TOKEN); when they are not set up, their tool errors are
printed as INFO rather than failures, so the protocol check still passes.
"""
import json
import os
from urllib import request

URL = os.getenv("MCP_URL", "http://127.0.0.1:8010/mcp")
TOKEN = os.environ["QWEN_MCP_TOKEN"]
SKIP_QWEN = os.getenv("MCP_SKIP_QWEN") == "1"
EXPECTED = ["qwen_ask", "current_time", "current_weather", "chess_game_state", "chess_coach_explain"]


def send(payload, status=200):
    req = request.Request(URL, data=json.dumps(payload).encode(), headers={
        "Authorization": "Bearer " + TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    })
    with request.urlopen(req, timeout=90) as resp:
        assert resp.status == status, resp.status
        return json.load(resp) if status != 202 else None


def call(ident, name, arguments):
    return send({"jsonrpc":"2.0","id":ident,"method":"tools/call","params":{"name":name,"arguments":arguments}})["result"]


init = send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"vbot-qwen-smoke","version":"0.1"}}})
assert init["result"]["protocolVersion"] == "2025-06-18"
print("PASS initialize")
send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}, 202)
print("PASS notifications/initialized")
tools = send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
names = [t["name"] for t in tools["result"]["tools"]]
assert names == EXPECTED, names
print("PASS tools/list: " + ", ".join(names))

if SKIP_QWEN:
    print("SKIP tools/call qwen_ask (MCP_SKIP_QWEN=1)")
else:
    result = call(3, "qwen_ask", {"question": "Reply with exactly VBOT MCP READY"})
    assert not result.get("isError"), result
    print("PASS tools/call: " + result["content"][0]["text"])

result = call(4, "current_time", {})
assert not result.get("isError"), result
print("PASS tools/call current_time: " + result["content"][0]["text"])

configurable = ["current_weather", "chess_game_state"] + ([] if SKIP_QWEN else ["chess_coach_explain"])
for ident, name in enumerate(configurable, start=5):
    result = call(ident, name, {})
    text = result["content"][0]["text"]
    print(("INFO " if result.get("isError") else "PASS ") + "tools/call " + name + ": " + text[:300])
