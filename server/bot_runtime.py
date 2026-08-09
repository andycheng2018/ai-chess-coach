from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine
import requests
import yaml

from coach.stockfish_analyzer import configure_supported_options, find_stockfish

LICHESS_URL = "https://lichess.org"
ROOT = Path(__file__).resolve().parent.parent
BOT_CONFIG = ROOT / "bot" / "config.yml"
ACTIVE_STATUSES = {"created", "started"}


@dataclass(frozen=True)
class BotLevel:
    id: str
    label: str
    display_elo: int
    think_ms: int
    multipv: int
    temperature_cp: float


# These are practice-strength estimates, not official Lichess ratings. Lower
# levels use a wider candidate distribution because Stockfish's built-in Elo
# limiting is not designed for true beginners.
BOT_LEVELS: dict[str, BotLevel] = {
    "newcomer": BotLevel("newcomer", "Newcomer", 500, 45, 10, 330.0),
    "beginner": BotLevel("beginner", "Beginner", 800, 60, 9, 210.0),
    "developing": BotLevel("developing", "Developing", 1100, 80, 7, 125.0),
    "club": BotLevel("club", "Club", 1400, 110, 6, 70.0),
    "strong": BotLevel("strong", "Strong", 1700, 160, 4, 34.0),
    "expert": BotLevel("expert", "Expert", 2000, 240, 3, 14.0),
}


