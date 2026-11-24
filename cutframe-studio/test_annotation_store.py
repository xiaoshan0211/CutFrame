"""V2–V6：真实SQLite事务、历史和库级约束；只用临时状态。"""
import os,unittest,tempfile,sqlite3,json
from pathlib import Path
from annotation_store import Store
class AnnotationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'annotation.sqlite3');self.store.original('a',duration=10)
    def test_V2_V3_unique_original_ranges_multiple_facts(self):
        s=self.store;s.original('a',duration=10);a=s.create('a',0,2);b=s.create('a',2,4)
        self.assertNotEqual(a,b);self.assertEqual(a,s.create('a',0,2))
        s.annotate(a,{'evidence':'来源一'});s.annotate(a,{'evidence':'来源二'})
        self.assertEqual(len(s.get(a)['annotations']),2);self.assertEqual(len(s.list('a')),2);self.assertEqual(s.counts()['originals'],1)
    def test_V4_invalid_atomic(self):
        s=self.store;before=s.counts()
        for a,b,message in [(-1,2,'起秒不能为负'),(2,2,'止秒必须大于起秒'),(0,11,'止秒超过原片时长'),(0,float('nan'),'有限数字')]:
            with self.assertRaisesRegex(ValueError,message):s.create('a',a,b)
            self.assertEqual(before,s.counts())
    def test_V5_history_and_events(self):
        s=self.store;a=s.create('a',0,3);old=s.get(a)['ranges'][0];s.change_range(a,1,4,'调整','测试人')
        self.assertEqual(old,s.get(a)['ranges'][0])
        ann=s.annotate(a,{'labels':['V05'],'reviewer':'测试人'});s.annotate(a,{'labels':['V06'],'reviewer':'测试人'},supersedes=ann)
        self.assertEqual(s.get(a)['id'],a);self.assertEqual(len(s.get(a)['annotations']),2)
        with s.db() as c:
            events=c.execute("SELECT * FROM events WHERE action IN ('改秒段','改标')").fetchall()
            self.assertEqual(len(events),2)
            for e in events:self.assertIsNotNone(e['before_value']);self.assertIsNotNone(e['after_value'])
    def test_V6_events_append_only(self):
        s=self.store;s.create('a',0,2)
        for sql in ["UPDATE events SET reason='篡改'",'DELETE FROM events']:
            with self.assertRaisesRegex(sqlite3.IntegrityError,'只追加'):
                with s.db() as c:c.execute(sql)
    def test_split_atomic_and_retire(self):
        s=self.store;a=s.create('a',0,8);before=s.counts()
        with self.assertRaises(ValueError):s.split(a,[{'start':0,'end':4},{'start':7,'end':9}])
        self.assertEqual(before,s.counts());children=s.split(a,[{'start':0,'end':4},{'start':4,'end':8}]);self.assertEqual(len(children),2)
        self.assertEqual(s.get(a)['status'],'废弃');self.assertTrue(all(x['split_from']==a for x in children))
    def test_duration_required_and_import_unchecked(self):
        s=self.store;s.original('b')
        with self.assertRaisesRegex(ValueError,'时长'):s.create('b',0,2)
        a=s.create('b',0,2,allow_unknown=True);self.assertEqual(s.get(a)['ranges'][0]['duration_unchecked'],1)
    def test_http_token_and_metadata_failure(self):
        if not os.environ.get('CUTFRAME_STATE'):self.skipTest('需run_tests隔离环境')
        from app import app,PORT,TOKEN
        from unittest.mock import patch
        store=app.extensions['annotation_store'];client=app.test_client();headers={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN}
        self.assertEqual(client.post('/api/annotation/segments',json={}).status_code,403)
        with patch('app.get_asset',return_value={'rel':'test'}),patch('app.metadata',side_effect=ValueError('不可读')):
            before=store.counts();r=client.post('/api/annotation/segments',json={'asset_id':'missing','start':0,'end':2},headers=headers)
            self.assertEqual(r.status_code,400);self.assertEqual(before,store.counts())
if __name__=='__main__':unittest.main()
