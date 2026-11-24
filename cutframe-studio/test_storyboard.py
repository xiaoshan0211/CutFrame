# -*- coding: utf-8 -*-
import os,unittest
if not os.environ.get('CUTFRAME_STATE'):raise RuntimeError('使用 run_tests.py 隔离测试')
from app import app,TOKEN,PORT
class StoryboardTests(unittest.TestCase):
    def test_draft_roundtrip_and_invalid_times(self):
        c=app.test_client();h={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN}
        board={'version':1,'enabled':True,'tasks':[{'id':'a','text':'武汉','need':'现场讲解','role':'话题开场','start':0,'end':2}],'candidates':[],'confirmed':None}
        p={'name':'隔离选片工程','shots':[],'imports':{},'settings':{},'workflow':{'script':'武汉','storyboard':board}}
        r=c.post('/api/projects',json=p,headers=h);self.assertEqual(r.status_code,200,r.json)
        saved=c.get('/api/projects/'+r.json['id'],headers=h).json
        self.assertEqual(saved['workflow']['storyboard'],board)
        board['tasks'][0]['start']=-1
        self.assertEqual(c.post('/api/projects',json=p,headers=h).status_code,400)
