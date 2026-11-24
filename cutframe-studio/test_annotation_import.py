import unittest,tempfile,json,sqlite3,contextlib
from pathlib import Path
from annotation_store import Store
from import_annotation_library import import_library,structured
class AnnotationImportTests(unittest.TestCase):
    def test_V2_V7_idempotence_changed_source_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'inputs';source.mkdir();catalog=root/'catalog.sqlite3'
            with contextlib.closing(sqlite3.connect(catalog)) as c, c:c.execute('CREATE TABLE assets(id TEXT PRIMARY KEY)');c.execute("INSERT INTO assets VALUES('a')")
            originals=[{'原片ID':'orig','镜序素材ID':'a','时长':10},{'原片ID':'not-registered','镜序素材ID':'','时长':3}]
            facts=[{'事实编号':'F1','来源文件':'source','来源条目标识':'one','镜序素材ID':'a','起秒':0,'止秒':2,'确认状态':'已确认','确认人':'当前用户','内容':{},'是否反例':True},{'事实编号':'F2','来源文件':'source','来源条目标识':'two','镜序素材ID':'a','起秒':None,'止秒':2,'确认人':'','内容':{}}]
            restrictions=[{'规则ID':'R','来源文件':'restriction','来源条目标识':'R','禁用原文':'阿姨不要用','主库相对路径':'目录'}]
            def write():
                for file,data in [('原片表.jsonl',originals),('事实层.jsonl',facts),('禁用表.jsonl',restrictions)]: (source/file).write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in data),encoding='utf-8')
            write();store=Store(root/'annotation.sqlite3');one=import_library(store,source,catalog);two=import_library(store,source,catalog)
            self.assertEqual(one['table_counts'],two['table_counts']);self.assertEqual(one['segment_fact_count']+one['clue_fact_count'],2)
            self.assertEqual(one['table_counts']['clues'],2);self.assertEqual(one['original_unregistered'],['not-registered']);self.assertEqual(one['segment_negative_facts'],1);self.assertEqual(one['table_counts']['restrictions'],1)
            facts[0]['限定语原文']='新增依据';write();three=import_library(store,source,catalog)
            self.assertEqual(three['table_counts']['segments'],1);self.assertEqual(three['table_counts']['source_records'],6)
            annotations=store.list('a')[0]['annotations'];self.assertEqual(len(annotations),2);self.assertEqual(annotations[-1]['supersedes'],annotations[0]['id'])
    def test_audited_type_uses_fix_and_preserves_negative_fact(self):
        self.assertEqual(structured({'样例类别':'试标50段','内容':{'审核结果':{'verdict':'错','机器画面类型':'V06','fix':'V10'}}}),[('画面类型','V10',False,'人工审核')])
        self.assertEqual(structured({'样例类别':'试标50段','内容':{'审核结果':{'verdict':'对','机器画面类型':'V05'}}}),[('画面类型','V05',False,'人工审核')])
    def test_overlapping_identity_conflicts_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'inputs';source.mkdir();catalog=root/'catalog.sqlite3'
            with contextlib.closing(sqlite3.connect(catalog)) as c, c:c.execute('CREATE TABLE assets(id TEXT)');c.execute("INSERT INTO assets VALUES('a')")
            originals=[{'原片ID':'orig','镜序素材ID':'a','时长':10},{'原片ID':'not-registered','镜序素材ID':'','时长':3}]
            facts=[dict(事实编号='F1',来源文件='s',来源条目标识='1',镜序素材ID='a',起秒=0,止秒=4,确认状态='已确认',确认人='甲',内容={'identities':['阿文']}),dict(事实编号='F2',来源文件='s',来源条目标识='2',镜序素材ID='a',起秒=2,止秒=6,确认状态='已确认',确认人='乙',内容={'person_identity':'不是阿文'},是否反例=True)]
            for file,data in [('原片表.jsonl',originals),('事实层.jsonl',facts),('禁用表.jsonl',[])]: (source/file).write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in data),encoding='utf-8')
            store=Store(root/'annotation.sqlite3');report=import_library(store,source,catalog)
            self.assertEqual(len(report['conflicts']),1);self.assertEqual(store.counts()['segments'],2)
            for segment in store.list('a'):
                self.assertTrue(any('冲突待确认' in json.loads(a['flags']) and a['review_status']=='待确认' for a in segment['annotations']))
if __name__=='__main__':unittest.main()
