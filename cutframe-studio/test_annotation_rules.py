"""V8–V12：规则失败定位、确认失效、不可变发布和绑定、真实T07原文保留。"""
import unittest,tempfile,json,copy,sqlite3,re
from pathlib import Path
from annotation_store import Store
from annotation_rules import Rules,validate,content_hash,t07_package,stats
ROOT=Path(__file__).resolve().parent.parent
class AnnotationRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(Path(self.temp.name)/'annotation.sqlite3');self.rules=Rules(self.store)
        self.tree=json.loads((ROOT/'cutframe-studio/rules/label-tree-v0.2.json').read_text('utf-8'))
        self.content=dict(schema_version=1,label_tree=self.tree,rules=[dict(id='test-rule',suite='测试套',text='测试原句',must=[dict(dimension='画面类型',tags=['V05'],raw='画面类型：V05',notes='',structure_status='人工编辑')],prefer=[],forbid=[],target_duration=2,illustration_only=True,unprovable='仅示意',notes='')])
    def publish(self,content=None):
        d=self.rules.create(content or self.content);self.rules.confirm(d['id'],'测试确认人');return self.rules.publish(d['id'])
    def test_V8_invalid_types_tags_conflicts_locate_rows(self):
        content=copy.deepcopy(self.content);r=content['rules'][0];r['target_duration']='两秒';r['must'].append(dict(dimension='空间',tags=['V404','V05'],raw='坏行',notes='',structure_status='人工编辑'));r['forbid']=[copy.deepcopy(r['must'][0])]
        draft=self.rules.create(content);issues=validate(content)
        self.assertTrue(any(x['rule_id']=='test-rule' and x['group']=='must' and x['line']==2 and '不存在' in x['message'] for x in issues))
        self.assertTrue(any('不属于' in x['message'] for x in issues));self.assertTrue(any('时长' in x['message'] for x in issues));self.assertTrue(any('矛盾' in x['message'] for x in issues))
        self.rules.confirm(draft['id'],'测试人')
        with self.assertRaisesRegex(ValueError,'校验未通过'):self.rules.publish(draft['id'])
    def test_V9_binding_stays_v1_and_database_immutability(self):
        v1=self.publish();binding=self.rules.bind('task',v1['id']);other=copy.deepcopy(self.content);other['rules'][0]['text']='第二版';v2=self.publish(other)
        self.assertEqual(v2['version'],2);bound=self.rules.bound('task');self.assertEqual(bound['content_hash'],binding['content_hash']);self.assertEqual(bound['content'],v1['content']);self.assertEqual(bound['version'],1)
        for sql in ["UPDATE rule_packages SET name='篡改' WHERE id=?",'DELETE FROM rule_packages WHERE id=?']:
            with self.assertRaisesRegex(sqlite3.IntegrityError,'不可'):
                with self.store.db() as c:c.execute(sql,(v1['id'],))
        with self.assertRaises(ValueError):self.rules.bind('task',v2['id'])
    def test_V10_confirmation_hash_invalidation(self):
        d=self.rules.create(self.content)
        with self.assertRaisesRegex(ValueError,'业务确认'):self.rules.publish(d['id'])
        self.rules.confirm(d['id'],'测试人');changed=copy.deepcopy(self.content);changed['rules'][0]['notes']='内容变化';saved=self.rules.save(d['id'],changed,d['content_hash']);self.assertIsNone(saved['confirmed_by']);self.assertIsNone(saved['confirmed_hash'])
        with self.assertRaisesRegex(ValueError,'业务确认'):self.rules.publish(d['id'])
        with self.assertRaisesRegex(ValueError,'变化'):self.rules.confirm(d['id'],'测试人',d['content_hash'])
    def test_V11_T07_preserves_every_line_draft(self):
        path=ROOT/'参考资料/video-harness-lab-references/素材底座项目-20261116/工位产出/T07/20261117_01/第一条线_逐句对照表.tsv'
        if not path.is_file():self.skipTest('需要原始 99 行 TSV 进行对照')
        package=t07_package(path,self.tree);self.assertEqual(len(package['rules']),99);self.assertEqual(len({r['id'] for r in package['rules']}),99)
        draft=self.rules.create(package);self.assertEqual(draft['status'],'草稿')
        for rule in draft['content']['rules']:
            for group in ('must','prefer','forbid'):self.assertEqual([x['raw'] for x in rule[group]],rule['source_lines'][group])
        report=stats(package);self.assertGreater(report['unstructured_lines'],0)
        # V编号可认出；“包装入镜：无”不能误转成“无任何瑕疵”。
        from annotation_rules import parse_line
        row=parse_line('- 他方品牌包装入镜：无（词表：企业专有）',self.tree);self.assertEqual(row['structure_status'],'未结构化')
    def test_V12_tree_traceability_no_added_unclear(self):

        ids=[x['id'] for x in self.tree['labels']];self.assertEqual(len(ids),len(set(ids)))
        if self.tree.get('source'):
            text=(ROOT/self.tree['source']).read_text('utf-8-sig').split('## 三、维度总表')[1].split('## 四、')[0]
            for label in self.tree['labels']:self.assertIn(label['name'],text)
        self.assertEqual({x['id'] for x in self.tree['labels'] if x['id'].startswith('V')},{f'V{i:02}' for i in range(1,25)})
        for dim in ('部位','人数','角色','朝向'):self.assertFalse(any(x['dimension']==dim and x['name']=='看不清' for x in self.tree['labels']))
        self.assertEqual(validate(self.content),[])
    def test_referenced_label_may_disable_but_not_delete(self):
        draft=self.rules.create(self.content);changed=copy.deepcopy(self.content);changed['label_tree']['labels']=[t for t in changed['label_tree']['labels'] if t['id']!='V05']
        with self.assertRaisesRegex(ValueError,'不能删除'):self.rules.save(draft['id'],changed)
        changed=copy.deepcopy(self.content);next(x for x in changed['label_tree']['labels'] if x['id']=='V05')['enabled']=False;self.rules.save(draft['id'],changed)
        self.assertTrue(any('停用' in x['message'] for x in validate(changed)))
    def test_unstructured_must_and_forbid_block_prefer_allowed(self):
        for group in ('must','forbid'):
            content=copy.deepcopy(self.content);content['rules'][0][group].append(dict(dimension='画面类型',tags=[],raw='只能原样保留',notes='',structure_status='未结构化'));self.assertTrue(any(x['group']==group and '未结构化' in x['message'] for x in validate(content)))
if __name__=='__main__':unittest.main()
