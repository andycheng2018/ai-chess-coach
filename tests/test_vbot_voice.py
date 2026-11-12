"""Qwen voice mode. The session, Qwen and the dog are replaced; nothing here reaches a robot."""
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'vbot-demo'))
import robot_voice
from robot_voice import VoiceGate
import vbot_voice
from vbot_voice import VoiceMode


class GateTests(unittest.TestCase):
    def test_nothing_counts_before_the_wake_word(self):
        self.assertEqual(VoiceGate().decide('are you a dog', 100), 'no_wake')

    def test_recorded_session_after_a_wake_word(self):
        # Timings from the live test: wake at 10.5, chime to 11.2, first sentence at 20.9.
        gate = VoiceGate()
        gate.on_wake(10.5); gate.on_speech_start(10.6); gate.on_speech_end(11.2)
        self.assertEqual(gate.decide('Now you have the weight that you hear me', 20.9), 'accept')

    def test_the_window_closes_so_the_room_is_not_answered(self):
        gate = VoiceGate(); gate.on_wake(0)
        self.assertEqual(gate.decide('talking to someone else', robot_voice.LISTEN_SECONDS + 1), 'no_wake')

    def test_a_reply_reopens_the_window_for_a_follow_up(self):
        gate = VoiceGate(); gate.on_wake(0)
        gate.before_speaking('Did you ask about my dances?', 30); gate.on_speech_start(30); gate.on_speech_end(33)
        self.assertEqual(gate.decide('yes the dances', 40), 'accept')

    def test_the_dog_ignores_itself(self):
        gate = VoiceGate(); gate.on_wake(0)
        gate.before_speaking('Dogs wag their tails to show how they feel', 1); gate.on_speech_start(1)
        self.assertEqual(gate.decide('dogs wag', 2), 'dog_speaking')
        gate.on_speech_end(5)
        self.assertEqual(gate.decide('dogs wag their tails to show how they feel', 5.1), 'dog_speaking')
        self.assertEqual(gate.decide('dogs wag their tail to show how they feel', 6), 'echo')
        self.assertEqual(gate.decide('what is your favorite food', 7), 'accept')

    def test_a_lost_end_of_speech_event_does_not_deafen_it(self):
        gate = VoiceGate(); gate.on_wake(100); gate.on_speech_start(100); gate.window_until = 1000
        self.assertEqual(gate.decide('hello', 100 + robot_voice.MAX_SPEAKING_SECONDS + 1), 'accept')


class ChatTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)

    def test_off_then_restored_and_marker_removed(self):
        states = [True, False, True]
        with patch.object(robot_voice, 'speech_control', side_effect=states) as call:
            chat = robot_voice.Chat(self.directory); chat.turn_off()
            self.assertTrue(chat.marker.exists())
            self.assertTrue(chat.restore())
        self.assertEqual(call.call_args_list[-1].args, (robot_voice.REQUEST_SET_CHAT, True))
        self.assertFalse(chat.marker.exists())

    def test_a_crashed_session_does_not_lose_the_original_setting(self):
        (self.directory / 'voice-original.json').write_text(json.dumps({'chat': True}))
        with patch.object(robot_voice, 'speech_control', side_effect=[False, True]) as call:
            chat = robot_voice.Chat(self.directory); chat.turn_off(); chat.restore()
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[-1].args, (robot_voice.REQUEST_SET_CHAT, True))

    def test_failed_restore_is_reported_and_marker_kept(self):
        with patch.object(robot_voice, 'speech_control', side_effect=[True, False, RuntimeError()]):
            chat = robot_voice.Chat(self.directory); chat.turn_off()
            self.assertFalse(chat.restore())
        self.assertTrue(chat.marker.exists())


class SpeakingTests(unittest.TestCase):
    def test_speech_never_waits_on_the_motion_lock(self):
        source = (ROOT / 'vbot-demo' / 'robot_speak.py').read_text()
        self.assertNotIn('fcntl', source)

    def test_a_failed_reply_does_not_end_the_session(self):
        session = robot_voice.Session(Path('.'), 'x')
        session.emit = Mock()
        with patch.object(robot_voice.robot_speak, 'speak', side_effect=RuntimeError('no speaker')):
            session.say(None, {'id': 'a', 'text': 'hello'})
        self.assertFalse(session.emit.call_args.kwargs['ok'])
        self.assertFalse(session.gate.own_speech_pending)


