"""Read-only connection checks behind the in-app Test Dashboard.

Nothing here can move the robot. The robot only ever sees an SSH echo, the existing
--check-ready probe and a GET on its agent's MCP connection list. Reports never carry
tokens or request headers.
"""
from __future__ import annotations

import json
import os
import threading
import time

import requests

from vbot_demo import run_ssh
from vbot_ssh import ssh_argv

PASS, WARN, FAIL, SKIP = 'pass', 'warn', 'fail', 'skip'
_RANK = {SKIP: 0, PASS: 1, WARN: 2, FAIL: 3}

MCP_URL = 'https://vbot-mcp.urbot.ai/mcp'
MCP_VERSION = '2025-06-18'
MCP_SERVER_NAME = 'qwen-bridge'
MCP_TOOL = 'qwen_ask'
AGENT_SERVERS_URL = 'http://192.168.127.10:8787/api/admin/extensions/vbot-mcp/http/servers'
AGENT_WORKING_DIR = '/app/vbot-agent-harness'
SLOW_QWEN_MS = 20_000
# The helper answered, so the link works; these only mean the dog can't move right now.
RESPONSIVE_CODES = {'battery', 'system', 'posture', 'head_fault', 'head_pending', 'head_busy', 'stale', 'incomplete', 'not_ready'}


def _clip(text, limit=200):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _ms(started):
    return round((time.monotonic() - started) * 1000)


class Report:
    def __init__(self, check):
        self.check, self.started, self.steps = check, time.monotonic(), []

    def add(self, label, status, detail, started=None):
        self.steps.append({'label': label, 'status': status, 'detail': _clip(detail),
                           'latencyMs': None if started is None else _ms(started)})
        return status

    def finish(self, summary=None):
        status = max((step['status'] for step in self.steps), key=_RANK.get, default=SKIP)
        if summary is None:
            summary = next((step['detail'] for step in self.steps if step['status'] == status), '')
        return {'check': self.check, 'status': status, 'summary': _clip(summary),
                'latencyMs': _ms(self.started), 'steps': self.steps}


def ssh_failure(stderr):
    error = (stderr or '').lower()
    if 'host key verification failed' in error or 'remote host identification has changed' in error:
        return "The dog's SSH identity could not be verified."
    if 'permission denied' in error:
        return "The dog refused this server's SSH key."
    return "The dog isn't answering. Check its power, Wi-Fi and link to the server."


def run_on_robot(demo, remote, timeout, stdin=None):
    """Returns (finished process, None) or (None, reason), using the same pinned identity as dispatch."""
    if not demo.target:
        return None, 'No robot address is configured on this server.'
    try:
        # known_hosts is keyed by the bare address, so drop the account name from the anchor.
        alias = demo._ssh_identity_anchor().removeprefix('vbot@') if demo.network_book is not None else None
        extra = {} if stdin is None else {'input': stdin}
        return run_ssh(ssh_argv(demo.target, remote, host_key_alias=alias),
                       capture_output=True, text=True, timeout=timeout, check=False, **extra), None
    except ValueError as error:
        return None, str(error)
    except Exception as error:  # A subprocess timeout or the Android SSH client.
        return None, f"The dog didn't answer in time ({type(error).__name__})."


def _robot_ssh(demo, remote, timeout):
    """Returns (stdout, None) or (None, reason)."""
    done, problem = run_on_robot(demo, remote, timeout)
    if problem:
        return None, problem
    if done.returncode != 0:
        return None, ssh_failure(done.stderr)
    return done.stdout, None


def check_backend(demo, server):
    report = Report('backend')
    report.add('Chess server', PASS, 'The server answered this device.')
    public_url = server.get('publicUrl') or ''
    report.add('Hosting', PASS if public_url.startswith('https://') else WARN,
               f'Published at {public_url}' if public_url.startswith('https://') else 'This server has no public address, so it is running locally.')
    report.add('Stockfish', PASS if server.get('stockfish') else FAIL,
               'Engine found.' if server.get('stockfish') else 'No Stockfish engine on this server.')
    report.add('Coach', PASS if server.get('coachConfigured') else WARN,
               f"Provider: {server.get('coachProvider', 'unknown')}." if server.get('coachConfigured') else 'No coach provider is configured.')
    return report.finish()


def _mcp_problem(response):
    if response.status_code == 401:
        return "The bridge rejected this server's MCP token."
    if response.status_code in {301, 302, 303, 307, 308}:
        return 'Something redirected the request, likely a Cloudflare Access login on this hostname.'
    if response.status_code == 403:
        return 'Cloudflare or the bridge refused the request (HTTP 403).'
    if response.status_code in {502, 503, 504, 530}:
        return f'The tunnel could not reach the bridge (HTTP {response.status_code}). Check its LaunchAgent on the Mac Studio.'
    return f'The bridge answered HTTP {response.status_code}.'


