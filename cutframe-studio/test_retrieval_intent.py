import unittest
from unittest.mock import patch
from test_gpt_provider import GPTTests
from gpt_worker import discover
from retrieval_intent import plan_intent,rank_by_intent,rejection

class IntentTests(GPTTests):
    def test_routes(self):
        self.assertEqual(plan_intent('他就是全武汉女人都想嫁的旧房改造大王')['kind'],'person')
        self.assertEqual(plan_intent('微陶泥批刮覆盖')['kind'],'action')
        self.assertEqual(plan_intent('微陶泥材料桶展示')['kind'],'product')
    def test_people_before_construction(self):
        assets=[dict(id='a',name='旧房.mp4',rel='旧房/施工前处理/旧房.mp4'),dict(id='b',name='人物.mp4',rel='项目/人物出镜/人物.mp4')]
        rows,intent=rank_by_intent(assets,'他就是旧房改造大王')
        self.assertEqual(rows[0]['id'],'b')
    def test_cross_source_and_resume(self):
        req=self.request();req['catalog']=[]
        for key in ['a','b','c']:
            (self.root/(key+'.mp4')).write_bytes(b'test');req['catalog'].append(dict(id=key,root='raw',rel=key+'.mp4',name=key+'.mp4'))
        seen=[]
        def caller(rule,ledger,key,fs,query,s,e,metadata):
            seen.append(metadata['asset_id']);return {'segments':[],'reject_code':'category_mismatch','evidence':'人物低头施工，没有所需动作'},{'seconds':0,'cost_estimate_usd':0}
        with patch('gpt_worker.probe',return_value={'width':1080,'height':1920,'duration':30}),patch('gpt_worker.frames',side_effect=self.fake_frames):
            r=discover(req,self.root,caller,lambda home:'mock')
        self.assertEqual(seen,['a','b','c']);self.assertEqual(len(r['rejections']),3)
        self.assertEqual(len(r['scan_cursors']),3);self.assertEqual(r['examined_assets'],[])
        self.assertTrue(all(x['next']==6 for x in r['scan_cursors'].values()))
    def test_missing_reason_is_not_invented(self):
        self.assertEqual(rejection({'segments':[]},[])[0],'missing_reason')
    def test_product_unknown_blocks_without_call(self):
        req=self.request();req['text']='微陶泥材料桶展示'
        r=discover(req,self.root,lambda *a:self.fail('身份未知不可调用'),lambda *a:self.fail())
        self.assertEqual(r['calls'],0);self.assertIn('待核实',r['empty_reason'])

if __name__=='__main__':unittest.main()
