"""使用独立状态目录运行，不能将测试指向正在使用的素材台账。"""
import unittest
import os
if not os.environ.get('CUTFRAME_STATE'): raise RuntimeError('请使用 run_tests.py，在独立测试台账运行')
from app import app,TOKEN,PORT

class TtsTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()
        self.headers={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN}
    def test_reject_empty_and_overlong(self):
        for value in ('','   ','字'*501,None,123):
            r=self.client.post('/api/tts',json={'text':value},headers=self.headers)
            self.assertEqual(r.status_code,400)
    def test_reject_path_in_name(self):
        r=self.client.post('/api/tts',json={'text':'测试','name':'../源目录'},headers=self.headers)
        self.assertEqual(r.status_code,400)
    def test_requires_token(self):
        r=self.client.post('/api/tts',json={'text':'测试'},headers={'Host':f'127.0.0.1:{PORT}'})
        self.assertEqual(r.status_code,403)
    def test_history_and_missing_audio(self):
        r=self.client.get('/api/tts',headers=self.headers)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['items'],[])
        self.assertEqual(self.client.get('/api/voice/not-found',headers=self.headers).status_code,400)

if __name__=='__main__': unittest.main()
