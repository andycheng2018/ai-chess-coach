"""Bot account registry and switching rules. Offline: Lichess calls are faked."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import app  # noqa: E402
from bot_accounts import BotAccountStore  # noqa: E402
from bot_runtime import BotAccountBusy, LichessBotRuntime  # noqa: E402

DEFAULT_TOKEN = 'lip_defaultToken1111'
SECOND_TOKEN = 'lip_secondToken2222'
ENV = {'LICHESS_BOT_TOKEN': DEFAULT_TOKEN, 'LICHESS_BOT_USERNAME': 'bot_2435'}


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'bot-accounts'
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)

    def test_existing_env_account_migrates_in_as_selected_default(self):
        store = BotAccountStore(self.directory)
        accounts = store.list_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]['id'], 'default')
        self.assertEqual(accounts[0]['username'], 'bot_2435')
        self.assertTrue(accounts[0]['selected'])
        self.assertEqual(accounts[0]['tokenHint'], '1111')
        self.assertEqual(store.selected().token, DEFAULT_TOKEN)
        # The .env secret is referenced, never copied into the database.
        self.assertNotIn(DEFAULT_TOKEN.encode(), (self.directory / 'accounts.sqlite3').read_bytes())
        self.assertNotIn(DEFAULT_TOKEN, json.dumps(accounts))
        self.assertNotIn(DEFAULT_TOKEN, repr(store.selected()))

    def test_default_store_lives_under_chess_data_home(self):
        with patch.dict(os.environ, {'CHESS_DATA_HOME': self.tmp.name}):
            store = BotAccountStore.open_default()
        self.assertEqual(store.selected_id(), 'default')
        self.assertTrue((Path(self.tmp.name) / 'bot-accounts' / 'accounts.sqlite3').exists())

    def test_saved_token_is_private_and_kept_out_of_the_database(self):
        store = BotAccountStore(self.directory)
        created = store.add(label='Second bot', username='SecondBot', token=SECOND_TOKEN)
        self.assertEqual(created['tokenHint'], '2222')
        self.assertFalse(created['selected'])
        self.assertNotIn(SECOND_TOKEN, json.dumps(store.list_accounts()))
        self.assertNotIn(SECOND_TOKEN.encode(), (self.directory / 'accounts.sqlite3').read_bytes())
        token_file = self.directory / 'tokens' / f"{created['id']}.token"
        self.assertEqual(token_file.read_text(), SECOND_TOKEN)
        self.assertEqual(mode(token_file), 0o600)
        self.assertEqual(mode(self.directory / 'accounts.sqlite3'), 0o600)
        self.assertEqual(mode(self.directory), 0o700)
        # Survives a restart.
        reopened = BotAccountStore(self.directory)
        self.assertEqual(reopened.resolve(created['id']).token, SECOND_TOKEN)
        reopened.select(created['id'])
        self.assertEqual(BotAccountStore(self.directory).selected().username, 'SecondBot')

    def test_env_variable_reference(self):
        store = BotAccountStore(self.directory)
        created = store.add(username='EnvBot', token_env='LICHESS_BOT_TOKEN_2')
        self.assertFalse(created['tokenConfigured'])
        with patch.dict(os.environ, {'LICHESS_BOT_TOKEN_2': 'lip_fromEnvToken9999'}):
            self.assertEqual(store.resolve(created['id']).token, 'lip_fromEnvToken9999')
            self.assertEqual(store.public(created['id'])['tokenHint'], '9999')

    def test_add_rejects_bad_input(self):
        store = BotAccountStore(self.directory)
        for kwargs in [dict(username='', token=SECOND_TOKEN),
                       dict(username='bad name', token=SECOND_TOKEN),
                       dict(username='SecondBot'),
                       dict(username='SecondBot', token=SECOND_TOKEN, token_env='LICHESS_X'),
                       dict(username='SecondBot', token='PASTE_TOKEN_HERE'),
                       dict(username='SecondBot', token='has space in it'),
                       dict(username='SecondBot', token_env='PATH'),
                       dict(username='BOT_2435', token=SECOND_TOKEN)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                store.add(**kwargs)
        self.assertEqual(len(store.list_accounts()), 1)

    def test_remove_deletes_saved_token_and_moves_selection(self):
        store = BotAccountStore(self.directory)
        created = store.add(username='SecondBot', token=SECOND_TOKEN)
        store.select(created['id'])
        store.remove(created['id'])
        self.assertFalse((self.directory / 'tokens' / f"{created['id']}.token").exists())
        self.assertEqual(store.selected_id(), 'default')
        with self.assertRaises(ValueError):
            store.select(created['id'])

    def test_removed_default_is_not_migrated_again(self):
        store = BotAccountStore(self.directory)
        created = store.add(username='SecondBot', token=SECOND_TOKEN)
        store.remove('default')
        self.assertEqual(store.selected_id(), created['id'])
        self.assertEqual([a['id'] for a in BotAccountStore(self.directory).list_accounts()], [created['id']])


class FakeLichess:
    """Answers /api/account per token and records which token each request used."""
    def __init__(self, accounts):
        self.accounts = accounts
        self.calls = []

    def request(self, method, path, *, timeout=12, allow=(200,), account=None):
        self.calls.append((path, account.token if account else None))
        if path == '/api/account':
            return SimpleNamespace(json=lambda: self.accounts[account.token])
        if path == '/api/account/playing':
            return SimpleNamespace(json=lambda: {'nowPlaying': []})
        return SimpleNamespace(status_code=200, json=lambda: {})


class RuntimeSwitchTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        self.store = BotAccountStore()
        self.second = self.store.add(label='Second bot', username='SecondBot', token=SECOND_TOKEN)
        self.runtime = LichessBotRuntime(accounts=self.store)
        self.lichess = FakeLichess({
            DEFAULT_TOKEN: {'username': 'bot_2435', 'title': 'BOT'},
            SECOND_TOKEN: {'username': 'SecondBot', 'title': 'BOT'},
        })
        self.runtime._request = self.lichess.request
        self.runtime._engine = Mock()
        self.loops = []

        def fake_event_loop(session, account):
            self.loops.append((session, account.username))
            with self.runtime._lock:
                self.runtime._connected = True
            while self.runtime._session_is_current(session):
                time.sleep(0.005)

        self.runtime._event_loop = fake_event_loop
        self.addCleanup(self.runtime.stop)

    def fake_game(self, game_id='AbCd1234'):
        finished = threading.Event()
        self.addCleanup(finished.set)
        self.runtime._game_loop = lambda gid: finished.wait(5)
        self.runtime._ensure_game_thread(game_id)
        return finished

    def test_default_account_is_used_with_no_setup(self):
        status = self.runtime.start()
        self.assertTrue(status['connected'])
        self.assertEqual(status['username'], 'bot_2435')
        self.assertEqual(status['accountId'], 'default')
        self.assertEqual(self.runtime._credentials(), (DEFAULT_TOKEN, 'bot_2435'))

    def test_selecting_another_account_restarts_the_stream_with_its_token(self):
        self.runtime.start()
        first_thread = self.runtime._event_thread
        result = self.runtime.select_account(self.second['id'])
        self.assertEqual(result['bot']['username'], 'SecondBot')
        self.assertEqual(result['activeId'], self.second['id'])
        self.assertEqual(self.runtime._credentials(), (SECOND_TOKEN, 'SecondBot'))
        self.assertEqual([name for _, name in self.loops], ['bot_2435', 'SecondBot'])
        first_thread.join(1)
        self.assertFalse(first_thread.is_alive(), 'the previous event stream must retire')
        self.assertNotIn(SECOND_TOKEN, json.dumps(result))
        # A new game challenges and is played by the selected account.
        self.fake_game('NewGame1')
        self.assertEqual(self.runtime._game_account('NewGame1').token, SECOND_TOKEN)

    def test_switch_is_refused_while_a_game_is_running(self):
        self.runtime.start()
        finished = self.fake_game()
        with self.assertRaises(BotAccountBusy):
            self.runtime.select_account(self.second['id'])
        with self.assertRaises(BotAccountBusy):
            self.runtime.remove_account('default')
        self.assertEqual(self.store.selected_id(), 'default')
        self.assertEqual(self.runtime._credentials()[0], DEFAULT_TOKEN)
        payload = self.runtime.accounts_payload()
        self.assertTrue(payload['locked'])
        # Once the game ends the switch goes through.
        finished.set()
        self.runtime._game_threads['AbCd1234'].join(1)
        self.assertEqual(self.runtime.select_account(self.second['id'])['bot']['username'], 'SecondBot')

    def test_game_keeps_its_own_token_for_moves(self):
        self.runtime.start()
        self.fake_game()
        engine = Mock()
        engine.choose_move.return_value = (chess.Move.from_uci('e2e4'), 1)
        self.runtime._engine = engine
        # Even if the selection changed underneath (e.g. another client), the
        # game in progress keeps answering with the account that started it.
        self.store.select(self.second['id'])
        self.runtime._maybe_move('AbCd1234', 'startpos', {'status': 'started', 'moves': ''}, chess.WHITE)
        self.assertEqual(self.lichess.calls[-1], ('/api/bot/game/AbCd1234/move/e2e4', DEFAULT_TOKEN))
        self.assertTrue(self.runtime.status()['accountPending'])
        # A start request during the game does not move it to the new token.
        self.assertEqual(self.runtime.start()['username'], 'bot_2435')

    def test_failed_switch_keeps_the_previous_account(self):
        self.lichess.accounts[SECOND_TOKEN] = {'username': 'SecondBot'}  # not a BOT title
        self.runtime.start()
        with self.assertRaisesRegex(RuntimeError, 'not a Lichess BOT account'):
            self.runtime.select_account(self.second['id'])
        self.assertEqual(self.store.selected_id(), 'default')
        status = self.runtime.status()
        self.assertTrue(status['running'])
        self.assertEqual(status['username'], 'bot_2435')

    def test_failed_first_switch_does_not_leave_a_stale_error(self):
        self.lichess.accounts[SECOND_TOKEN] = {'username': 'SecondBot'}
        with self.assertRaises(RuntimeError):
            self.runtime.select_account(self.second['id'])
        self.assertEqual(self.store.selected_id(), 'default')
        self.assertIsNone(self.runtime.status()['error'])

    def test_mismatched_username_is_rejected(self):
        self.lichess.accounts[SECOND_TOKEN] = {'username': 'SomeoneElse', 'title': 'BOT'}
        with self.assertRaisesRegex(RuntimeError, 'belongs to SomeoneElse'):
            self.runtime.select_account(self.second['id'])

    def test_add_and_select_in_one_step(self):
        self.runtime.start()
        third_token = 'lip_thirdToken3333'
        self.lichess.accounts[third_token] = {'username': 'ThirdBot', 'title': 'BOT'}
        result = self.runtime.add_account({'username': 'ThirdBot', 'token': third_token, 'select': True})
        self.assertEqual(result['bot']['username'], 'ThirdBot')
        self.assertNotIn(third_token, json.dumps(result))

    def test_removing_the_active_account_moves_to_the_next(self):
        self.runtime.select_account(self.second['id'])
        result = self.runtime.remove_account(self.second['id'])
        self.assertEqual(result['bot']['username'], 'bot_2435')
        self.assertEqual(self.runtime._credentials()[0], DEFAULT_TOKEN)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        self.runtime = LichessBotRuntime(accounts=BotAccountStore())
        patcher = patch.object(app, 'runtime', self.runtime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def handler(self, path, body=None, local=True):
        handler = object.__new__(app.Handler)
        handler.path = path
        handler.headers = {'Content-Type': 'application/json'}
        handler._tablet_api_denied = lambda: False
        handler._vbot_local_request = lambda: local
        handler._json_body = lambda: body or {}
        handler._send = Mock()
        return handler

    def sent(self, handler):
        status, payload = handler._send.call_args.args
        return status, payload

    def test_listing_never_contains_tokens(self):
        handler = self.handler('/api/bot/accounts')
        handler.do_GET()
        status, payload = self.sent(handler)
        self.assertEqual(status, 200)
        self.assertTrue(payload['canManage'])
        self.assertNotIn(DEFAULT_TOKEN, json.dumps(payload))

    def test_remote_listing_hides_token_hints(self):
        handler = self.handler('/api/bot/accounts', local=False)
        handler.do_GET()
        status, payload = self.sent(handler)
        self.assertEqual(status, 200)
        self.assertFalse(payload['canManage'])
        self.assertEqual([(a['tokenHint'], a['tokenEnv']) for a in payload['accounts']], [('', None)])

    def test_remote_clients_cannot_change_accounts(self):
        for path in ('/api/bot/accounts', '/api/bot/accounts/select', '/api/bot/accounts/remove'):
            handler = self.handler(path, {'id': 'default', 'username': 'X1', 'token': SECOND_TOKEN}, local=False)
            handler.do_POST()
            self.assertEqual(self.sent(handler)[0], 403)
        self.assertEqual(len(self.runtime.accounts().list_accounts()), 1)

    def test_add_returns_masked_account(self):
        handler = self.handler('/api/bot/accounts', {'username': 'SecondBot', 'token': SECOND_TOKEN})
        handler.do_POST()
        status, payload = self.sent(handler)
        self.assertEqual(status, 200)
        self.assertNotIn(SECOND_TOKEN, json.dumps(payload))
        self.assertEqual([a['tokenHint'] for a in payload['accounts']], ['1111', '2222'])

    def test_switch_during_game_is_409(self):
        self.runtime.select_account = Mock(side_effect=BotAccountBusy('Finish the current game before switching bot accounts.'))
        handler = self.handler('/api/bot/accounts/select', {'id': 'default'})
        handler.do_POST()
        self.assertEqual(self.sent(handler)[0], 409)

    def test_bad_input_is_400(self):
        handler = self.handler('/api/bot/accounts', {'username': 'SecondBot'})
        handler.do_POST()
        self.assertEqual(self.sent(handler)[0], 400)


if __name__ == '__main__':
    unittest.main()
