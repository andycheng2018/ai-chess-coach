"""Minimal, sessionless Streamable HTTP MCP service for VBOT EDU agent.

Implements the subset documented in VitaDynamics/vbot-lab, without any
robot actuation capabilities. Uses Python's standard library only.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request
from urllib.parse import urlsplit

MCP_VERSION = "2025-06-18"
MAX_BODY = 16_384
MAX_PROMPT = 2_000
MODEL = os.getenv("QWEN_MODEL", "qwen3.8-27b:latest")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://api-qwen.urbot.ai/v1").rstrip("/")
LISTEN_HOST = os.getenv("MCP_HOST", "127.0.0.1")
LISTEN_PORT = int(os.getenv("MCP_PORT", "8010"))

TOOL = {
    "name": "qwen_ask",
    "description": "Ask the remote Qwen model for a text-only answer or explanation. This tool cannot control the robot or execute actions. Use for reasoning, knowledge and drafting; verify facts before relying on them.",
    "inputSchema": {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "The question for Qwen (up to 2000 characters)."}},
        "required": ["question"],
        "additionalProperties": False,
    },
}


def call_qwen(question):
    key = os.environ.get("QWEN_API_KEY")
    if not key:
        raise RuntimeError("QWEN_API_KEY is not set on the MCP server")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful text-only assistant supporting a robot agent. Do not output physical robot control instructions or claim to operate hardware. Be concise."},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "max_tokens": 256,
    }
    outgoing = request.Request(
        QWEN_BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "curl/8.7.1"},
        method="POST",
    )
    try:
        with request.urlopen(outgoing, timeout=75) as resp:
            data = json.load(resp)
    except error.HTTPError as exc:
        raise RuntimeError("Qwen upstream HTTP " + str(exc.code)) from exc
    except error.URLError as exc:
        raise RuntimeError("Qwen upstream connection failed") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Qwen returned an unexpected response format") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Qwen returned an empty answer")
    return content.strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "VBOTQwenMCP/0.1"

    def log_message(self, fmt, *args):
        # Avoid logging prompts, headers or secrets.
        sys.stderr.write("[mcp] %s\n" % (fmt % args))

    def send_json(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def rpc_error(self, ident, code, message, status=200):
        self.send_json(status, {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}})

    def do_GET(self):
        if self.path == "/healthz":
            self.send_json(200, {"ok": True, "service": "vbot-qwen-mcp"})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/mcp":
            self.send_error(404)
            return
        token = os.environ.get("QWEN_MCP_TOKEN")
        if not token:
            self.send_json(503, {"error": "Server authentication not configured"})
            return
        from hmac import compare_digest
        if not compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
            self.send_json(401, {"error": "Unauthorized"})
            return
        # For localhost / Cloudflare proxy only. Reject browser cross-origin calls.
        if self.headers.get("Origin"):
            self.send_json(403, {"error": "Browser Origin is not allowed"})
            return
        size = self.headers.get("Content-Length", "")
        if not size.isdecimal() or int(size) > MAX_BODY:
            self.send_json(413, {"error": "Invalid or oversized body"})
            return
        try:
            obj = json.loads(self.rfile.read(int(size)))
        except (ValueError, UnicodeDecodeError):
            self.rpc_error(None, -32700, "Parse error", 400)
            return
        if not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0" or not isinstance(obj.get("method"), str):
            self.rpc_error(obj.get("id") if isinstance(obj, dict) else None, -32600, "Invalid Request", 400)
            return
        method = obj["method"]
        ident = obj.get("id")
        if method == "notifications/initialized" and "id" not in obj:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if "id" not in obj:
            self.rpc_error(None, -32600, "Expected request id", 400)
            return
        params = obj.get("params", {})
        if not isinstance(params, dict):
            self.rpc_error(ident, -32602, "Invalid params")
            return
        if method == "initialize":
            if params.get("protocolVersion") != MCP_VERSION:
                self.rpc_error(ident, -32602, "Unsupported protocol version")
                return
            result = {"protocolVersion": MCP_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "vbot-qwen-mcp", "version": "0.1.0"}}
        elif method == "tools/list":
            result = {"tools": [TOOL]}
        elif method == "tools/call":
            if params.get("name") != "qwen_ask":
                self.rpc_error(ident, -32602, "Unknown tool")
                return
            args = params.get("arguments")
            if not isinstance(args, dict) or set(args) != {"question"} or not isinstance(args["question"], str) or not 1 <= len(args["question"].strip()) <= MAX_PROMPT:
                self.rpc_error(ident, -32602, "question must be a nonempty string of at most 2000 characters")
                return
            try:
                answer = call_qwen(args["question"])
                result = {"content": [{"type": "text", "text": answer}], "isError": False}
            except Exception as exc:
                # Sanitized error message. Never include prompts or secret values.
                print("[mcp] tool error: " + type(exc).__name__, file=sys.stderr)
                result = {"content": [{"type": "text", "text": str(exc) if isinstance(exc, RuntimeError) else "Unexpected tool failure"}], "isError": True}
        else:
            self.rpc_error(ident, -32601, "Method not found")
            return
        self.send_json(200, {"jsonrpc": "2.0", "id": ident, "result": result})


def main():
    if not os.getenv("QWEN_MCP_TOKEN"):
        sys.exit("Missing QWEN_MCP_TOKEN (set a separate secret for the MCP service)")
    if not os.getenv("QWEN_API_KEY"):
        sys.exit("Missing QWEN_API_KEY (existing Caddy/Ollama key)")
    if urlsplit(QWEN_BASE_URL).scheme != "https" and not QWEN_BASE_URL.startswith("http://127.0.0.1:"):
        sys.exit("QWEN_BASE_URL must be HTTPS or localhost")
    if LISTEN_HOST != "127.0.0.1":
        sys.exit("For safety this demo only binds to 127.0.0.1. Use a protected reverse proxy for remote access.")
    with ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler) as server:
        print(f"VBOT Qwen MCP listening on http://{LISTEN_HOST}:{LISTEN_PORT}/mcp", flush=True)
        server.serve_forever()

if __name__ == "__main__":
    main()
