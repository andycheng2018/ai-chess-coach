"""Test Dashboard checks. Network and robot I/O are replaced; nothing here moves a robot."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import diagnostics


def demo(**overrides):
    values = dict(target='vbot-remote', network_book=None, armed=False, busy=False,
                  checker=Mock(return_value={'ready': True, 'code': 'ready'}))
    values.update(overrides)
    return SimpleNamespace(**values)


def ssh_result(stdout='', returncode=0, stderr=''):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def http(status=200, body=None):
    return Mock(status_code=status, json=Mock(return_value=body or {}), raise_for_status=Mock())


AGENT_OK = json.dumps({'catalogReady': True, 'refreshPending': False,
                       'servers': [{'name': 'edu-user', 'enabled': True, 'toolCount': 0},
                                   {'name': 'qwen-bridge', 'enabled': True, 'toolCount': 1}]})


def steps(report):
    return {step['label']: step['status'] for step in report['steps']}


class VbotTests(unittest.TestCase):
    def test_answering_dog_passes(self):
        with patch.object(diagnostics, 'run_ssh', return_value=ssh_result('chess-buddy-ok\n7200.5\n')):
            report = diagnostics.check_vbot(demo(), {})
        self.assertEqual(report['status'], 'pass')

    def test_ssh_pins_the_saved_host_key_by_bare_address(self):
        robot = demo(network_book=object(), _ssh_identity_anchor=lambda: 'vbot@172.20.10.5')
        with patch.object(diagnostics, 'run_ssh', return_value=ssh_result('chess-buddy-ok\n1\n')) as ssh:
            diagnostics.check_vbot(robot, {})
        self.assertIn('HostKeyAlias=172.20.10.5', ssh.call_args.args[0])

    def test_a_dead_link_fails_and_never_probes_the_helper(self):
        robot = demo()
        with patch.object(diagnostics, 'run_ssh', return_value=ssh_result(returncode=255, stderr='Connection refused')):
            report = diagnostics.check_vbot(robot, {})
        self.assertEqual(report['status'], 'fail')
        robot.checker.assert_not_called()

    def test_helper_is_not_touched_while_reactions_are_on(self):
        for state in ({'armed': True}, {'busy': True}):
            robot = demo(**state)
            with patch.object(diagnostics, 'run_ssh', return_value=ssh_result('chess-buddy-ok\n1\n')):
                report = diagnostics.check_vbot(robot, {})
            robot.checker.assert_not_called()
            self.assertEqual(steps(report)['Robot helper'], 'skip')

    def test_a_low_battery_answer_still_proves_the_link(self):
        robot = demo(checker=Mock(return_value={'ready': False, 'code': 'battery', 'reason': 'Battery low'}))
        with patch.object(diagnostics, 'run_ssh', return_value=ssh_result('chess-buddy-ok\n1\n')):
            self.assertEqual(diagnostics.check_vbot(robot, {})['status'], 'warn')

    def test_robot_commands_are_read_only(self):
        with patch.object(diagnostics, 'run_ssh', return_value=ssh_result(AGENT_OK)) as ssh:
            diagnostics._agent_registration(demo(), diagnostics.Report('mcp'))
        remote = ssh.call_args.args[0][-1]
        self.assertTrue(remote.startswith('curl '))
        for write in ('-X', '--data', '-d '):
            self.assertNotIn(write, remote)


@patch.dict(os.environ, {'QWEN_MCP_TOKEN': 'secret-mcp-token'})
class McpTests(unittest.TestCase):
    def happy(self):
        return [http(200, {'result': {'serverInfo': {'name': 'vbot-qwen-mcp'}}}), http(202),
                http(200, {'result': {'tools': [{'name': 'qwen_ask'}]}}),
                http(200, {'result': {'content': [{'type': 'text', 'text': 'MCP OK'}], 'isError': False}})]

    def test_full_path_passes_and_keeps_the_token_out_of_the_report(self):
        with patch.object(diagnostics.requests, 'post', side_effect=self.happy()), \
             patch.object(diagnostics, 'run_ssh', return_value=ssh_result(AGENT_OK)):
            report = diagnostics.check_mcp(demo(), {})
        self.assertEqual(report['status'], 'pass')
        self.assertNotIn('secret-mcp-token', json.dumps(report))

    def test_rejected_token_fails(self):
        with patch.object(diagnostics.requests, 'post', return_value=http(401)), \
             patch.object(diagnostics, 'run_ssh', return_value=ssh_result(AGENT_OK)):
            report = diagnostics.check_mcp(demo(), {})
        self.assertEqual(steps(report)['Bridge handshake'], 'fail')
        self.assertIn('token', report['summary'])

    def test_tool_failure_is_not_success(self):
        replies = self.happy()
        replies[3] = http(200, {'result': {'content': [{'type': 'text', 'text': 'Qwen upstream HTTP 500'}], 'isError': True}})
        with patch.object(diagnostics.requests, 'post', side_effect=replies), \
             patch.object(diagnostics, 'run_ssh', return_value=ssh_result(AGENT_OK)):
            self.assertEqual(steps(diagnostics.check_mcp(demo(), {}))['Tool call'], 'fail')

    def test_unregistered_or_toolless_agent_fails(self):
        for listing in ({'catalogReady': True, 'servers': []},
                        {'catalogReady': True, 'servers': [{'name': 'qwen-bridge', 'enabled': True, 'toolCount': 0}]},
                        {'catalogReady': True, 'servers': [{'name': 'qwen-bridge', 'enabled': False, 'toolCount': 1}]}):
            with patch.object(diagnostics.requests, 'post', side_effect=self.happy()), \
                 patch.object(diagnostics, 'run_ssh', return_value=ssh_result(json.dumps(listing))):
                self.assertEqual(steps(diagnostics.check_mcp(demo(), {}))['Registered on the dog'], 'fail')

    def test_unreachable_dog_is_unknown_not_failed(self):
        with patch.object(diagnostics.requests, 'post', side_effect=self.happy()), \
             patch.object(diagnostics, 'run_ssh', return_value=ssh_result(returncode=255, stderr='timed out')):
            self.assertEqual(diagnostics.check_mcp(demo(), {})['status'], 'warn')

    def test_missing_token_is_reported(self):
        with patch.dict(os.environ, {'QWEN_MCP_TOKEN': ''}), \
             patch.object(diagnostics, 'run_ssh', return_value=ssh_result(AGENT_OK)):
            self.assertIn('QWEN_MCP_TOKEN', diagnostics.check_mcp(demo(), {})['summary'])


@patch.dict(os.environ, {'LLM_PROVIDER': 'qwen', 'QWEN_BASE_URL': 'http://127.0.0.1:11434/v1', 'QWEN_MODEL': 'qwen-test'})
class QwenTests(unittest.TestCase):
    MODELS = {'data': [{'id': 'qwen-test'}]}
    REPLY = {'choices': [{'message': {'content': 'QWEN OK'}}]}

    def test_responsive_endpoint_passes(self):
        with patch.object(diagnostics.requests, 'get', return_value=http(200, self.MODELS)), \
             patch.object(diagnostics.requests, 'post', return_value=http(200, self.REPLY)):
            self.assertEqual(diagnostics.check_qwen(demo(), {})['status'], 'pass')

    def test_coach_rejecting_the_endpoint_is_surfaced(self):
        with patch.dict(os.environ, {'QWEN_BASE_URL': 'http://example.com:11434/v1'}), \
             patch.object(diagnostics.requests, 'get', return_value=http(200, self.MODELS)), \
             patch.object(diagnostics.requests, 'post', return_value=http(200, self.REPLY)):
            report = diagnostics.check_qwen(demo(), {})
        self.assertEqual(report['status'], 'warn')
        self.assertEqual(steps(report)['Coach can use it'], 'warn')

    def test_the_hosted_docker_address_works_for_the_coach(self):
        with patch.dict(os.environ, {'QWEN_BASE_URL': 'http://host.docker.internal:11434/v1'}), \
             patch.object(diagnostics.requests, 'get', return_value=http(200, self.MODELS)), \
             patch.object(diagnostics.requests, 'post', return_value=http(200, self.REPLY)):
            self.assertEqual(diagnostics.check_qwen(demo(), {})['status'], 'pass')

    def test_down_endpoint_fails(self):
        with patch.object(diagnostics.requests, 'get', side_effect=diagnostics.requests.ConnectionError()):
            self.assertEqual(diagnostics.check_qwen(demo(), {})['status'], 'fail')

    def test_other_provider_is_skipped(self):
        with patch.dict(os.environ, {'LLM_PROVIDER': 'openai'}):
            self.assertEqual(diagnostics.check_qwen(demo(), {})['status'], 'skip')


class RunTests(unittest.TestCase):
    def test_a_second_run_of_the_same_check_is_refused(self):
        with diagnostics._locks['vbot']:
            self.assertEqual(diagnostics.run_check('vbot', demo(), {})['summary'], 'This check is already running.')


if __name__ == '__main__':
    unittest.main()
