"""第三单：统计修复、试标隔离和人工核对边界。"""
import unittest,tempfile,json,hashlib,os
from pathlib import Path
from annotation_store import Store
from annotation_rules import Rules
from pilot_library import Pilot
from repair_reference_outputs import parse_types,full_hash,stable_source_key,normalize_fact,normalize_coarse
ROOT=Path(__file__).resolve().parent.parent
class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.store=Store(self.root/'annotation.sqlite3');self.pilot=Pilot(self.store);self.store.original('a',logical_path='项目/原片.mp4',duration=10)
        tree=json.loads((ROOT/'cutframe-studio/rules/label-tree-v0.2.json').read_text('utf-8'))
        with self.store.db() as c:
            c.execute('CREATE TABLE label_registry(id TEXT PRIMARY KEY,name TEXT,dimension TEXT)')
            c.executemany('INSERT INTO label_registry VALUES(?,?,?)',[(t['id'],t['name'],t['dimension']) for t in tree['labels']])
        ref=self.root/'ref';self.ref=ref;facts=ref/'素材底座项目-20261116/片段库';facts.mkdir(parents=True);frames=ref/'素材标注总纲-20261116/试标50段/frames';frames.mkdir(parents=True);(frames/'seg_01.jpg').write_bytes(b'fixture')
        (facts/'事实层.jsonl').write_text(json.dumps(dict(样例类别='试标50段',来源条目标识='seg_01',镜序素材ID='a',起秒=1,止秒=3)),encoding='utf-8');self.pred=self.root/'predictions.jsonl';self.pred.write_text(json.dumps(dict(sample_id='seg_01',code='V05',model='test-model',max_pixels=262144,prompt_sha256='hash',rule_version='v0.2')),encoding='utf-8')
    def test_predictions_do_not_become_approved_annotations(self):
        rid=self.pilot.import_round('测试轮',self.pred,self.ref);before=self.store.counts();self.assertEqual(before['annotations'],0);self.assertEqual(before['segments'],0);self.assertEqual(self.pilot.import_round('测试轮',self.pred,self.ref),rid);self.assertEqual(before,self.store.counts());item=self.pilot.items(rid)['items'][0];self.assertIsNone(item['review']);self.assertEqual(item['code'],'V05')
    def test_review_validated_versioned_and_round_frozen(self):
        rid=self.pilot.import_round('测试轮',self.pred,self.ref);item=self.pilot.items(rid)['items'][0]
        for code,reviewer in [('V404','审核人'),('V05','')]:
            with self.assertRaises(ValueError):self.pilot.review(item['id'],code,reviewer)
        aid=self.pilot.review(item['id'],'V05','实际审核人',True);before=self.store.counts();self.assertEqual(self.pilot.review(item['id'],'V05','实际审核人',True),aid);self.assertEqual(before,self.store.counts())
        self.pilot.review(item['id'],'V10','实际审核人');updated=self.pilot.items(rid,code='V10');self.assertEqual(updated['total'],1);self.assertEqual(updated['reviewed'],1)
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM annotations WHERE supersedes=?',(aid,)).fetchone()[0],1)
        changed=json.loads(self.pred.read_text('utf-8'));changed['code']='V06';self.pred.write_text(json.dumps(changed),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'冻结'):self.pilot.import_round('测试轮',self.pred,self.ref)
    def test_brackets_counting_and_full_file_hash(self):
        result=parse_types('其他（模糊画面、叠大字等） 5、施工现场·其他 1；备注原样保留')
        self.assertEqual(result,[dict(type='其他',count=5),dict(type='施工现场·其他',count=1)])
        with self.assertRaises(ValueError):parse_types('未知类别没有数量')
        a=self.root/'a.bin';b=self.root/'b.bin';prefix=b'x'*(1024*1024);a.write_bytes(prefix+b'a');b.write_bytes(prefix+b'b');self.assertNotEqual(full_hash(a),full_hash(b));self.assertEqual(hashlib.sha256(a.read_bytes()[:1024*1024]).hexdigest(),hashlib.sha256(b.read_bytes()[:1024*1024]).hexdigest())
        row={'id':'a','start':0,'end':2,'工序':'批刮'};self.assertEqual(stable_source_key(row,1),stable_source_key(dict(row,来源条目标识='旧键已追加'),1))
    def test_new_api_token_required(self):
        if not os.environ.get('CUTFRAME_STATE'):self.skipTest('请使用临时状态运行器')
        from app import app,PORT
        client=app.test_client();r=client.post('/api/pilot/review/no-such-item',json={},headers={'Host':f'127.0.0.1:{PORT}'});self.assertEqual(r.status_code,403)
    def test_upstream_repairs_are_idempotent(self):
        fact=dict(事实编号='F0018',来源文件='x',内容={'product_identity':'本片段不是微陶泥（用户确认）'},是否反例=False)
        fixed=normalize_fact(fact);self.assertTrue(fixed['是否反例']);self.assertEqual(fixed,normalize_fact(fixed))
        coarse=dict(记录种类='施工镜头',原字段={'id':'a','start':0,'end':2,'工序':'批刮'},来源条目标识='旧键')
        fixed=normalize_coarse(coarse,12);self.assertEqual(fixed,normalize_coarse(fixed,12))
        purpose=dict(记录种类='用途片段',粗标编号='C0001',来源条目标识='a:0-2')
        fixed=normalize_coarse(purpose);self.assertEqual(fixed,normalize_coarse(fixed))
if __name__=='__main__':unittest.main()