class SessionFrameTests(unittest.TestCase):
    def run_frames(self, data):
        read, write = os.pipe()
        os.write(write, data); os.close(write)
        session = robot_voice.Session(Path('.'), 'x')
        session.say = Mock()
        reason = session.serve(None, read)
        os.close(read)
        return reason, session.say.call_count

    def test_frames_arriving_together_are_all_handled(self):
        data = b'{"op":"say","text":"a"}\n{"op":"say","text":"b"}\n{"op":"close"}\n'
        self.assertEqual(self.run_frames(data), ('closed', 2))

    def test_a_lost_link_ends_the_session(self):
        self.assertEqual(self.run_frames(b'')[0], 'link_closed')


def demo(**overrides):
    values = dict(target='vbot-remote', network_book=None, armed=False, busy=False)
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeProcess:
    def __init__(self, events):
        self.written = []
        self.lines = queue.Queue()
        for event in events:
            self.lines.put(json.dumps(event) + '\n')
        self.stdout = iter(self.lines.get, None)
        self.stderr = iter(())
        self.stdin = SimpleNamespace(write=self.on_write, flush=lambda: None)

    def on_write(self, line):
        frame = json.loads(line)
        self.written.append(frame)
        if frame['op'] == 'close':
            self.lines.put(json.dumps({'event': 'closed', 'chatRestored': True}) + '\n')
            self.lines.put(None)

    def wait(self):
        return 0

    def terminate(self):
        self.lines.put(None)


