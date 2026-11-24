import json,sqlite3,tempfile,unittest
from pathlib import Path
from annotation_store import Store
from import_machine_annotations import import_machine
class MachineImportTests(unittest.TestCase):
    def test_W10_idempotent_small_refs_unreviewed_and_preserve_human(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);s=Store(p/'annotation.sqlite3');s.original('a',duration=10);sid=s.create('a',0,4);s.annotate(sid,dict(source='人工',dimension='画面类型',labels=['V05'],review_status='人工确认',reviewer='甲'))
            before=s.get(sid);catalog=p/'catalog.sqlite3';c=sqlite3.connect(catalog);c.execute('CREATE TABLE assets(id TEXT)');c.execute("INSERT INTO assets VALUES('a')");c.commit();c.close()
            row=dict(范围='范围内',镜序素材ID='a',起秒=0,止秒=4,记录种类='分时段',来源文件='s',来源条目标识='1',对应总纲标签=['V05'],原字段={'description':'批刮描述','可按微陶泥选用':True},人工核对标记=True)
            rows=[row,dict(row,来源条目标识='2',对应总纲标签=['V05','V06'],原字段={'description':'两个类型','可按微陶泥选用':False}),dict(row,范围='范围外'),dict(row,镜序素材ID=''),dict(row,起秒=None),dict(row,止秒=11),dict(row,镜序素材ID='missing')]
            src=p/'粗标.jsonl';src.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in rows),encoding='utf-8');one=import_machine(s,src,catalog);two=import_machine(s,src,catalog)
            self.assertEqual(one['table_counts'],two['table_counts']);self.assertEqual(one['imported_rows'],2);self.assertEqual(sum(one['skipped'].values()),5);self.assertEqual(one['type_annotations'],1);self.assertEqual(one['material_annotations'],1);self.assertEqual(two['unchanged_rows'],2)
            after=s.get(sid);self.assertEqual(after['ranges'],before['ranges']);self.assertEqual(after['annotations'][0],before['annotations'][0]);self.assertEqual(s.counts()['segments'],1)
            machine=[a for a in after['annotations'] if a['source']=='机器'];self.assertTrue(all(a['review_status']=='未审' for a in machine));self.assertTrue(all('description' not in json.loads(a['raw']) for a in machine))
            with s.db() as c:self.assertEqual(c.execute('SELECT text FROM machine_descriptions ORDER BY id LIMIT 1').fetchone()[0],'批刮描述')
