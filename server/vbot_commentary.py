"""Read-only, bounded commentary for the local VBOT demo desk.

No robot imports/commands, never changes dance eligibility or movement.
"""
import os
import re
import requests

FALLBACK = {
    'blunder': 'That one was tricky. Take another look at what your opponent can capture.',
    'good': 'Nice move! Keep looking for threats and opportunities.',
}


def commentary_for_event(demo, payload):
    # Source of truth is the server's event log, not user-supplied classification.
    event = None
    for entry in demo.status().get('events', []):
        if (entry.get('time') == payload.get('time') and
            entry.get('status') == payload.get('status') and
            entry.get('gameId') == payload.get('gameId') and
            entry.get('ply') == payload.get('ply')):
            event = entry
            break
    if not event or event.get('status') not in {'rehearsed', 'requested'}:
        raise ValueError('No matching, eligible VBOT reaction event.')
    classification = event.get('classification')
    if classification not in {'good', 'excellent', 'best', 'brilliant', 'blunder'}:
        raise ValueError('No eligible classification for commentary.')
    fallback = FALLBACK['blunder' if classification == 'blunder' else 'good']
    if os.environ.get('LLM_PROVIDER', '').lower() != 'qwen':
        return {'commentary': fallback, 'source': 'fallback'}
    prompt = (f'A chess engine verified a {classification} move. '
              f'The played move notation is {str(event.get("playedMove") or "unknown")[:20]}. '
              f'The approved reaction tier is {str(event.get("tier") or "small")[:10]}. '
              'Write exactly one friendly, energetic sentence (at most 20 words) '
              'for a chess-playing robot dog. Do not invent a tactic, position, '
              'capture, evaluation or outcome. No stage directions, markdown, or commands.')
    try:

        url = os.environ.get(
            'QWEN_BASE_URL',
            'http://' + '127.0.0.1:18000/v1'
        ).rstrip('/')

        allowed = {
            'http://' + '127.0.0.1:18000/v1',
            'http://' + 'localhost:18000/v1'
        }
        if url not in allowed:
            return {'commentary': fallback, 'source': 'fallback'}

        resp = requests.post(
            url.removesuffix('/v1') + '/api/chat',
            json={
                'model': os.environ.get('QWEN_MODEL', 'qwen3.8-27b:latest'),
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You are a friendly chess robot. Give exactly one short, encouraging sentence. Do not exaggerate the move quality.'
                    },
                    {'role': 'user', 'content': prompt},
                ],
                'stream': False,
                'think': False,
                'options': {'num_predict': 256},
                'keep_alive': '10m',
            },
            timeout=(3, 30),
        )
        resp.raise_for_status()
        text = resp.json()['message']['content'].strip()

        text = re.sub(r'\s+', ' ', text).strip(' "\n')
        print(
            '[VBOT QWEN DEBUG]',
            'length=', len(text),
            'empty=', not bool(text),
            'has_markup=', '<' in text,
            'preview=', repr(text[:150]),
            flush=True
        )
        if not text or '<' in text:
            raise ValueError('Invalid generated commentary')

        if len(text) > 180:
            print('[VBOT QWEN] Long response:', repr(text[:250]), flush=True)
            text = text[:180].rsplit(' ', 1)[0].rstrip(' ,;:-') + '...'
        return {'commentary': text, 'source': 'qwen'}
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as exc:
        print('[VBOT QWEN] Commentary failed:', repr(exc), flush=True)
        return {'commentary': fallback, 'source': 'fallback'}
