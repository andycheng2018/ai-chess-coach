import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from android_openai import OpenAI

class AndroidResponsesTests(unittest.TestCase):
    def test_responses_payload_and_output_keep_existing_audit_contract(self):
        response=Mock(ok=True)
        response.json.return_value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'A useful hint.'}]}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-key'}),patch('android_openai.requests.post',return_value=response) as post:
            result=OpenAI().with_options(timeout=12,max_retries=0).responses.create(model='gpt-4.1-mini',input='Question',store=True)
        self.assertEqual(result.output_text,'A useful hint.')
        self.assertEqual(post.call_args.kwargs['json']['store'],False)
        self.assertEqual(post.call_args.kwargs['timeout'],12)
    def test_missing_key_and_provider_errors_are_explicit_without_key_echo(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}),self.assertRaisesRegex(RuntimeError,'Tablet settings'):
            OpenAI().responses.create(input='Question')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-key'}),patch('android_openai.requests.post',return_value=Mock(ok=False,status_code=401)),self.assertRaisesRegex(RuntimeError,'401') as error:
            OpenAI().responses.create(input='Question')
        self.assertNotIn('fixture-key',str(error.exception))

if __name__=='__main__':unittest.main()
