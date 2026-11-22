"""Read-only game snapshot for the dog's MCP bridge, and the route that serves it.

All robot I/O is replaced with test doubles. Nothing here moves a robot or makes a move.
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import app
from bot_runtime import LichessBotRuntime
from tablet_access import TabletAccess, TABLET_HEADER, TABLET_ORIGIN
from vbot_demo import VbotDemo
from vbot_game_context import CONTEXT_HEADER, ContextAccess, game_snapshot

CONTEXT_TOKEN = 'ctx_' + 'c' * 40
TABLET_TOKEN = 'tab_' + 't' * 40
DOCKER_GATEWAY = '192.168.65.1'


def cached_game(moves='e2e4 e7e5 g1f3', status='started', game_id='g1', **extra):
    return {'gameId': game_id, 'botColor': 'black', 'rated': False, 'initialFen': 'startpos',
            'players': {'white': 'Rich', 'black': 'CoachBot'}, 'updatedAt': 123,
            'state': {'moves': moves, 'status': status, 'wtime': 60000, 'btime': 60000}, **extra}


class SnapshotTests(unittest.TestCase):
    def demo(self, game_id='g1'):
        demo = VbotDemo(clock=lambda: 1000.0, verification={}, sender=Mock(), checker=Mock())
        demo.game_id, demo.target = game_id, 'vbot@10.0.0.9'
        return demo

    def test_connected_game_reports_position_last_move_players_and_side_to_move(self):
        snap = game_snapshot(self.demo(), {'g1': cached_game()}.get)
        game = snap['game']
        self.assertEqual(snap['source'], 'dog')
        self.assertTrue(game['live'])
        self.assertEqual(game['fen'], 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2')
        self.assertEqual(game['sideToMove'], 'black')
        self.assertEqual(game['lastMove'], {'uci': 'g1f3', 'san': 'Nf3', 'by': 'white'})
        self.assertEqual((game['humanColor'], game['botColor']), ('white', 'black'))
        self.assertEqual(game['players'], {'white': 'Rich', 'black': 'CoachBot'})
        self.assertIsNone(snap['note'])

    def test_latest_review_is_the_newest_record_for_this_game_only(self):
        demo = self.demo()
        demo.remember({'recordId': 'a', 'gameId': 'g1', 'ply': 1, 'playerColor': 'white', 'playedMove': 'e4',
                       'classification': 'best', 'centipawnLoss': 0, 'bestMove': 'e4', 'fenBefore': 'x'})
        demo.remember({'recordId': 'b', 'gameId': 'g1', 'ply': 3, 'playerColor': 'white', 'playedMove': 'Nf3',
                       'classification': 'good', 'centipawnLoss': 12, 'bestMove': 'Nc3'})
        demo.remember({'recordId': 'c', 'gameId': 'other', 'ply': 9, 'playedMove': 'Qh5', 'classification': 'blunder'})
        review = game_snapshot(demo, {'g1': cached_game()}.get)['latestReview']
        self.assertEqual(review, {'ply': 3, 'playerColor': 'white', 'playedMove': 'Nf3', 'classification': 'good',
                                  'centipawnLoss': 12, 'bestMove': 'Nc3'})

    def test_no_game_is_a_normal_result(self):
        snap = game_snapshot(self.demo(game_id=''), lambda _: None)
        self.assertTrue(snap['available'])
        self.assertIsNone(snap['game'])
        self.assertIn('No chess game', snap['note'])

    def test_without_a_connected_game_it_falls_back_to_the_bots_latest_game(self):
        snap = game_snapshot(self.demo(game_id=''), {'g1': cached_game(status='mate')}.get, lambda: 'g1')
        self.assertEqual(snap['source'], 'bot')
        self.assertFalse(snap['game']['live'])
        self.assertIn('most recent game', snap['note'])

    def test_practice_uncached_and_corrupt_games_are_explained_not_raised(self):
        demo = self.demo(game_id='CAPTURE1')
        demo.session_kind, demo.armed = 'capture-practice', True
        self.assertIn('active capture-practice session', game_snapshot(demo, lambda _: None)['note'])
        self.assertIn('not in the coach bot cache', game_snapshot(self.demo(), lambda _: None)['note'])
        broken = game_snapshot(self.demo(), {'g1': cached_game(moves='e2e4 e2e4')}.get)
        self.assertIsNone(broken['game'])
        self.assertIn('could not be replayed', broken['note'])

    def test_a_finished_practice_or_performance_does_not_hide_the_bots_game(self):
        for kind, game_id in (('capture-practice', 'CAPTURE1'), ('performance', '')):
            demo = self.demo(game_id=game_id)
            demo.session_kind, demo.armed = kind, False
            snap = game_snapshot(demo, {'g1': cached_game()}.get, lambda: 'g1')
            self.assertEqual((snap['session'], snap['source'], snap['game']['gameId']), ('game', 'bot', 'g1'))

    def test_reading_changes_nothing_and_leaves_out_robot_details(self):
        demo = self.demo()
        demo.armed, demo.mode = True, 'live'
        demo._event('armed', mode='live')
        before = (demo.operator_seen, demo.generation, demo.armed, demo.game_id, len(demo.events))
        with patch.object(demo, 'status', side_effect=AssertionError('status() touches network state')), \
             patch.object(demo, 'touch_operator', side_effect=AssertionError('fake operator presence')):
            snap = game_snapshot(demo, {'g1': cached_game()}.get)
        self.assertEqual(before, (demo.operator_seen, demo.generation, demo.armed, demo.game_id, len(demo.events)))
        self.assertEqual(snap['reactions'], 'live')
        raw = json.dumps(snap)
        for secret in ('10.0.0.9', 'vbot@', 'events', 'target', 'token'):
            self.assertNotIn(secret, raw)

    def test_long_player_names_are_cut(self):
        game = cached_game(players={'white': 'x' * 500, 'black': None})
        players = game_snapshot(self.demo(), {'g1': game}.get)['game']['players']
        self.assertEqual((len(players['white']), players['black']), (40, None))


class ContextAccessTests(unittest.TestCase):
    def test_needs_a_long_token_the_exact_value_and_no_browser_origin(self):
        self.assertFalse(ContextAccess('short').authorized('short'))
        self.assertFalse(ContextAccess('').authorized(''))
        access = ContextAccess(CONTEXT_TOKEN)
        self.assertTrue(access.authorized(CONTEXT_TOKEN))
        self.assertFalse(access.authorized(CONTEXT_TOKEN[:-1] + 'x'))
        self.assertFalse(access.authorized(CONTEXT_TOKEN, origin='https://localhost'))
        self.assertFalse(access.authorized(None))


class RouteTests(unittest.TestCase):
    """Requests reach the container from Docker's private gateway, like the hosted server."""

    def handler(self, headers):
        handler = object.__new__(app.Handler)
        handler.client_address = (DOCKER_GATEWAY, 40000)
        handler.server = SimpleNamespace(server_port=8765)
        handler.headers = {'Host': 'chess-api.example', **headers}
        handler.path = '/api/vbot/game-context'
        handler._send = Mock()
        return handler

    def gates(self, context=CONTEXT_TOKEN):
        return (patch.object(app, 'context_access', ContextAccess(context)),
                patch.object(app, 'tablet_access', TabletAccess(TABLET_TOKEN, 'https://chess-api.example')))

    def test_context_token_reads_the_snapshot_without_the_pairing_key_or_operator_presence(self):
        ctx, tablet = self.gates()
        with ctx, tablet, patch.object(app, 'vbot_demo') as demo, patch.object(app, 'game_snapshot', return_value={'available': True}) as snapshot:
            handler = self.handler({CONTEXT_HEADER: CONTEXT_TOKEN})
            handler.do_GET()
            handler._send.assert_called_once_with(200, {'available': True})
            snapshot.assert_called_once()
            demo.touch_operator.assert_not_called()
            demo.status.assert_not_called()

    def test_pairing_key_alone_wrong_token_browser_origin_or_unset_token_are_refused(self):
        refused = [
            {TABLET_HEADER: TABLET_TOKEN, 'Origin': TABLET_ORIGIN},
            {CONTEXT_HEADER: 'z' * 44},
            {CONTEXT_HEADER: CONTEXT_TOKEN, 'Origin': TABLET_ORIGIN},
        ]
        ctx, tablet = self.gates()
        with ctx, tablet, patch.object(app, 'game_snapshot') as snapshot:
            for headers in refused:
                handler = self.handler(headers)
                handler.do_GET()
                self.assertEqual(handler._send.call_args.args[0], 403)
            snapshot.assert_not_called()
        ctx, tablet = self.gates(context='')
        with ctx, tablet, patch.object(app, 'game_snapshot') as snapshot:
            handler = self.handler({CONTEXT_HEADER: ''})
            handler.do_GET()
            self.assertEqual(handler._send.call_args.args[0], 403)
            snapshot.assert_not_called()


class RuntimeCacheTests(unittest.TestCase):
    def test_cached_state_carries_player_names_and_the_last_game(self):
        runtime = object.__new__(LichessBotRuntime)
        runtime._lock, runtime._demo_games, runtime._last_game_id = __import__('threading').Lock(), set(), 'g1'
        runtime._game_states = {'g1': {**cached_game(), 'timeControlKnown': True, 'clock': None}}
        state = runtime.game_state('g1')
        self.assertEqual(state['players'], {'white': 'Rich', 'black': 'CoachBot'})
        self.assertEqual(runtime.last_game_id(), 'g1')
        runtime._game_states['g1'].pop('players')
        self.assertIsNone(runtime.game_state('g1')['players'])


if __name__ == '__main__':
    unittest.main()
