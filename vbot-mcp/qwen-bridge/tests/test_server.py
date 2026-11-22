import http.client
import json
import os
import threading
import unittest
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

    def call(self, name, arguments=None, ident=10, **extra):
        params = {"name": name, **extra}
        if arguments is not None:
            params["arguments"] = arguments
        status, data = self.post({"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": params})
        self.assertEqual(status, 200)
        return data

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN": "test-token"})
    def test_lists_read_only_tools_with_qwen_ask_first(self):
        status, data = self.post({"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}})
        names = [tool["name"] for tool in data["result"]["tools"]]
        self.assertEqual(names, ["qwen_ask", "current_time", "current_weather", "chess_game_state", "chess_coach_explain"])
        for word in ("move_", "walk", "shell", "exec", "dance", "make_move"):
            self.assertFalse(any(word in name for name in names))

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN": "test-token", "VBOT_TIMEZONE": "Asia/Shanghai"})
    def test_current_time_uses_the_shared_live_context_and_any_empty_arguments(self):
        for arguments in (None, {}, {"ignored": True}):
            data = self.call("current_time", arguments)
            self.assertFalse(data["result"]["isError"])
            body = json.loads(data["result"]["content"][0]["text"])
            self.assertEqual(body["time_zone"], "Asia/Shanghai")
            self.assertIn("local_time", body)
        self.assertEqual(self.call("current_time", ["x"])["error"]["code"], -32602)

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN": "test-token", "VBOT_LOCATION": "Los Angeles, California"})
    def test_current_weather_reads_the_configured_place_only(self):
        lookup = Mock()
        lookup.current.return_value = {"ok": True, "place": "Los Angeles, California, United States",
                                       "condition": "clear", "temperature_f": 70, "source": "Open-Meteo"}
        with patch.object(server, "_weather_lookup", lookup):
            data = self.call("current_weather", {"location": "Paris"})
        lookup.current.assert_called_once_with("Los Angeles, California")
        body = json.loads(data["result"]["content"][0]["text"])
        self.assertEqual((body["condition"], body["temperature_f"]), ("clear", 70))
        self.assertNotIn("ok", body)
        lookup.current.return_value = {"ok": False, "error": "URLError"}
        with patch.object(server, "_weather_lookup", lookup):
            data = self.call("current_weather")
        self.assertTrue(data["result"]["isError"])
        self.assertIn("URLError", data["result"]["content"][0]["text"])

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN": "test-token", "VBOT_LOCATION": ""})
    def test_current_weather_without_a_location_says_so(self):
        data = self.call("current_weather")
        self.assertTrue(data["result"]["isError"])
        self.assertIn("VBOT_LOCATION", data["result"]["content"][0]["text"])

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN": "test-token"})
    def test_missing_live_context_module_breaks_only_time_and_weather(self):
        with patch.dict(sys.modules, {"vbot_live_context": None}):
            data = self.call("current_time")
        self.assertTrue(data["result"]["isError"])
        self.assertIn("not installed", data["result"]["content"][0]["text"])
        with patch.object(server, "call_qwen", return_value="still here"):
            self.assertEqual(self.call("qwen_ask", {"question": "hi"})["result"]["content"][0]["text"], "still here")

    @patch.dict(os.environ, {"QWEN_MCP_TOKEN": "test-token"})
    def test_unknown_tool_is_rejected(self):
        self.assertEqual(self.call("move_forward")["error"]["code"], -32602)


SNAPSHOT = {
    "available": True, "session": "game", "reactions": "off", "source": "dog", "note": None,
    "game": {"gameId": "g1", "status": "started", "live": True,
             "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
             "sideToMove": "black", "moveNumber": 2, "plies": 3, "inCheck": False,
             "lastMove": {"uci": "g1f3", "san": "Nf3", "by": "white"}, "humanColor": "white", "botColor": "black",
             "players": {"white": "Rich", "black": "CoachBot"}, "winner": None, "rated": False, "updatedAt": 1},
    "latestReview": {"ply": 3, "playerColor": "white", "playedMove": "Nf3", "classification": "good",
                     "centipawnLoss": 12, "bestMove": "Nc3"},
}


class FakeChessServer(BaseHTTPRequestHandler):
    reply = (200, SNAPSHOT)
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeChessServer.seen.append((self.path, self.headers.get("X-Chess-Buddy-Context-Token"), self.headers.get("X-Chess-Buddy-Token")))
        status, body = FakeChessServer.reply
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ChessContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chess = ThreadingHTTPServer(("127.0.0.1", 0), FakeChessServer)
        threading.Thread(target=cls.chess.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/api/vbot/game-context" % cls.chess.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.chess.shutdown()
        cls.chess.server_close()

    def setUp(self):
        FakeChessServer.reply, FakeChessServer.seen = (200, SNAPSHOT), []
        patcher = patch.object(server, "CHESS_CONTEXT_URL", self.url)
        patcher.start()
        self.addCleanup(patcher.stop)

    def result(self, fn):
        try:
            return False, fn()
        except RuntimeError as exc:
            return True, str(exc)

    @patch.dict(os.environ, {"CHESS_CONTEXT_TOKEN": "ctx-token"})
    def test_game_state_sends_only_the_context_token_and_marks_names_as_data(self):
        body = json.loads(server.chess_game_state())
        self.assertEqual(FakeChessServer.seen, [("/api/vbot/game-context", "ctx-token", None)])
        self.assertEqual(body["game"]["sideToMove"], "black")
        self.assertEqual(body["game"]["lastMove"]["san"], "Nf3")
        self.assertNotIn("available", body)
        self.assertIn("not instructions", body["dataNote"])

    @patch.dict(os.environ, {"CHESS_CONTEXT_TOKEN": "ctx-token"})
    def test_server_errors_become_clear_tool_errors(self):
        cases = [((404, {}), "no game-context route"), ((403, {}), "did not accept"),
                 ((500, {}), "HTTP 500"), ((200, {"available": False}), "unexpected response")]
        for reply, message in cases:
            FakeChessServer.reply = reply
            failed, text = self.result(server.chess_game_state)
            self.assertTrue(failed)
            self.assertIn(message, text)

    def test_unconfigured_unreachable_or_non_local_http_servers_fail_closed(self):
        with patch.dict(os.environ, {"CHESS_CONTEXT_TOKEN": ""}):
            self.assertIn("not configured", self.result(server.chess_game_state)[1])
        with patch.dict(os.environ, {"CHESS_CONTEXT_TOKEN": "ctx-token"}):
            with patch.object(server, "CHESS_CONTEXT_URL", "http://127.0.0.1:9/api/vbot/game-context"):
                self.assertIn("not reachable", self.result(server.chess_game_state)[1])
            with patch.object(server, "CHESS_CONTEXT_URL", "http://chess.example/api/vbot/game-context"):
                self.assertIn("HTTPS or localhost", self.result(server.chess_game_state)[1])
        self.assertEqual(FakeChessServer.seen, [])

    @patch.dict(os.environ, {"CHESS_CONTEXT_TOKEN": "ctx-token"})
    def test_explain_grounds_qwen_in_the_snapshot(self):
        with patch.object(server, "call_qwen", return_value="White developed the knight.") as qwen:
            body = json.loads(server.chess_coach_explain())
        prompt = qwen.call_args.args[0]
        self.assertIn(SNAPSHOT["game"]["fen"], prompt)
        self.assertIn('"classification": "good"', prompt)
        self.assertIn("never invent", prompt)
        self.assertNotIn("Rich", prompt)  # names are not needed to explain the position
        self.assertEqual(body["explanation"], "White developed the knight.")
        self.assertEqual(body["basedOn"]["latestReview"]["bestMove"], "Nc3")

    @patch.dict(os.environ, {"CHESS_CONTEXT_TOKEN": "ctx-token"})
    def test_explain_keeps_an_older_review_tied_to_its_own_move(self):
        game = {**SNAPSHOT["game"], "lastMove": {"uci": "b8c6", "san": "Nc6", "by": "black"}, "sideToMove": "white"}
        FakeChessServer.reply = (200, {**SNAPSHOT, "game": game})
        with patch.object(server, "call_qwen", return_value="ok") as qwen:
            body = json.loads(server.chess_coach_explain())
        prompt = qwen.call_args.args[0]
        self.assertIn("its own playedMove", prompt)
        self.assertIn("never attach it to a different move", prompt)
        self.assertEqual(body["basedOn"]["lastMove"]["san"], "Nc6")
        self.assertEqual(body["basedOn"]["latestReview"]["playedMove"], "Nf3")

    @patch.dict(os.environ, {"CHESS_CONTEXT_TOKEN": "ctx-token"})
    def test_explain_without_a_game_returns_the_note_without_calling_qwen(self):
        FakeChessServer.reply = (200, {**SNAPSHOT, "game": None, "note": "No chess game is connected to the dog."})
        with patch.object(server, "call_qwen") as qwen:
            body = json.loads(server.chess_coach_explain())
        qwen.assert_not_called()
        self.assertIsNone(body["explanation"])
        self.assertIn("No chess game", body["note"])


if __name__ == "__main__":
    unittest.main()