@patch.dict(os.environ, {'LLM_PROVIDER': 'qwen', 'CHESS_ANDROID': '0'})
class VoiceModeTests(unittest.TestCase):
    def make(self, process, ask=None, **robot):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        ask = ask or Mock(return_value={'understood': 'Are you a dog?', 'clarifying': False, 'reply': 'I am a robot dog.'})
        mode = VoiceMode(demo(**robot), data_home=folder.name, ask=ask, popen=Mock(return_value=process))
        return mode, ask

    def wait_for(self, check):
        event = threading.Event()
        for _ in range(100):
            if check():
                return
            event.wait(0.05)
        self.fail('condition never became true')

    def test_heard_speech_gets_a_spoken_answer_and_clean_shutdown(self):
        process = FakeProcess([{'event': 'ready'}, {'event': 'heard', 'text': 'are you a dog', 'rejected': False}])
        mode, ask = self.make(process)
        with patch.object(vbot_voice, 'JOIN_SECONDS', 0.01):
            mode.set_enabled(True)
            self.wait_for(lambda: any(f['op'] == 'say' for f in process.written))
            self.assertEqual(next(f for f in process.written if f['op'] == 'say')['text'], 'I am a robot dog.')
            self.assertEqual(mode.status()['turns'][0]['heard'], 'are you a dog')
            status = mode.set_enabled(False)
        self.assertEqual(status['state'], 'off')
        self.assertTrue(status['chatRestored'])

    def test_rejected_speech_is_still_answered(self):
        process = FakeProcess([{'event': 'ready'}, {'event': 'heard', 'text': 'and i you understand me', 'rejected': True}])
        ask = Mock(return_value={'understood': '', 'clarifying': True, 'reply': 'Did you ask if I understand you?'})
        mode, _ = self.make(process, ask)
        with patch.object(vbot_voice, 'JOIN_SECONDS', 0.01):
            mode.set_enabled(True)
            self.wait_for(lambda: any(f['op'] == 'say' for f in process.written))
            self.assertTrue(ask.call_args.args[2])
            self.assertTrue(mode.status()['turns'][0]['clarifying'])
            mode.set_enabled(False)

    def test_split_sentences_become_one_question(self):
        process = FakeProcess([{'event': 'ready'}, {'event': 'heard', 'text': 'what is it like', 'rejected': False},
                               {'event': 'heard', 'text': 'to be a robot', 'rejected': False}])
        mode, ask = self.make(process)
        with patch.object(vbot_voice, 'JOIN_SECONDS', 0.2):
            mode.set_enabled(True)
            self.wait_for(lambda: ask.called)
            self.assertEqual(ask.call_args.args[1], 'what is it like to be a robot')
            mode.set_enabled(False)

    def test_qwen_failure_still_says_something(self):
        process = FakeProcess([{'event': 'ready'}, {'event': 'heard', 'text': 'hello', 'rejected': False}])
        mode, _ = self.make(process, Mock(side_effect=RuntimeError('down')))
        with patch.object(vbot_voice, 'JOIN_SECONDS', 0.01):
            mode.set_enabled(True)
            self.wait_for(lambda: any(f['op'] == 'say' for f in process.written))
            self.assertEqual(next(f for f in process.written if f['op'] == 'say')['text'], vbot_voice.FALLBACK_REPLY)
            mode.set_enabled(False)

    def test_a_qwen_failure_stays_visible_after_a_speech_failure(self):
        process = FakeProcess([{'event': 'ready'}, {'event': 'heard', 'text': 'hello', 'rejected': False}])
        mode, _ = self.make(process, Mock(side_effect=RuntimeError('down')))
        with patch.object(vbot_voice, 'JOIN_SECONDS', 0.01):
            mode.set_enabled(True)
            self.wait_for(lambda: any(f['op'] == 'say' for f in process.written))
            say = next(f for f in process.written if f['op'] == 'say')
            mode._on_event({'event': 'said', 'id': say['id'], 'ok': False, 'reason': 'Speaker unavailable'})
            error = mode.status()['turns'][0]['error']
            mode.set_enabled(False)
        self.assertIn('Qwen did not answer', error)
        self.assertIn('Speaker unavailable', error)

    def test_paused_during_reactions(self):
        process = FakeProcess([{'event': 'ready'}, {'event': 'heard', 'text': 'hello', 'rejected': False}])
        mode, ask = self.make(process, armed=True)
        with patch.object(vbot_voice, 'JOIN_SECONDS', 0.01):
            mode.set_enabled(True)
            self.wait_for(lambda: mode.status()['turns'])
            ask.assert_not_called()
            mode.set_enabled(False)

    def test_the_setting_survives_a_restart(self):
        process = FakeProcess([{'event': 'ready'}])
        mode, _ = self.make(process)
        mode.set_enabled(True)
        self.wait_for(lambda: mode.status()['state'] == 'listening')
        again = VoiceMode(demo(), data_home=mode.path.parent, ask=Mock(), popen=Mock(return_value=FakeProcess([{'event': 'ready'}])))
        again.resume()
        self.assertTrue(again.status()['enabled'])
        again.set_enabled(False)
        mode.set_enabled(False)

    def test_can_be_turned_back_on(self):
        first, second = FakeProcess([{'event': 'ready'}]), FakeProcess([{'event': 'ready'}, {'event': 'heard', 'text': 'hi', 'rejected': False}])
        mode, ask = self.make(first)
        mode.popen = Mock(side_effect=[first, second])
        with patch.object(vbot_voice, 'JOIN_SECONDS', 0.01):
            mode.set_enabled(True)
            self.wait_for(lambda: mode.status()['state'] == 'listening')
            mode.set_enabled(False)
            mode.set_enabled(True)
            self.wait_for(lambda: ask.called)
            mode.set_enabled(False)

    def answered_turn(self, mode, text):
        return mode._run_turn(text, False)

    def test_qwen_keeps_the_thread_however_long_the_gap(self):
        mode, ask = self.make(FakeProcess([]))
        self.answered_turn(mode, 'my name is Zack')
        with patch.object(vbot_voice.time, 'monotonic', return_value=10**7):
            self.answered_turn(mode, 'what is my name')
        history = ask.call_args.args[0]
        self.assertEqual(history[0]['content'], 'They said: "my name is Zack"')

    def test_a_session_survives_a_server_restart(self):
        mode, _ = self.make(FakeProcess([]))
        self.answered_turn(mode, 'remember the blue ball')
        ask = Mock(return_value={'understood': '', 'clarifying': False, 'reply': 'ok'})
        again = VoiceMode(demo(), data_home=mode.path.parent, ask=ask)
        self.assertEqual(again.active_id, mode.active_id)
        again._run_turn('what should you remember', False)
        self.assertIn('blue ball', ask.call_args.args[0][0]['content'])

    def test_new_session_starts_clean_and_old_one_can_be_continued(self):
        mode, ask = self.make(FakeProcess([]))
        self.answered_turn(mode, 'first topic')
        first = mode.active_id
        status = mode.new_session()
        second = status['activeSession']
        self.assertNotEqual(first, second)
        self.assertEqual(status['turns'], [])
        self.answered_turn(mode, 'second topic')
        self.assertEqual(ask.call_args.args[0], [])
        status = mode.continue_session(first)
        self.assertEqual(status['activeSession'], first)
        self.assertEqual({item['title'] for item in status['sessions']}, {'first topic', 'second topic'})
        self.answered_turn(mode, 'back to the first')
        self.assertIn('first topic', ask.call_args.args[0][0]['content'])

    def test_the_chosen_session_is_remembered_after_a_restart(self):
        mode, _ = self.make(FakeProcess([]))
        self.answered_turn(mode, 'one'); first = mode.active_id
        mode.new_session(); self.answered_turn(mode, 'two')
        mode.continue_session(first)
        self.assertEqual(VoiceMode(demo(), data_home=mode.path.parent, ask=Mock()).active_id, first)

    def test_repeated_new_session_does_not_pile_up_empty_ones(self):
        mode, _ = self.make(FakeProcess([]))
        mode.new_session(); mode.new_session()
        self.assertEqual(len(mode.status()['sessions']), 1)

    def test_unknown_session_is_refused(self):
        mode, _ = self.make(FakeProcess([]))
        with self.assertRaises(ValueError):
            mode.continue_session('../../etc/passwd')

    def test_failed_turns_are_not_fed_back_to_qwen(self):
        ask = Mock(side_effect=[RuntimeError('down'), {'understood': '', 'clarifying': False, 'reply': 'ok'}])
        mode, _ = self.make(FakeProcess([]), ask)
        mode._run_turn('first', False); mode._run_turn('second', False)
        self.assertEqual(ask.call_args.args[0], [])

    def test_context_is_bounded_but_keeps_the_newest(self):
        mode, ask = self.make(FakeProcess([]))
        with patch.object(vbot_voice, 'CONTEXT_CHARS', 80):
            for number in range(10):
                self.answered_turn(mode, f'message number {number}')
        history = ask.call_args.args[0]
        self.assertLess(len(history), 18)
        self.assertIn('number 8', history[-2]['content'])

    def test_session_files_are_private(self):
        mode, _ = self.make(FakeProcess([]))
        self.answered_turn(mode, 'secret')
        path = mode.session_dir / f'{mode.active_id}.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_a_damaged_session_file_does_not_lose_the_rest(self):
        mode, _ = self.make(FakeProcess([]))
        self.answered_turn(mode, 'keep me')
        (mode.session_dir / ('b' * 32 + '.json')).write_text('not json')
        again = VoiceMode(demo(), data_home=mode.path.parent, ask=Mock())
        self.assertEqual(len(again.status()['sessions']), 1)

    @patch.object(vbot_voice, 'say_once', return_value={'ok': True})
    def test_typed_message_joins_the_session_and_is_spoken(self, say):
        mode, ask = self.make(FakeProcess([]))
        self.answered_turn(mode, 'we talked about dances')
        status = mode.send_typed({'text': 'and which one is best'})
        self.assertEqual(ask.call_args.kwargs['typed'], True)
        self.assertIn('dances', ask.call_args.args[0][0]['content'])
        say.assert_called_once()
        self.assertTrue(status['turns'][-1]['spoken'])

    def test_demo_mode_is_off_by_default_and_selectable(self):
        mode, _ = self.make(FakeProcess([]))
        self.assertFalse(mode.status()['demoMode'])
        self.assertTrue(mode.set_demo_mode(True)['demoMode'])
        self.assertTrue(VoiceMode(demo(), data_home=mode.path.parent, ask=Mock()).status()['demoMode'])  # Survives restarts.
        with self.assertRaises(ValueError):
            mode.set_demo_mode('yes')
        with patch.dict(os.environ, {'VBOT_VOICE_DEMO_MODE': '1'}):
            fresh, _ = self.make(FakeProcess([]))
            self.assertTrue(fresh.status()['demoMode'])
            self.assertFalse(fresh.set_demo_mode(False)['demoMode'])  # The saved choice beats the default.

    def test_demo_mode_starts_a_fresh_conversation_after_a_silence(self):
        mode, ask = self.make(FakeProcess([]))
        mode.set_demo_mode(True)
        with patch.object(vbot_voice.time, 'time', return_value=1_000_000):
            self.answered_turn(mode, 'my lucky number is forty-seven')
        first = mode.status()['activeSession']
        with patch.object(vbot_voice.time, 'time', return_value=1_000_000 + vbot_voice.DEMO_IDLE_SECONDS - 5):
            self.answered_turn(mode, 'what is my lucky number')
        self.assertEqual(mode.status()['activeSession'], first)
        self.assertIn('forty-seven', ask.call_args.args[0][0]['content'])
        with patch.object(vbot_voice.time, 'time', return_value=1_000_000 + 3 * vbot_voice.DEMO_IDLE_SECONDS):
            self.answered_turn(mode, 'hi, who are you')
        self.assertNotEqual(mode.status()['activeSession'], first)
        self.assertEqual(ask.call_args.args[0], [])  # The new visitor hears nothing about the last one.
        self.assertEqual(len(mode.status()['sessions']), 2)

    def test_without_demo_mode_a_silence_keeps_the_conversation(self):
        mode, _ = self.make(FakeProcess([]))
        with patch.object(vbot_voice.time, 'time', return_value=1_000_000):
            self.answered_turn(mode, 'hello')
        first = mode.status()['activeSession']
        with patch.object(vbot_voice.time, 'time', return_value=1_000_000 + 10 * vbot_voice.DEMO_IDLE_SECONDS):
            self.answered_turn(mode, 'hello again')
        self.assertEqual(mode.status()['activeSession'], first)

    def test_typed_message_uses_the_open_session_to_the_dog(self):
        process = FakeProcess([{'event': 'ready'}])
        mode, _ = self.make(process)
        mode.set_enabled(True)
        self.wait_for(lambda: mode.status()['state'] == 'listening')
        mode.send_typed({'text': 'hello'})
        self.assertTrue(any(f['op'] == 'say' for f in process.written))
        mode.set_enabled(False)

    def test_typed_message_does_not_talk_over_reactions(self):
        mode, _ = self.make(FakeProcess([]), armed=True)
        with patch.object(vbot_voice, 'say_once') as say:
            status = mode.send_typed({'text': 'hello'})
        say.assert_not_called()
        self.assertFalse(status['turns'][-1]['spoken'])

    def test_dashboard_question_joins_the_session(self):
        mode, ask = self.make(FakeProcess([]))
        self.answered_turn(mode, 'earlier')
        self.assertEqual(mode.ask_only({'question': 'now?'})['answer'], 'I am a robot dog.')
        self.assertIn('earlier', ask.call_args.args[0][0]['content'])

    def test_unavailable_without_qwen(self):
        process = FakeProcess([])
        mode, _ = self.make(process)
        with patch.dict(os.environ, {'LLM_PROVIDER': 'openai'}), self.assertRaises(ValueError):
            mode.set_enabled(True)
        with self.assertRaises(ValueError):
            mode.set_enabled('yes')


