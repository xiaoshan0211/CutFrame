# -*- coding: utf-8 -*-
import unittest
import os
if not os.environ.get('CUTFRAME_STATE'): raise RuntimeError('请使用 run_tests.py，在独立测试台账运行')
from app import app,TOKEN,PORT
try:
    from subtitle_worker import align
except ModuleNotFoundError as err:
    if err.name != 'opencc':
        raise
    align = None

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client();self.headers={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN}
    def save(self,cues):
        return self.client.post('/api/workflow/subtitles/save',json={'cues':cues},headers=self.headers)
    def test_normalize_and_keep_versions(self):
        a=self.save([dict(start=0,end=1,text='武汉的朋友，')]);b=self.save([dict(start=0,end=1,text='武汉的朋友。')])
        self.assertEqual(a.status_code,200);self.assertNotEqual(a.json['id'],b.json['id'])
        self.assertEqual(a.json['meta']['cues'][0]['text'],'武汉的朋友')
        self.assertEqual(self.client.get('/api/workflow/resources/'+a.json['id'],headers=self.headers).status_code,200)
    def test_reject_overlap_and_controls(self):
        for cues in [[dict(start=0,end=2,text='甲'),dict(start=1,end=3,text='乙')],[dict(start=0,end=1,text='{格式}')],[dict(start=0,end=1,text='第一行\n第二行')]]:
            self.assertEqual(self.save(cues).status_code,400)
    @unittest.skipIf(align is None, '字幕对齐需要 OpenCC')
    def test_alignment_is_not_evenly_distributed(self):
        cues,warnings=align('武汉。你好。',[dict(start=.5,end=1,word='武汉'),dict(start=2,end=3,word='你好')])
        self.assertEqual(cues[1]['start'],2);self.assertEqual(cues[0]['start'],.5);self.assertFalse(warnings)
    @unittest.skipIf(align is None, '字幕对齐需要 OpenCC')
    def test_recognition_omission_keeps_script(self):
        cues,warnings=align('武汉朋友你好',[dict(start=0,end=1,word='武汉你好')])
        self.assertEqual(cues[0]['text'],'武汉朋友你好')
        self.assertEqual((cues[0]['start'],cues[0]['end']),(0,1))
        self.assertTrue(warnings)
    @unittest.skipIf(align is None, '字幕对齐需要 OpenCC')
    def test_missing_clause_end_uses_next_anchor(self):
        cues,warnings=align('从旧房改造，全屋墙面7天搞定。',[
            dict(start=1,end=2,word='从旧房'),dict(start=2.5,end=5,word='全屋墙面七天搞定')])
        self.assertEqual(cues[0]['text'],'从旧房改造')
        self.assertEqual(cues[0]['end'],2.5)
        self.assertEqual(cues[1]['start'],2.5)
        self.assertTrue(warnings)
    @unittest.skipIf(align is None, '字幕对齐需要 OpenCC')
    def test_unanchored_sentence_not_invented(self):
        with self.assertRaises(ValueError):
            align('武汉朋友。欢迎光临。你好。',[dict(start=0,end=1,word='武汉朋友'),dict(start=3,end=4,word='你好')])
    @unittest.skipIf(align is None, '字幕对齐需要 OpenCC')
    def test_keep_complete_clause(self):
        text='先看看墙面现在的情况，再聊聊你想要的颜色和效果。你家最想先改哪个房间？'
        phrases=['先看看墙面现在的情况','再聊聊你想要的颜色和效果','你家最想先改哪个房间']
        words=[dict(start=i*3,end=i*3+2,word=p) for i,p in enumerate(phrases)]
        cues,_=align(text,words)
        self.assertEqual([c['text'] for c in cues],phrases)
        self.assertEqual([(c['start'],c['end']) for c in cues],[(0,2),(3,5),(6,8)])
    def test_no_arbitrary_resources(self):
        self.assertEqual(self.client.get('/api/workflow/resources/missing',headers=self.headers).status_code,400)
