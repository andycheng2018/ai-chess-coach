"""Read-only, bounded commentary for the local VBOT demo desk.

No robot imports/commands, never changes dance eligibility or movement.
"""
import os
import re
import requests
from coach.history import audit_call, record_attempt, timestamp

FALLBACK = {
    'blunder': 'That one was tricky. Take another look at what your opponent can capture.',
    'good': 'Nice move! Keep looking for threats and opportunities.',
}


@audit_call("vbot_commentary")
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
    synthetic = event.get("synthetic") is True
    classification = event["classification"]
    tier = event.get("tier", "small")

    prompt = (
        "You are VBOT, a playful, encouraging chess robot dog. "
        "Write exactly ONE natural sentence, 6 to 14 words. "
        "Sound like a fun companion, not a textbook. "
        "Occasional dog personality is welcome, but no forced barking. "
        "Never invent tactical facts, captures, threats, evaluations, "
        "or specific board features. Do not exaggerate move quality. "
        "Do not claim the robot physically performed anything. "
        "No markdown, emojis, stage directions, or commands. "
        f"Verified controller classification: {classification}. "
        f"Approved reaction tier: {tier}. "
        f"Played notation: {str(event.get('playedMove') or 'unknown')[:20]}. "
        + (
            "This is a SYNTHETIC rehearsal sample, not a verified "
            "chess position. Keep the response generic."
            if synthetic else
            "Respond naturally to the verified event classification."
        )
    )

    entry = {'timestamp': timestamp(), 'type': 'vbot_commentary', 'game_id': event.get('gameId', ''),
             'model': os.environ.get('QWEN_MODEL', 'qwen3.8-27b:latest'), 'input': prompt,
             'instructions': 'You are a friendly chess robot. Give exactly one short, encouraging sentence. Do not exaggerate the move quality.',
             'payload': dict(event)}
    attempted = False
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

        attempted = True
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
        raw = resp.json()['message']['content']
        entry['raw_output'] = raw
        if not isinstance(raw, str):
            raise ValueError('Invalid commentary content type')
        text = raw.strip()
        text = re.sub(r'\s+', ' ', text).strip(' "\n')
        if not text or '<' in text:
            raise ValueError('Invalid generated commentary')

        if len(text) > 180:
            text = text[:180].rsplit(' ', 1)[0].rstrip(' ,;:-') + '...'
        entry.update(status='success', parsed={'commentary': text})
        return {'commentary': text, 'source': 'qwen'}
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as exc:
        entry.update(status='error', error=type(exc).__name__)
        return {'commentary': fallback, 'source': 'fallback'}

    finally:
        if attempted:
            record_attempt(entry)
