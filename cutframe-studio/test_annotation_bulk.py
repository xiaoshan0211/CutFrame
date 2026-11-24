import copy,json,tempfile,unittest
from pathlib import Path
from annotation_store import Store
from annotation_rules import Rules,validate,QUALIFIED
class BulkTests(unittest.TestCase):
    def test_W9_same_raw_same_group_preserve_manual_explanation_events(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Store(Path(folder)/'a.sqlite3');rules=Rules(s);tree=json.loads((Path(__file__).parent/'rules/label-tree-v0.2.json').read_text('utf-8'))
            def row(status='未结构化',raw='完全相同原文'):return dict(dimension='画面类型',tags=[],raw=raw,notes='',structure_status=status)
            content=dict(label_tree=tree,rules=[])
            for i in range(4):content['rules'].append(dict(id=str(i),suite='s',text='字幕',target_duration=1,illustration_only=True,unprovable='',notes='',must=[row()],prefer=[row()],forbid=[]))
            content['rules'][0]['must'][0].update(tags=['V05'],structure_status='人工编辑')
            content['rules'][2]['must'][0].update(tags=['V10'],structure_status='人工编辑')
            content['rules'][3]['must'][0]['raw']='完全相同原文 '
            p=rules.create(content);pending=rules.pending(p['id']);self.assertEqual(pending[0]['count'],5)
            r=rules.apply_same(p['id'],'0','must',0,False,p['content_hash']);self.assertEqual(r['applied'],1);p=r['package']
            self.assertEqual(p['content']['rules'][2]['must'][0]['tags'],['V10']);self.assertEqual(p['content']['rules'][1]['prefer'][0]['tags'],[])
            r=rules.apply_same(p['id'],'0','must',0,True,p['content_hash']);self.assertEqual(r['applied'],2);p=r['package']
            c=copy.deepcopy(p['content']);c['rules'][0]['must'][0].update(explanation_only=True,tags=[]);p=rules.save(p['id'],c,p['content_hash'])
            p=rules.apply_same(p['id'],'0','must',0,True,p['content_hash'])['package'];self.assertTrue(p['content']['rules'][1]['must'][0]['explanation_only'])
            self.assertFalse(any(i['rule_id']=='0' and i['group']=='must' for i in validate(p['content'])))
            self.assertEqual(p['content']['rules'][1]['must'][0]['raw'],'完全相同原文')
            with s.db() as db:
                events=db.execute("SELECT after_value FROM events WHERE action='按相同原文套用'").fetchall();self.assertEqual(len(events),3);self.assertEqual(json.loads(events[0][0])['count'],1)
            with self.assertRaisesRegex(ValueError,'变化'):rules.apply_same(p['id'],'0','must',0,False,'过期哈希')
