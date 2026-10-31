"""Provider integration without contacting Ollama, SSH, TTS or robots."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import app
from coach.qwen_adapter import QwenClient
from coach.llm_coach import LLMCoach
from coach.history import CoachHistory
from vbot_commentary import commentary_for_event

class QwenIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.journal=CoachHistory(Path(temp.name)/'audit.jsonl')
        p=patch('coach.history.history',self.journal);p.start();self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'LLM_PROVIDER':'qwen','QWEN_BASE_URL':'http://127.0.0.1:18000/v1','CHESS_ANDROID':'0'});p.start();self.addCleanup(p.stop)
    def test_coach_selects_qwen_without_openai_key(self):
        with patch('coach.llm_coach.OpenAI') as openai:
            coach=LLMCoach()
        self.assertIsInstance(coach.client,QwenClient);openai.assert_not_called()
        self.assertTrue(app.coach_is_configured())
    def test_android_does_not_silently_enable_mac_tunnel_provider(self):
        with patch.dict(os.environ,{'CHESS_ANDROID':'1'}):
            self.assertFalse(app.coach_is_configured())
            with self.assertRaises(RuntimeError):LLMCoach()
    def test_adapter_preserves_json_schema_and_never_returns_reasoning(self):
        response=Mock();response.json.return_value={'choices':[{'message':{'content':'{"reply":"Good thinking."}','reasoning':'hidden'},'finish_reason':'stop'}]}
        with patch('coach.qwen_adapter.requests.post',return_value=response) as post:
            result=QwenClient().create(model='qwen',instructions='Explain chess',input='position',text={'format':{'type':'json_schema','name':'reply','schema':{'type':'object'}}})
        self.assertNotIn('hidden',result.output_text)
        self.assertEqual(post.call_args.kwargs['json']['response_format']['json_schema']['name'],'reply')
    def test_commentary_is_audited_and_never_requests_motion(self):
        event=dict(time=1,status='requested',gameId='AbCd1234',ply=2,classification='good',tier='small')
        demo=Mock();demo.status.return_value={'events':[event]}
        response=Mock();response.json.return_value={'message':{'content':'Keep thinking carefully and enjoy exploring your next move.'}}
        with patch('vbot_commentary.requests.post',return_value=response): result=commentary_for_event(demo,event)
        self.assertEqual(result['source'],'qwen')
        entries=self.journal.audit_entries()
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['record_id'],result['recordId'])
        self.assertIn('Keep thinking',entries[0]['raw_output'])
        self.assertEqual([call[0] for call in demo.method_calls],['status'])
    def test_unverified_event_cannot_trigger_model_or_motion(self):
        demo=Mock();demo.status.return_value={'events':[]}
        with patch('vbot_commentary.requests.post') as post:
            with self.assertRaises(ValueError):commentary_for_event(demo,{'classification':'best'})
        post.assert_not_called()
    def test_launcher_rejects_backend_with_wrong_provider(self):
        path=Path(__file__).resolve().parents[1]/'scripts/qwen_demo_launcher.py'
        spec=importlib.util.spec_from_file_location('qwen_launcher',path);launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
        with patch.object(launcher,'get_json',return_value={'vbotDemo':True,'coach':{'configured':True,'provider':'openai'}}):
            with self.assertRaisesRegex(RuntimeError,'not confirmed as Qwen'):launcher.check_backend()
