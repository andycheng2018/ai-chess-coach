"""Read-only Chess Buddy game snapshot for the dog's MCP bridge (vbot-mcp/qwen-bridge).

The bridge runs on the Mac Studio host and the chess server runs in Docker, so the
container cannot tell the bridge apart from the public tunnel: both arrive from a private
proxy address. The route that serves this snapshot is therefore treated as public and
gated by its own token (CHESS_CONTEXT_TOKEN), never the tablet pairing key, which
authorizes robot controls.

Reading the snapshot changes nothing: no move, no motion, no operator check-in (it never
calls VbotDemo.status() or touch_operator(), which would keep the motion timeout alive)
and no engine work. It leaves out robot addresses, events, accounts and tokens.
"""
from __future__ import annotations

import secrets

import chess

CONTEXT_HEADER = 'X-Chess-Buddy-Context-Token'
MIN_TOKEN_LENGTH = 40
ACTIVE_STATUSES = {'created', 'started'}
NAME_CHARS = 40
REVIEW_FIELDS = ('ply', 'playerColor', 'playedMove', 'classification', 'centipawnLoss', 'bestMove')


class ContextAccess:
    """Separate, read-only credential for the game snapshot. Off unless a long token is set."""

    def __init__(self, token=''):
        self.token = str(token or '')

    @property
    def enabled(self):
        return len(self.token) >= MIN_TOKEN_LENGTH

    def authorized(self, token, origin=''):
        # Browsers have no business here; the bridge is a server-side client.
        return bool(self.enabled and not origin and isinstance(token, str)
                    and secrets.compare_digest(token.encode(), self.token.encode()))


def _name(value):
    return str(value or '')[:NAME_CHARS] or None


def _board(initial_fen, moves):
    board = chess.Board() if not initial_fen or initial_fen == 'startpos' else chess.Board(initial_fen)
    for uci in moves:
        board.push_uci(uci)
    return board


def _position(game):
    """FEN, side to move and last move from a cached bot-runtime game."""
    state = game.get('state') or {}
    moves = str(state.get('moves') or '').split()
    board = _board(game.get('initialFen'), moves)
    last = None
    if moves:
        move = board.pop()
        last = {'uci': move.uci(), 'san': board.san(move), 'by': 'white' if board.turn else 'black'}
        board.push(move)
    status = str(state.get('status') or 'started')
    bot = game.get('botColor') if game.get('botColor') in {'white', 'black'} else None
    players = game.get('players') if isinstance(game.get('players'), dict) else {}
    return {
        'gameId': game.get('gameId'),
        'status': status,
        'live': status in ACTIVE_STATUSES,
        'fen': board.fen(),
        'sideToMove': 'white' if board.turn else 'black',
        'moveNumber': board.fullmove_number,
        'plies': len(moves),
        'lastMove': last,
        'inCheck': board.is_check(),
        'botColor': bot,
        'humanColor': {'white': 'black', 'black': 'white'}.get(bot),
        'players': {'white': _name(players.get('white')), 'black': _name(players.get('black'))},
        'winner': state.get('winner') if state.get('winner') in {'white', 'black'} else None,
        'rated': game.get('rated') if isinstance(game.get('rated'), bool) else None,
        'updatedAt': game.get('updatedAt'),
    }


def _latest_review(demo, game_id):
    """Newest engine review the server already computed for this game (no new engine work)."""
    newest = None
    for _, record in reversed(list(demo.records.values())):
        if record.get('gameId') == game_id:
            newest = record
            break
    if newest is None:
        return None
    review = {key: newest.get(key) for key in REVIEW_FIELDS}
    review['playedMove'] = _name(review['playedMove'])
    review['bestMove'] = _name(review['bestMove'])
    if not isinstance(review['centipawnLoss'], (int, float)):
        review['centipawnLoss'] = None
    return review


def game_snapshot(demo, game_reader, last_game_id=lambda: None):
    """What the dog's game looks like right now. Every outcome, including no game, is a result."""
    with demo.lock:
        game_id = demo.game_id
        session = demo.session_kind
        armed = demo.armed
        reactions = demo.mode if armed else 'off'
    if session != 'game' and not armed:
        # A finished practice or performance leaves its kind behind; it is not the current activity.
        session, game_id = 'game', ''
    source = 'dog'
    if not game_id:
        game_id, source = last_game_id() or '', 'bot'
    with demo.lock:
        review = _latest_review(demo, game_id) if game_id else None
    snapshot = {'available': True, 'session': session, 'reactions': reactions, 'source': source,
                'game': None, 'latestReview': review, 'note': None}
    if session != 'game':
        snapshot['note'] = f'The dog is in an active {session} session, not a chess game.'
        return snapshot
    if not game_id:
        snapshot['note'] = 'No chess game is connected to the dog and the coach bot has not played a game.'
        return snapshot
    game = game_reader(game_id)
    if not game:
        snapshot['note'] = 'The connected game is not in the coach bot cache (the bot may be off or the game is over).'
        return snapshot
    try:
        snapshot['game'] = _position(game)
    except (ValueError, AssertionError):
        snapshot['note'] = 'The cached game has a move list that could not be replayed.'
        return snapshot
    if source == 'bot':
        snapshot['note'] = "No game is connected to the dog; this is the coach bot's most recent game."
    elif not snapshot['game']['live']:
        snapshot['note'] = 'The game is over.'
    return snapshot