def _token_from_config() -> tuple[str, str]:
    env_token = os.getenv("LICHESS_BOT_TOKEN", "").strip()
    env_username = os.getenv("LICHESS_BOT_USERNAME", "").strip()
    if env_token:
        return env_token, env_username

    if not BOT_CONFIG.exists():
        return "", env_username
    try:
        data = yaml.safe_load(BOT_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", env_username
    if not isinstance(data, dict):
        return "", env_username
    return str(data.get("token", "")).strip(), str(data.get("username", env_username or "")).strip()


def _is_placeholder(token: str) -> bool:
    upper = token.upper()
    return not token or any(marker in upper for marker in ("PASTE_", "TOKEN_HERE", "YOUR_TOKEN", "XXX"))


class BotEngine:
    """A fast Stockfish-backed move picker for a teaching opponent.

    Search time stays short at every level. Strength is controlled mainly by
    how willing the picker is to choose a lower-ranked MultiPV candidate, so a
    weaker bot does not feel slow simply because it is pretending to think.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()
        self._rng = rng or random.Random()

    def _ensure_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is not None:
            return self._engine
        engine = chess.engine.SimpleEngine.popen_uci(find_stockfish())
        configure_supported_options(engine, {"Threads": 1, "Hash": 16})
        self._engine = engine
        return engine

    def warmup(self) -> None:
        with self._lock:
            self._ensure_engine()

    def close(self) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
            if engine is None:
                return
            try:
                engine.quit()
            except Exception:
                try:
                    engine.close()
                except Exception:
                    pass

    def _reset_after_failure(self) -> None:
        engine, self._engine = self._engine, None
        if engine is None:
            return
        try:
            engine.close()
        except Exception:
            pass

    @staticmethod
    def _score(info: dict[str, Any], perspective: chess.Color) -> int:
        score = info.get("score")
        if score is None:
            return -100_000
        value = score.pov(perspective).score(mate_score=100_000)
        return int(value if value is not None else -100_000)

    def choose_move(self, board: chess.Board, level: BotLevel) -> tuple[chess.Move, int]:
        legal = list(board.legal_moves)
        if not legal:
            raise RuntimeError("No legal bot move is available.")

        started = time.perf_counter()
        with self._lock:
            try:
                engine = self._ensure_engine()
                raw = engine.analyse(
                    board,
                    chess.engine.Limit(time=max(0.02, level.think_ms / 1000.0)),
                    multipv=min(level.multipv, len(legal)),
                )
                infos = raw if isinstance(raw, list) else [raw]
                candidates: list[tuple[chess.Move, int]] = []
                for info in infos:
                    pv = info.get("pv") or []
                    if not pv:
                        continue
                    move = pv[0]
                    if move in board.legal_moves:
                        candidates.append((move, self._score(info, board.turn)))
                if not candidates:
                    raise RuntimeError("Stockfish returned no legal candidate moves.")

                best_score = max(score for _, score in candidates)
                weights: list[float] = []
                for _, score in candidates:
                    # Cap extreme mate/material swings so probabilities remain
                    # stable while still strongly preferring sane moves.
                    loss = min(1500, max(0, best_score - score))
                    weights.append(math.exp(-loss / max(1.0, level.temperature_cp)))
                move = self._rng.choices([candidate for candidate, _ in candidates], weights=weights, k=1)[0]
            except Exception:
                # A transient engine failure should not forfeit the game. Reset
                # Stockfish and make one legal fallback move; the next turn will
                # start a fresh engine process.
                self._reset_after_failure()
                move = self._rng.choice(legal)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return move, elapsed_ms


class LichessBotRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._event_thread: threading.Thread | None = None
        self._game_threads: dict[str, threading.Thread] = {}
        self._engine = BotEngine()
        self._level_id = "developing"
        self._username = os.getenv("LICHESS_BOT_USERNAME", "bot_2435").strip() or "bot_2435"
        self._connected = False
        self._running = False
        self._last_error = ""
        self._last_move_ms: int | None = None
        self._last_game_id: str | None = None
        self._submitted_ply: dict[str, int] = {}
        self._takeback_seen: set[tuple[str, int]] = set()
        self._game_start_condition = threading.Condition(self._lock)
        self._recent_game_starts: list[tuple[float, str, str]] = []

    def level(self) -> BotLevel:
        with self._lock:
            return BOT_LEVELS[self._level_id]

    def set_level(self, level_id: str) -> dict[str, Any]:
        if level_id not in BOT_LEVELS:
            raise ValueError(f"Unknown bot level: {level_id}")
        with self._lock:
            self._level_id = level_id
        return self.status(message=f"Difficulty set to {BOT_LEVELS[level_id].label}.")

    def _credentials(self) -> tuple[str, str]:
        token, configured_username = _token_from_config()
        if _is_placeholder(token):
            raise RuntimeError("Add the bot token to .env (LICHESS_BOT_TOKEN) or bot/config.yml.")
        return token, configured_username

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | tuple[float, float] = 12,
        allow: tuple[int, ...] = (200,),
    ) -> requests.Response:
        token, _ = self._credentials()
        response = requests.request(
            method,
            f"{LICHESS_URL}{path}",
            headers=self._headers(token),
            timeout=timeout,
        )
        if response.status_code not in allow:
            detail = response.text.strip().replace("\n", " ")[:300]
            raise RuntimeError(f"Lichess returned {response.status_code}: {detail or response.reason}")
        return response

    def _validate_account(self) -> None:
        profile = self._request("GET", "/api/account").json()
        username = str(profile.get("username") or profile.get("id") or "").strip()
        title = str(profile.get("title") or "").upper()
        if not username:
            raise RuntimeError("The bot token did not return a Lichess username.")
        if title != "BOT":
            raise RuntimeError(f"{username} is not a Lichess BOT account.")
        configured = _token_from_config()[1]
        if configured and configured.lower() != username.lower():
            raise RuntimeError(f"Bot token belongs to {username}, not configured bot {configured}.")
        with self._lock:
            self._username = username

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running and self._event_thread and self._event_thread.is_alive():
                return self.status(message="Bot is already running.")

        try:
            self._validate_account()
            self._engine.warmup()  # Avoid first-move process startup lag.
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._running = False
                self._connected = False
            raise

        with self._lock:
            self._stop.clear()
            self._last_error = ""
            self._running = True
            self._connected = False
            thread = threading.Thread(target=self._event_loop, name="lichess-bot-events", daemon=True)
            self._event_thread = thread
            thread.start()

        # Recover a game after backend restart instead of leaving the player
        # waiting forever for a gameStart event that already happened.
        try:
            playing = self._request("GET", "/api/account/playing").json().get("nowPlaying", [])
            for game in playing if isinstance(playing, list) else []:
                game_id = str(game.get("gameId") or "")
                if game_id:
                    self._ensure_game_thread(game_id)
        except Exception as exc:
            with self._lock:
                self._last_error = f"Could not recover active games: {exc}"

        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and not self._stop.is_set():
            if self.status().get("connected"):
                return self.status(message="Bot connected and ready.")
            time.sleep(0.08)
        return self.status(message="Bot runtime started; reconnecting to Lichess.")

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop.set()
            self._running = False
            self._connected = False
        self._engine.close()
        return self.status(message="Bot runtime stopped.")

    def status(self, message: str | None = None) -> dict[str, Any]:
        level = self.level()
        with self._lock:
            event_alive = bool(self._event_thread and self._event_thread.is_alive() and self._running)
            error = self._last_error
            if not event_alive and not error:
                token, _ = _token_from_config()
                if _is_placeholder(token):
                    error = "Bot token is not configured."
            payload: dict[str, Any] = {
                "running": event_alive,
                "connected": bool(self._connected and event_alive),
                "username": self._username,
                "level": level.id,
                "displayElo": level.display_elo,
                "lastMoveMs": self._last_move_ms,
                "activeGames": sum(1 for thread in self._game_threads.values() if thread.is_alive()),
                "lastGameId": self._last_game_id,
                "error": error or None,
            }
            if message:
                payload["message"] = message
            return payload

    def _wait_for_game_start(self, *, opponent: str = "", since: float, timeout: float = 8.0) -> str | None:
        """Wait for the bot event stream to report the newly started game.

        This is more reliable than asking the browser to hammer /api/account/playing
        after accepting a challenge. The event stream is the authoritative source
        for challenge -> game transitions.
        """
        opponent_key = opponent.strip().lower()
        deadline = time.monotonic() + timeout
        with self._game_start_condition:
            while True:
                for started_at, game_id, opponent_name in reversed(self._recent_game_starts):
                    if started_at < since:
                        break
                    if not opponent_key or opponent_name == opponent_key:
                        return game_id
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._game_start_condition.wait(timeout=remaining)

    def accept_challenge(
        self,
        challenge_id: str,
        opponent: str = "",
        color: str = "",
    ) -> dict[str, Any]:
        challenge_id = challenge_id.strip()
        if not challenge_id:
            raise ValueError("challenge id is required")

        color = color.strip().lower()
        if color and color not in {"white", "black"}:
            raise ValueError("color must be white or black")

        if not self.status()["running"]:
            self.start()

        if not self.status().get("connected"):
            raise RuntimeError(
                "Bot event stream is not connected yet. Try again in a moment."
            )

        started_after = time.monotonic() - 0.25

        path = f"/api/challenge/{challenge_id}/accept"

        # Open Lichess challenges can specify which color the joining
        # player should take. SenseRobot includes this in its QR URL.
        if color:
            path += f"?color={color}"

        response = self._request(
            "POST",
            path,
            allow=(200, 404, 409),
        )

        game_id = self._wait_for_game_start(
            opponent=opponent,
            since=started_after,
            timeout=8.0,
        )

        if game_id:
            payload = self.status(
                message="Open challenge joined and game started."
            )
            payload["gameId"] = game_id
            payload["color"] = color or None
            return payload

        if response.status_code != 200:
            raise RuntimeError(
                f"Lichess challenge transitioned ({response.status_code}) "
                "but no gameStart event arrived."
            )

        raise RuntimeError(
            "Lichess accepted the challenge, but the bot did not "
            "receive gameStart within 8 seconds."
        )

    def _event_loop(self) -> None:
        backoff = 0.8
        while not self._stop.is_set():
            try:
                token, _ = self._credentials()

                with requests.get(
                    f"{LICHESS_URL}/api/stream/event",
                    headers={**self._headers(token), "Accept": "application/x-ndjson"},
                    stream=True,
                    timeout=(10, 300),
                ) as response:
                    if response.status_code == 429:
                        with self._lock:
                            self._connected = False
                            self._last_error = (
                                "Lichess rate limited the bot event stream. "
                                "Waiting 60 seconds before retrying."
                            )
                        if self._stop.wait(60):
                            return
                        backoff = 0.8
                        continue

                    if response.status_code != 200:
                        raise RuntimeError(
                            f"Bot event stream returned {response.status_code}: "
                            f"{response.text[:200]}"
                        )

                    with self._lock:
                        self._connected = True
                        self._last_error = ""
                    backoff = 0.8

                    for raw in response.iter_lines():
                        if self._stop.is_set():
                            return
                        if raw:
                            self._handle_event(json.loads(raw.decode("utf-8")))

                with self._lock:
                    self._connected = False

            except Exception as exc:
                with self._lock:
                    self._connected = False
                    self._last_error = f"Bot event stream: {exc}"

                if self._stop.wait(backoff):
                    return
                backoff = min(12.0, backoff * 1.8)

        with self._lock:
            self._connected = False

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "gameStart":
            game = event.get("game") or {}
            game_id = str(game.get("id") or game.get("gameId") or "")
            opponent = game.get("opponent") or {}
            opponent_name = str(opponent.get("username") or opponent.get("name") or opponent.get("id") or "").lower()
            if game_id:
                now = time.monotonic()
                with self._game_start_condition:
                    self._last_game_id = game_id
                    self._recent_game_starts.append((now, game_id, opponent_name))
                    cutoff = now - 30.0
                    self._recent_game_starts = [entry for entry in self._recent_game_starts if entry[0] >= cutoff]
                    self._game_start_condition.notify_all()
                self._ensure_game_thread(game_id)
        elif event_type == "gameFinish":
            game = event.get("game") or {}
            game_id = str(game.get("id") or game.get("gameId") or "")
            if game_id:
                self._clear_game_state(game_id)

    def _clear_game_state(self, game_id: str) -> None:
        with self._lock:
            self._submitted_ply.pop(game_id, None)
            self._takeback_seen = {entry for entry in self._takeback_seen if entry[0] != game_id}

    def _ensure_game_thread(self, game_id: str) -> None:
        with self._lock:
            existing = self._game_threads.get(game_id)
            if existing and existing.is_alive():
                return
            thread = threading.Thread(
                target=self._game_loop,
                args=(game_id,),
                name=f"lichess-game-{game_id[:8]}",
                daemon=True,
            )
            self._game_threads[game_id] = thread
            self._last_game_id = game_id
            thread.start()

    @staticmethod
    def _board_from_state(initial_fen: str, moves_text: str) -> chess.Board:
        board = chess.Board() if not initial_fen or initial_fen == "startpos" else chess.Board(initial_fen)
        for move_text in moves_text.split():
            try:
                board.push_uci(move_text)
            except ValueError as exc:
                raise RuntimeError(f"Invalid move in Lichess game stream: {move_text}") from exc
        return board

    def _game_loop(self, game_id: str) -> None:
        """Keep one bot-game stream alive until that game finishes.

        A dropped HTTP stream reconnects instead of silently killing the bot for
        the rest of the game. State is reconstructed from each fresh gameFull.
        """
        backoff = 0.7
        finished = False
        try:
            while not self._stop.is_set() and not finished:
                initial_fen = "startpos"
                bot_color: chess.Color | None = None
                try:
                    token, _ = self._credentials()
                    with requests.get(
                        f"{LICHESS_URL}/api/bot/game/stream/{game_id}",
                        headers={**self._headers(token), "Accept": "application/x-ndjson"},
                        stream=True,
                        timeout=(10, 300),
                    ) as response:
                        if response.status_code == 429:
                            with self._lock:
                                self._last_error = (
                                    f"Game {game_id}: Lichess rate limited the game stream. "
                                    "Waiting 60 seconds before retrying."
                                )
                            if self._stop.wait(60):
                                return
                            backoff = 0.7
                            continue

                        if response.status_code != 200:
                            raise RuntimeError(
                                f"Game stream returned {response.status_code}: "
                                f"{response.text[:200]}"
                            )

                        backoff = 0.7
                        for raw in response.iter_lines():
                            if self._stop.is_set():
                                return
                            if not raw:
                                continue
                            event = json.loads(raw.decode("utf-8"))
                            event_type = event.get("type")
                            if event_type == "gameFull":
                                initial_fen = str(event.get("initialFen") or "startpos")
                                white = event.get("white") or {}
                                black = event.get("black") or {}
                                white_id = str(white.get("id") or white.get("name") or "").lower()
                                black_id = str(black.get("id") or black.get("name") or "").lower()
                                username = self._username.lower()
                                if white_id == username:
                                    bot_color = chess.WHITE
                                elif black_id == username:
                                    bot_color = chess.BLACK
                                else:
                                    raise RuntimeError(f"Bot account {self._username} is not a player in game {game_id}.")
                                state = event.get("state") or {}
                            elif event_type == "gameState":
                                if bot_color is None:
                                    continue
                                state = event
                            else:
                                continue

                            status = str(state.get("status") or "started")
                            if status not in ACTIVE_STATUSES:
                                finished = True
                                break
                            self._maybe_accept_takeback(game_id, state, bot_color)
                            self._maybe_move(game_id, initial_fen, state, bot_color)
                    if not finished and not self._stop.is_set():
                        raise RuntimeError("Game stream ended unexpectedly.")
                except Exception as exc:
                    if self._stop.is_set() or finished:
                        break
                    with self._lock:
                        self._last_error = f"Game {game_id}: {exc}"
                    if self._stop.wait(backoff):
                        return
                    backoff = min(8.0, backoff * 1.8)
        finally:
            self._clear_game_state(game_id)
            with self._lock:
                self._game_threads.pop(game_id, None)

    def _maybe_accept_takeback(self, game_id: str, state: dict[str, Any], bot_color: chess.Color) -> None:
        # Lichess names the request flags by the side asking for the takeback.
        opponent_requested = bool(state.get("btakeback")) if bot_color == chess.WHITE else bool(state.get("wtakeback"))
        if not opponent_requested:
            return
        ply = len(str(state.get("moves") or "").split())
        signature = (game_id, ply)
        with self._lock:
            if signature in self._takeback_seen:
                return
            self._takeback_seen.add(signature)
        try:
            self._request("POST", f"/api/bot/game/{game_id}/takeback/yes", timeout=10)
        except Exception:
            with self._lock:
                self._takeback_seen.discard(signature)
            raise

    def _maybe_move(
        self,
        game_id: str,
        initial_fen: str,
        state: dict[str, Any],
        bot_color: chess.Color,
    ) -> None:
        if str(state.get("status") or "started") not in ACTIVE_STATUSES:
            return
        board = self._board_from_state(initial_fen, str(state.get("moves") or ""))
        if board.is_game_over() or board.turn != bot_color:
            return
        ply = board.ply()
        with self._lock:
            if self._submitted_ply.get(game_id) == ply:
                return
            self._submitted_ply[game_id] = ply
            level = BOT_LEVELS[self._level_id]
        try:
            move, elapsed_ms = self._engine.choose_move(board, level)
            self._request("POST", f"/api/bot/game/{game_id}/move/{move.uci()}", timeout=10)
            with self._lock:
                self._last_move_ms = elapsed_ms
                # Do not leave a stale reconnect warning visible after a move succeeds.
                self._last_error = ""
        except Exception:
            with self._lock:
                self._submitted_ply.pop(game_id, None)
            raise


runtime = LichessBotRuntime()