import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_store import connect,now
from ai_knowledge import import_confirmed,snapshot,select_experience,validate_draft
from gpt_worker import discover
from gpt_provider import load_rules,call_gpt
from test_gpt_provider import GPTTests


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'learning.db'
    def tearDown(self):
        import gc;gc.collect();self.tmp.cleanup()
    def add(self,id,kind='team',status='approved',**extra):
        p=dict(kind=kind,scope='similar',description=id,**extra)
        with connect(self.db) as db:db.execute('INSERT INTO rules VALUES(?,?,?,?,?,?)',(id,now(),'',status,'审核人',json.dumps(p)))
    def test_import_exact_and_idempotent(self):
        folder=self.root/'labels';folder.mkdir()
        rows=[dict(sample_id='R01',source=dict(id='a',start=2,end=6),confirmed_by='用户',confirmation_evidence='前景阿文，后方其他人物',person_targets=[{'description':'前景','identity':'阿文'},{'description':'后方','identity':'其他人物'}])]
        (folder/'person-01.json').write_text(json.dumps({'rows':rows}),'utf-8')
        (folder/'person-01.before-confirmation.json').write_text(json.dumps({'rows':[dict(rows[0],sample_id='wrong')]}),'utf-8')
        self.assertEqual(import_confirmed(folder,self.db),['confirmed-R01']);self.assertEqual(import_confirmed(folder,self.db),[])
        with connect(self.db) as db:k=snapshot(db,'p','甲')
        self.assertEqual(k['facts'][0]['identities'],['阿文'])
        self.assertEqual(len(select_experience(k,'a',2,6,'')),1)
        self.assertEqual(select_experience(k,'a',1,6,''),[])
        self.assertEqual(select_experience(k,'same-folder-other',2,6,''),[])
    def test_review_owner_keywords_and_switch(self):
        self.add('team',keywords=['批刮']);self.add('pending',status='pending')
        self.add('mine','personal',owner='甲');self.add('other','personal',owner='乙')
        self.add('fact','fact',asset_id='old',start=0,end=2)
        with connect(self.db) as db:
            k=snapshot(db,'p','甲');off=snapshot(db,'p','甲',False)
        self.assertEqual({r['id'] for r in select_experience(k,'new',0,2,'批刮墙面')},{'team','mine'})
        self.assertEqual({r['id'] for r in select_experience(k,'new',0,2,'清洁')},{'mine'})
        self.assertEqual(select_experience(off,'new',0,2,'批刮'),[])
        self.assertEqual(len(select_experience(off,'old',0,2,'批刮')),1)
        with connect(self.db) as db:
            db.execute("UPDATE rules SET status='disabled' WHERE id='team'")
            changed=snapshot(db,'p','甲')
        self.assertNotEqual(k['hash'],changed['hash'])
    def test_new_source_real_request_includes_approved_general_not_old_fact(self):
        self.add('team',keywords=['批刮']);self.add('mine','personal',owner='甲');self.add('pending',status='pending')
        self.add('fact','fact',asset_id='old',start=0,end=10,confirmed_by='用户',evidence='旧片段')
        with connect(self.db) as db:k=snapshot(db,'p','甲')
        self.rule=load_rules(Path(__file__).with_name('gpt-retrieval-rules.json'));self.ledger=self.root/'ledger.db'
        req=GPTTests.request(self);req['knowledge']=k;req['reviewer']='甲';seen=[]
        def caller(rule,ledger,key,fs,query,s,e,metadata):
            def transport(body):
                message=body['input'][0]['content'][0]['text'];actual=json.loads(message[message.index('{'):])['task'];seen.append(actual)
                self.assertNotIn(str(self.root),json.dumps(body))
                prediction={'segments':[dict(start=s,end=e,match=True,uncertain=False,actions=['批刮'],surface='墙面',evidence='模拟检查')]}
                return {'usage':{'input_tokens':100,'output_tokens':50},'id':'mock','output':[{'content':[{'type':'output_text','text':json.dumps(prediction)}]}]}
            return call_gpt(rule,ledger,key,fs,query,s,e,metadata,transport)
        with patch('gpt_worker.probe',return_value={'width':1080,'height':1920,'duration':2}),patch('gpt_worker.frames',side_effect=lambda *a:GPTTests.fake_frames(self,*a)):
            result=discover(req,self.root,caller,lambda h:'mock')
        self.assertEqual(len(seen),2)
        for q in seen:self.assertEqual({r['id'] for r in q['approved_experience']},{'team','mine'})
        self.assertEqual(result['experience_used'],['mine','team'])
        log=json.loads((self.root/'gpt-decisions.jsonl').read_text('utf-8').splitlines()[0]);self.assertEqual(log['knowledge_hash'],k['hash'])
    def test_confirmed_source_bounds_and_identity_used(self):
        self.rule=load_rules(Path(__file__).with_name('gpt-retrieval-rules.json'));self.ledger=self.root/'ledger.db'
        req=GPTTests.request(self);req['text']='阿文讲述';req['source_mode']='confirmed'
        fact=dict(id='R',kind='fact',asset_id='a',start=2,end=4,identities=['阿文'],confirmed_by='用户',evidence='仅前景阿文',person_targets=[{'description':'前景','identity':'阿文'},{'description':'后方','identity':'其他人物'}])
        req['knowledge']={'facts':[fact],'general':[],'hash':'test'};seen=[]
        def caller(rule,ledger,key,fs,query,s,e,metadata):
            seen.append((s,e,query));return {'segments':[dict(start=s,end=e,match=True,uncertain=False,actions=['讲述'],evidence='模拟确认')]},{'seconds':0,'cost_estimate_usd':0}
        with patch('gpt_worker.probe',return_value={'width':1080,'height':1920,'duration':20}),patch('gpt_worker.frames',side_effect=lambda *a:GPTTests.fake_frames(self,*a)):
            result=discover(req,self.root,caller,lambda h:'mock')
        self.assertEqual([(s,e) for s,e,q in seen],[(2,4),(2,4)])
        self.assertEqual(len(seen[0][2]['identity_evidence']['person_targets']),2)
        self.assertEqual(result['items'][0]['source_mode'],'confirmed')
    def test_personal_requires_owner_and_no_forged_fact_draft(self):
        with self.assertRaises(ValueError):validate_draft({'kind':'personal','description':'喜欢近景','scope':'similar'},'')
        with self.assertRaises(ValueError):validate_draft({'kind':'fact','description':'目录全是阿文'},'p')


if __name__=='__main__':unittest.main()
