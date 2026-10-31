"""Ollama OpenAI-chat compatibility for this application's Responses-style coach.

Deliberately supports the three known coach call patterns, not the full Responses API.
Never returns hidden model reasoning as displayable/spoken text.
"""
from __future__ import annotations
import os
from types import SimpleNamespace
import requests


class QwenClient:
    def __init__(self, timeout=60, max_retries=0):
        base = os.getenv('QWEN_BASE_URL', 'http://127.0.0.1:18000/v1').rstrip('/')
        if not base.startswith(('http://127.0.0.1:', 'http://localhost:', 'https://')):
            raise ValueError('QWEN_BASE_URL must be a local tunnel or HTTPS endpoint')
        self.url = base + '/chat/completions'
        self.timeout = timeout
        self.responses = self

    def with_options(self, timeout=60, max_retries=0):
        return QwenClient(timeout=timeout, max_retries=max_retries)

    def create(self, *, model, instructions, input, text=None,
               max_output_tokens=1200, store=False, **kwargs):
        if not isinstance(instructions, str):
            raise TypeError('Expected string instructions')
        messages = [{'role': 'system', 'content': instructions}]
        if isinstance(input, str):
            messages.append({'role': 'user', 'content': input})
        elif isinstance(input, list):
            for msg in input:
                if not isinstance(msg, dict) or msg.get('role') not in ('user','assistant','system') or not isinstance(msg.get('content'),str):
                    raise ValueError('Unexpected chat message format')
                messages.append({'role':msg['role'], 'content':msg['content']})
        else:
            raise TypeError('Expected string or chat-message list')
        payload={'model':model,'messages':messages,'stream':False,'max_tokens':max_output_tokens}
        if text:
            fmt=text.get('format',{})
            if fmt.get('type')!='json_schema':
                raise ValueError('Unsupported response format')
            payload['response_format']={
                'type':'json_schema',
                'json_schema': {'name':fmt['name'],'strict':fmt.get('strict',True),'schema':fmt['schema']}
            }
        try:
            response=requests.post(self.url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data=response.json()
            choice=data['choices'][0]
            content=choice['message'].get('content') or ''
            if not isinstance(content,str) or not content.strip():
                raise ValueError('Qwen returned empty response content')
            # Never expose message.reasoning / message.thinking to application output.
            return SimpleNamespace(output_text=content, status='completed' if choice.get('finish_reason')=='stop' else 'incomplete')
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError(f'Qwen inference request failed: {error}') from error
