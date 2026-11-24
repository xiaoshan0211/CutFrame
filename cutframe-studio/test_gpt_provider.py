import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from gpt_provider import load_rules, reserve, budget_status, budget_db, BudgetStop, validate_segments, call_gpt
from gpt_worker import discover


class GPTTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.rule=load_rules(Path(__file__).with_name('gpt-retrieval-rules.json'))
        self.ledger=self.root/'ledger.db'

    def tearDown(self):self.tmp.cleanup()

    def test_rule_reload_and_authorization(self):
        p=self.root/'rules.json';r=dict(self.rule);r['instructions']=r['instructions']+['新增判断要求'];p.write_text(json.dumps(r),encoding='utf-8')
        self.assertNotEqual(load_rules(p)['hash'],self.rule['hash'])
        r['budget']=dict(r['budget'],total_cap_usd=200);p.write_text(json.dumps(r),encoding='utf-8')
        with self.assertRaises(ValueError):load_rules(p)

    def test_budget_pending_and_total(self):
        self.rule['budget']['total_cap_usd'] = .16
        cid=reserve(self.ledger,self.rule,{})
        with self.assertRaises(BudgetStop):reserve(self.ledger,self.rule,{})
        with budget_db(self.ledger) as db:db.execute('UPDATE calls SET pending=0 WHERE id=?',(cid,))
        cid=reserve(self.ledger,self.rule,{})
        with budget_db(self.ledger) as db:db.execute('UPDATE calls SET pending=0 WHERE id=?',(cid,))
        with self.assertRaises(BudgetStop):reserve(self.ledger,self.rule,{})
        self.assertLess(budget_status(self.ledger,self.rule)['remaining_usd'],.001)

    def test_exact_range_unknown_and_nan(self):
        good=dict(start=1,end=3,match=True,uncertain=False,evidence='抹刀接触墙面',actions=['批刮'])
        rows=[good,dict(good,start=float('nan')),dict(good,end=2),dict(good,uncertain=True),dict(good,start=0)]
        self.assertEqual(validate_segments({'segments':rows},1,3,2),[good])

    def test_api_payload_no_video_and_cost(self):
        image=self.root/'f.jpg';Image.new('RGB',(40,40)).save(image)
        def transport(body):
            self.assertFalse(body['store']);self.assertEqual(body['model'],'gpt-6.1-sol')
            self.assertIn('data:image/jpeg;base64,',str(body));self.assertNotIn(str(image),str(body))
            return {'usage':{'input_tokens':1000,'output_tokens':100},'id':'mock','output':[{'content':[{'type':'output_text','text':'{"segments":[]}'}]}]}
        prediction,data=call_gpt(self.rule,self.ledger,'not-real',[{'path':image,'time':0}],{},0,2,{},transport)
        self.assertEqual(prediction,{'segments':[]});self.assertAlmostEqual(data['cost_estimate_usd'],.003)
        self.assertEqual(budget_status(self.ledger,self.rule)['pending'],0)

    def test_api_failure_keeps_reservation(self):
        def bad(body):raise OSError('secret details')
        with self.assertRaisesRegex(ValueError,'GPT请求失败'):
            call_gpt(self.rule,self.ledger,'not-real',[],{},0,2,{},bad)
        self.assertEqual(budget_status(self.ledger,self.rule)['pending'],1)

    def request(self):
        f=self.root/'a.mp4';f.write_bytes(b'test')
        return dict(gpt_rules=self.rule,duration=2,catalog=[dict(id='a',root='raw',rel='a.mp4',name='a.mp4')],text='批刮墙面',home=str(self.root),run_id='test',round=1,roots={'raw':str(self.root)},ffprobe='mock',ffmpeg='mock',ledger=str(self.ledger))

    def fake_frames(self,binary,source,s,e,folder):
        folder.mkdir(parents=True,exist_ok=True);p=folder/'f.jpg';Image.new('RGB',(40,40)).save(p)
        return [{'path':str(p),'time':s+(e-s)*i/8} for i in range(8)]

    def test_coarse_then_fixed_verification(self):
        req=self.request();calls=[]
        def caller(rule,ledger,key,fs,query,s,e,metadata):
            calls.append((s,e));return {'segments':[dict(start=s,end=e,match=True,uncertain=False,actions=['批刮'],surface='墙面',evidence='抹刀铺展材料')]},{'seconds':1,'cost_estimate_usd':.001}
        with patch('gpt_worker.probe',return_value={'width':1080,'height':1920,'duration':12}),patch('gpt_worker.frames',side_effect=self.fake_frames):
            result=discover(req,self.root,caller,lambda home:'mock')
        self.assertEqual(calls,[(0,8),(0,2)])
        self.assertEqual(len(result['items']),1);self.assertEqual(result['items'][0]['end'],2)
        self.assertEqual(result['rule_hash'],self.rule['hash'])

    def test_unknown_identity_no_charge_and_no_old_sample_fallback(self):
        req=self.request();req['text']='成都阿文'
        def forbidden(*a):raise AssertionError('不得调用API')
        result=discover(req,self.root,forbidden,forbidden)
        self.assertEqual(result['calls'],0);self.assertIn('待核实',result['stop_reason'])

    def test_landscape_and_history_excluded(self):
        req=self.request()
        with patch('gpt_worker.probe',return_value={'width':1920,'height':1080,'duration':12}):
            result=discover(req,self.root,lambda *a:self.fail('横屏不得调用'),lambda *a:self.fail())
        self.assertEqual(result['items'],[]);self.assertEqual(result['examined_assets'],['a'])
        req['exclude_assets']=['a']
        with patch('gpt_worker.probe',side_effect=AssertionError('已展示不得重查')):
            self.assertEqual(discover(req,self.root)['checked'],0)

    def test_failed_verification_does_not_return_candidate(self):
        req=self.request();calls=[]
        def caller(rule,ledger,key,fs,query,s,e,metadata):
            calls.append(1)
            rows=[] if '复查' in query['phase'] else [dict(start=s,end=e,match=True,uncertain=False,actions=['批刮'],evidence='粗查')]
            return {'segments':rows},{'seconds':1,'cost_estimate_usd':.001}
        with patch('gpt_worker.probe',return_value={'width':1080,'height':1920,'duration':2}),patch('gpt_worker.frames',side_effect=self.fake_frames):
            result=discover(req,self.root,caller,lambda home:'mock')
        self.assertEqual(len(calls),2);self.assertEqual(result['items'],[])


if __name__=='__main__':unittest.main()
