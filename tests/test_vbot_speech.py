"""Qwen-to-dog speech. Network and robot I/O are replaced; nothing here reaches a robot."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'vbot-demo'))
import diagnostics
import robot_speak
import vbot_speech


def demo(**overrides):
    values = dict(target='vbot-remote', network_book=None, armed=False, busy=False)
    values.update(overrides)
    return SimpleNamespace(**values)


def ssh(stdout='', returncode=0, stderr=''):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


RESULT = json.dumps({'event': 'speak_result', 'ok': True, 'status': 0, 'errorCode': 0, 'message': 'ok'})


class SayTests(unittest.TestCase):
    def test_text_goes_over_stdin_and_never_into_the_remote_command(self):
        words = "it's; rm -rf / $(reboot)"
        with patch.object(diagnostics, 'run_ssh', return_value=ssh('log line\n' + RESULT)) as run:
            self.assertTrue(vbot_speech.say(demo(), {'text': words})['ok'])
        self.assertEqual(run.call_args.kwargs['input'], words)
        self.assertNotIn('rm -rf', run.call_args.args[0][-1])
        self.assertIn('robot_speak.py', run.call_args.args[0][-1])

    def test_never_talks_during_reactions(self):
        for state in ({'armed': True}, {'busy': True}):
            with patch.object(diagnostics, 'run_ssh') as run:
                self.assertFalse(vbot_speech.say(demo(**state), {'text': 'hi'})['ok'])
            run.assert_not_called()

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            vbot_speech.say(demo(), {'text': '  <think>only thoughts</think> '})

    def test_helper_refusal_keeps_its_reason(self):
        refused = json.dumps({'event': 'speak_refused', 'code': 'busy', 'reason': 'A show is using the dog.'})
        with patch.object(diagnostics, 'run_ssh', return_value=ssh(refused, returncode=1)):
            self.assertEqual(vbot_speech.say(demo(), {'text': 'hi'})['reason'], 'A show is using the dog.')

    def test_speech_service_refusal_is_not_success(self):
        bad = json.dumps({'event': 'speak_result', 'ok': False, 'message': 'Speaker busy'})
        with patch.object(diagnostics, 'run_ssh', return_value=ssh(bad, returncode=1)):
            result = vbot_speech.say(demo(), {'text': 'hi'})
        self.assertFalse(result['ok'])
        self.assertIn('Speaker busy', result['reason'])

    def test_lost_link_and_timeout_are_explained(self):
        with patch.object(diagnostics, 'run_ssh', return_value=ssh(returncode=255, stderr='Connection refused')):
            self.assertIn("isn't answering", vbot_speech.say(demo(), {'text': 'hi'})['reason'])
        with patch.object(diagnostics, 'run_ssh', side_effect=subprocess.TimeoutExpired('ssh', 40)):
            self.assertFalse(vbot_speech.say(demo(), {'text': 'hi'})['ok'])

    def test_missing_helper_is_explained(self):
        with patch.object(diagnostics, 'run_ssh', return_value=ssh('', returncode=2, stderr='No such file')):
            self.assertIn('installed', vbot_speech.say(demo(), {'text': 'hi'})['reason'])


class FitSpokenTests(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(vbot_speech.fit_spoken('Hi there. I am Big Head!'), 'Hi there. I am Big Head!')

    def test_long_text_ends_at_the_last_whole_sentence(self):
        english = 'The loop is predict, add, repeat. ' * 20
        fitted = vbot_speech.fit_spoken(english)
        self.assertLessEqual(len(fitted), vbot_speech.MAX_SPOKEN)
        self.assertTrue(fitted.endswith('repeat.'))
        chinese = '你知道小狗为什么怕夏天吗？因为一热尾巴就直了。' * 30
        fitted = vbot_speech.fit_spoken(chinese)
        self.assertLessEqual(len(fitted), vbot_speech.MAX_SPOKEN)
        self.assertTrue(fitted.endswith(('。', '？')))

    def test_text_without_sentence_ends_stops_at_a_word_with_an_ellipsis(self):
        fitted = vbot_speech.fit_spoken('word ' * 200)
        self.assertLessEqual(len(fitted), vbot_speech.MAX_SPOKEN)
        self.assertTrue(fitted.endswith('word\u2026'))
        self.assertLessEqual(len(vbot_speech.fit_spoken('y' * 900)), vbot_speech.MAX_SPOKEN)

    def test_the_dog_speaks_fitted_text_unchanged(self):
        for raw in ('The loop is predict, add, repeat. ' * 20, 'word ' * 200, '你好。' * 300):
            fitted = vbot_speech.fit_spoken(vbot_speech.spoken_text(raw, limit=None))
            self.assertEqual(robot_speak.clean(fitted), fitted)


class HelperTests(unittest.TestCase):
    def test_server_and_dog_clean_text_identically(self):
        for raw in ('<think>a</think>hi', 'plain **bold** `x`', 'a\x07b\nc', 'y' * 900, '<think>never closed'):
            self.assertEqual(vbot_speech.spoken_text(raw), robot_speak.clean(raw))


if __name__ == '__main__':
    unittest.main()
