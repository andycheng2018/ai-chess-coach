import http.client
import json
import os
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def post(self, payload, token="test-token"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("POST", "/mcp", json.dumps(payload), {"Authorization": "Bearer " + token, "Content-Type":"application/json"})
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, json.loads(raw) if raw else None

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN":"test-token"})
    def test_auth_and_handshake(self):
        status, _ = self.post({"jsonrpc":"2.0","id":1,"method":"tools/list"}, token="wrong")
        self.assertEqual(status, 401)
        status, data = self.post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["protocolVersion"], "2025-06-18")
        status, data = self.post({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
        self.assertEqual(data["result"]["tools"][0]["name"], "qwen_ask")

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN":"test-token"})
    @patch.object(server, "call_qwen", return_value="VBOT MCP READY")
    def test_tool(self, mock_qwen):
        status, data = self.post({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"qwen_ask","arguments":{"question":"hello"}}})
        self.assertEqual(status, 200)
        self.assertFalse(data["result"]["isError"])
        self.assertEqual(data["result"]["content"][0]["text"], "VBOT MCP READY")
        mock_qwen.assert_called_once_with("hello")

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN":"test-token"})
    def test_invalid_question(self):
        status, data = self.post({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"qwen_ask","arguments":{"question":""}}})
        self.assertEqual(data["error"]["code"], -32602)

if __name__ == "__main__":
    unittest.main()
