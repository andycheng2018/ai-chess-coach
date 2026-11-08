"""Exercise MCP initialize, notification, tools/list, tools/call."""
import json
import os
from urllib import request

URL = os.getenv("MCP_URL", "http://127.0.0.1:8010/mcp")
TOKEN = os.environ["QWEN_MCP_TOKEN"]


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

init = send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"vbot-qwen-smoke","version":"0.1"}}})
assert init["result"]["protocolVersion"] == "2025-06-18"
print("PASS initialize")
send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}, 202)
print("PASS notifications/initialized")
tools = send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
assert any(t["name"] == "qwen_ask" for t in tools["result"]["tools"])
print("PASS tools/list: qwen_ask")
call = send({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"qwen_ask","arguments":{"question":"Reply with exactly VBOT MCP READY"}}})
assert not call["result"].get("isError"), call["result"]
print("PASS tools/call: " + call["result"]["content"][0]["text"])
