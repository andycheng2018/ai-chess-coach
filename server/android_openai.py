"""Small Responses transport for Android, avoiding desktop-only SDK wheels.

The prompt, validation and audit logic remain in coach/llm_coach.py.
"""
import os
from types import SimpleNamespace
import requests


class OpenAI:
    def __init__(self, timeout=45):
        self.timeout = timeout
        self.responses = self

    def with_options(self, timeout=45, max_retries=0):
        return OpenAI(timeout=timeout)

    def create(self, **payload):
        key = os.environ.get('OPENAI_API_KEY', '').strip()
        if not key:
            raise RuntimeError('Add an OpenAI key in Tablet settings to talk with Luna.')
        response = requests.post('https://api.openai.com/v1/responses',
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                                 json={**payload, 'store': False}, timeout=self.timeout)
        if not response.ok:
            raise RuntimeError(f'Luna request failed ({response.status_code}). Check the key, API access and Internet connection.')
        data = response.json()
        text = ''.join(part.get('text', '') for item in data.get('output', [])
                       if item.get('type') == 'message' for part in item.get('content', [])
                       if part.get('type') == 'output_text')
        return SimpleNamespace(output_text=text, status=data.get('status', 'completed'))