def _mcp_post(url, token, payload, timeout):
    return requests.post(url, data=json.dumps(payload), timeout=timeout, allow_redirects=False, headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': MCP_VERSION,
        'User-Agent': 'ChessBuddyDiagnostics/1.0'})


def _mcp_rpc(url, token, request_id, method, params, timeout):
    """Returns (result, None) or (None, reason)."""
    response = _mcp_post(url, token, {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}, timeout)
    if response.status_code != 200:
        return None, _mcp_problem(response)
    body = response.json()
    if 'error' in body:
        return None, f"The bridge returned an error: {body['error'].get('message', 'unknown')}"
    return body.get('result'), None


def _agent_registration(demo, report):
    query = f"workingDir={AGENT_WORKING_DIR}"
    started = time.monotonic()
    output, problem = _robot_ssh(demo, f"curl --noproxy '*' -fsS --connect-timeout 3 --max-time 10 '{AGENT_SERVERS_URL}?{query}'", 20)
    label = 'Registered on the dog'
    if problem:
        return report.add(label, WARN, f"Couldn't ask the dog's agent: {problem}", started)
    try:
        listing = json.loads(output)
        entry = next((item for item in listing['servers'] if item.get('name') == MCP_SERVER_NAME), None)
    except (ValueError, KeyError, TypeError):
        return report.add(label, WARN, "The dog's agent returned an unreadable connection list.", started)
    if entry is None:
        return report.add(label, FAIL, f'{MCP_SERVER_NAME} is not registered with the agent.', started)
    if not entry.get('enabled'):
        return report.add(label, FAIL, f'{MCP_SERVER_NAME} is registered but disabled.', started)
    if entry.get('configError'):
        return report.add(label, FAIL, f"Agent reports: {entry['configError']}", started)
    tools = entry.get('toolCount') or 0
    if listing.get('refreshPending') or not listing.get('catalogReady'):
        return report.add(label, WARN, f'Enabled with {tools} tool(s), but the agent is still refreshing its catalog.', started)
    if tools < 1:
        return report.add(label, FAIL, "Enabled, but the agent found no tools. Discovery can't reach the bridge.", started)
    return report.add(label, PASS, f'Enabled, and the agent sees {tools} tool.' if tools == 1 else f'Enabled, and the agent sees {tools} tools.', started)


def check_mcp(demo, server):
    report = Report('mcp')
    token = os.environ.get('QWEN_MCP_TOKEN', '').strip()
    url = os.environ.get('VBOT_MCP_URL', MCP_URL).strip()
    if not token:
        report.add('Bridge handshake', FAIL, 'QWEN_MCP_TOKEN is not set on this server, so it cannot test the bridge.')
        _agent_registration(demo, report)
        return report.finish()
    try:
        started = time.monotonic()
        result, problem = _mcp_rpc(url, token, 1, 'initialize', {
            'protocolVersion': MCP_VERSION, 'capabilities': {},
            'clientInfo': {'name': 'chess-buddy-diagnostics', 'version': '1.0'}}, 15)
        if problem:
            report.add('Bridge handshake', FAIL, problem, started)
            _agent_registration(demo, report)
            return report.finish()
        response = _mcp_post(url, token, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, 15)
        if response.status_code != 202:
            report.add('Bridge handshake', FAIL, _mcp_problem(response), started)
            _agent_registration(demo, report)
            return report.finish()
        report.add('Bridge handshake', PASS, f"{result['serverInfo']['name']} is up at {url}", started)

        started = time.monotonic()
        result, problem = _mcp_rpc(url, token, 2, 'tools/list', {}, 15)
        names = [tool.get('name') for tool in (result or {}).get('tools', [])]
        tool_ok = not problem and MCP_TOOL in names
        report.add('Tool list', PASS if tool_ok else FAIL, f'{MCP_TOOL} is offered.' if tool_ok else problem or f'{MCP_TOOL} is missing.', started)

        if tool_ok:
            started = time.monotonic()
            result, problem = _mcp_rpc(url, token, 3, 'tools/call', {'name': MCP_TOOL, 'arguments': {'question': 'Reply with exactly: MCP OK'}}, 80)
            if problem:
                report.add('Tool call', FAIL, problem, started)
            elif result.get('isError'):
                report.add('Tool call', FAIL, result['content'][0]['text'], started)
            else:
                report.add('Tool call', PASS, 'Qwen replied through the bridge: ' + result['content'][0]['text'], started)
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        report.add('Bridge', FAIL, f'Could not complete the MCP exchange ({type(error).__name__}).')
    _agent_registration(demo, report)
    failed = any(step['status'] == FAIL for step in report.steps)
    return report.finish(None if failed or any(step['status'] == WARN for step in report.steps) else 'The bridge works and the dog\'s agent has the tool.')