class StudioProxyTests(unittest.TestCase):
    def test_unlinked_studio_explains_itself_and_makes_no_request(self):
        import vbot_app_server as studio
        with patch.object(studio, '_cloud_settings', return_value=('', '')), patch('requests.get') as get:
            status, body = studio.cloud_voice()
        self.assertEqual(status, 200)
        self.assertFalse(body['available'])
        get.assert_not_called()

    def test_key_goes_to_the_cloud_only_and_never_back_to_the_page(self):
        import vbot_app_server as studio
        reply = Mock(status_code=200, json=Mock(return_value={'enabled': True}))
        with patch.object(studio, '_cloud_settings', return_value=('https://cloud.example', 'secret-key')), patch('requests.post', return_value=reply) as post:
            status, body = studio.cloud_voice({'enabled': True})
        self.assertEqual(post.call_args.args[0], 'https://cloud.example/api/vbot/voice')
        self.assertEqual(post.call_args.kwargs['headers']['X-Chess-Buddy-Token'], 'secret-key')
        self.assertNotIn('secret-key', json.dumps(body))


class QwenPromptTests(unittest.TestCase):
    @patch.dict(os.environ, {'QWEN_BASE_URL': 'http://127.0.0.1:18000/v1'})
    def test_history_and_recognizer_doubt_reach_qwen(self):
        client = Mock()
        client.return_value.create.return_value = SimpleNamespace(output_text=json.dumps({'understood': 'x', 'clarifying': True, 'reply': '**Did you** mean dances?'}))
        with patch('coach.qwen_adapter.QwenClient', client):
            answer = vbot_voice.ask_qwen([{'role': 'assistant', 'content': 'hi'}], 'your dan says', True)
        messages = client.return_value.create.call_args.kwargs['input']
        self.assertEqual(messages[0]['content'], 'hi')
        self.assertIn('unsure', messages[-1]['content'])
        self.assertEqual(answer['reply'], 'Did you mean dances?')
        self.assertIn('clarifying question', vbot_voice.INSTRUCTIONS)
        self.assertIn('Big Head', vbot_voice.INSTRUCTIONS)
        self.assertIn('大头', vbot_voice.INSTRUCTIONS)
        self.assertEqual(client.return_value.create.call_args.kwargs['instructions'], vbot_voice.INSTRUCTIONS)

    def test_instructions_are_honest_about_missing_tools_and_identity(self):
        text = vbot_voice.INSTRUCTIONS
        for phrase in ('you have no tool yet to:', 'move, turn, jump', 'change your speaker volume', 'contact a person or a specialist',
                       'cannot do that yet', 'Never invent another reason', 'never deny being Qwen', '打头'):
            self.assertIn(phrase, text)
        self.assertNotIn('cannot move your body', text)
        self.assertIn('Being a robot dog is simply who you are', text)  # A positive persona, not a hedge.
        self.assertIn('This robot dog body is you', text)  # Embodied in the VBOT, not a voice in the cloud.
        self.assertIn('Bring up a limit when someone asks you to do something you cannot', text)
        self.assertIn('what you want most is to make each conversation as warm and fun as it can be', text)

    @patch.dict(os.environ, {'QWEN_BASE_URL': 'http://127.0.0.1:18000/v1'})
    def test_a_cut_off_answer_is_retried_once_without_thinking(self):
        good = SimpleNamespace(output_text=json.dumps({'understood': 'x', 'clarifying': False, 'reply': 'Hello!'}))
        client = Mock()
        client.return_value.create.side_effect = [SimpleNamespace(output_text='{"understood": "x", "repl'), good]
        with patch('coach.qwen_adapter.QwenClient', client):
            self.assertEqual(vbot_voice.ask_qwen([], 'hi', False)['reply'], 'Hello!')
        first, second = client.return_value.create.call_args_list
        self.assertEqual(first.kwargs['max_output_tokens'], vbot_voice.REPLY_TOKENS)
        self.assertEqual(second.kwargs['reasoning_effort'], 'none')
        client.return_value.create.side_effect = RuntimeError('Qwen timed out')
        with patch('coach.qwen_adapter.QwenClient', client), self.assertRaises(RuntimeError):
            vbot_voice.ask_qwen([], 'hi', False)  # A timeout is not retried.

    @patch.dict(os.environ, {'QWEN_BASE_URL': 'http://127.0.0.1:18000/v1'})
    def test_long_replies_end_at_a_whole_sentence(self):
        long_reply = 'Autoregression means predicting the next word. ' * 12
        client = Mock()
        client.return_value.create.return_value = SimpleNamespace(output_text=json.dumps({'understood': 'x', 'clarifying': False, 'reply': long_reply}))
        with patch('coach.qwen_adapter.QwenClient', client):
            reply = vbot_voice.ask_qwen([], 'explain autoregression', True)['reply']
        self.assertLessEqual(len(reply), 400)
        self.assertTrue(reply.endswith('word.'), reply[-30:])

    @patch.dict(os.environ, {'QWEN_BASE_URL': 'http://127.0.0.1:18000/v1'})
    def test_time_question_brings_the_clock_to_qwen(self):
        client = Mock()
        client.return_value.create.return_value = SimpleNamespace(output_text=json.dumps({'understood': 'time', 'clarifying': False, 'reply': 'Noon.'}))
        with patch('coach.qwen_adapter.QwenClient', client):
            vbot_voice.ask_qwen([], 'what time is it', False)
        instructions = client.return_value.create.call_args.kwargs['instructions']
        self.assertTrue(instructions.startswith(vbot_voice.INSTRUCTIONS))
        self.assertIn('"local_time"', instructions)


if __name__ == '__main__':
    unittest.main()