def check_qwen(demo, server):
    report = Report('qwen')
    if os.getenv('LLM_PROVIDER', 'openai').lower() != 'qwen':
        report.add('Qwen endpoint', SKIP, 'This server is not set to use Qwen.')
        return report.finish()
    base = os.getenv('QWEN_BASE_URL', 'http://127.0.0.1:18000/v1').rstrip('/')
    model = os.getenv('QWEN_MODEL', 'qwen3.8-27b:latest')
    try:
        started = time.monotonic()
        response = requests.get(base + '/models', timeout=10)
        response.raise_for_status()
        models = [item.get('id') for item in response.json().get('data', [])]
        report.add('Model available', PASS if model in models else FAIL,
                   f'{model} is loaded on the endpoint.' if model in models else f'{model} is not on the endpoint.', started)

        started = time.monotonic()
        response = requests.post(base + '/chat/completions', timeout=80, json={
            'model': model, 'stream': False, 'max_tokens': 256,
            'messages': [{'role': 'user', 'content': 'Reply with exactly: QWEN OK'}]})
        response.raise_for_status()
        answer = (response.json()['choices'][0]['message'].get('content') or '').strip()
        elapsed = _ms(started)
        if not answer:
            report.add('Generated a reply', FAIL, 'Qwen returned an empty reply.', started)
        elif elapsed > SLOW_QWEN_MS:
            report.add('Generated a reply', WARN, f'Answered, but slowly: {answer}', started)
        else:
            report.add('Generated a reply', PASS, f'Qwen said: {answer}', started)
    except requests.RequestException as error:
        report.add('Qwen endpoint', FAIL, f"The endpoint didn't respond properly ({type(error).__name__}).", started)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        report.add('Qwen endpoint', FAIL, 'The endpoint returned an unexpected response.', started)

    # Reaching the endpoint is not enough: the coach builds its own client from the same settings.
    try:
        from coach.qwen_adapter import QwenClient
        QwenClient()
        report.add('Coach can use it', PASS, "Luna's coaching client accepts this endpoint.")
    except ValueError as error:
        report.add('Coach can use it', WARN, f"Luna's coaching client refuses this endpoint: {error}")
    return report.finish(None if any(step['status'] != PASS for step in report.steps) else f'{model} is responding.')


def check_vbot(demo, server):
    report = Report('vbot')
    started = time.monotonic()
    output, problem = _robot_ssh(demo, "echo chess-buddy-ok; cut -d' ' -f1 /proc/uptime", 15)
    if problem or 'chess-buddy-ok' not in (output or ''):
        report.add('Cloud reaches dog', FAIL, problem or 'The dog gave an unexpected reply.', started)
        return report.finish()
    try:
        hours = float(output.split()[1]) / 3600
        uptime = f'Dog has been on for {hours:.1f} hours.'
    except (IndexError, ValueError):
        uptime = 'Dog answered over SSH.'
    report.add('Cloud reaches dog', PASS, f'{uptime} Reached as {demo.target}.', started)

    if demo.armed or demo.busy:
        report.add('Robot helper', SKIP, 'Reactions are on, so this check is skipped to avoid interfering.')
    else:
        started = time.monotonic()
        try:
            state = demo.checker(demo.target)
        except Exception as error:
            state = {'ready': False, 'code': 'unavailable', 'reason': _clip(error)}
        if state.get('ready'):
            report.add('Robot helper', PASS, 'Helper answered: the dog is ready for commands.', started)
        elif state.get('code') in RESPONSIVE_CODES:
            report.add('Robot helper', WARN, f"Helper answered, but the dog can't move right now: {state.get('reason') or state.get('code')}", started)
        else:
            report.add('Robot helper', FAIL, state.get('reason') or 'The robot helper did not answer.', started)
    return report.finish(None if any(step['status'] in {WARN, FAIL} for step in report.steps) else 'The dog is responding to the cloud.')


CHECKS = {'backend': check_backend, 'mcp': check_mcp, 'qwen': check_qwen, 'vbot': check_vbot}
_locks = {name: threading.Lock() for name in CHECKS}


def run_check(name, demo, server):
    """One run per check at a time, so repeated taps can't pile up on the model or the dog."""
    if not _locks[name].acquire(blocking=False):
        return {'check': name, 'status': WARN, 'summary': 'This check is already running.', 'latencyMs': 0, 'steps': []}
    try:
        return CHECKS[name](demo, server)
    finally:
        _locks[name].release()
