"""在正式表的临时副本上检查待标注、定向修订和原始记录保护。"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import structured_entry as entry
import structured_selection as model


class CopyLabelChannels(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parent.parent
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'文案结构化标注.xlsx'
        self.source=model.book_path(self.root)
        shutil.copyfile(self.source,self.path)
        mock_path=patch.object(model,'book_path',return_value=self.path)
        mock_path.start()
        self.addCleanup(mock_path.stop)

    def tables(self):
        return model.read_tables(self.path,self.path.stat().st_mtime_ns)

    def test_queue_is_separate_and_idempotent(self):
        original=self.tables()['逐条标注']
        existing=self.tables().get('待标注',[])
        self.assertTrue(entry.enqueue_pending(self.root,'试标水槽1.5米','测试成员甲'))
        stamp=self.path.stat().st_mtime_ns
        self.assertFalse(entry.enqueue_pending(self.root,'试标水槽1.5米。','另一位成员'))
        self.assertEqual(stamp,self.path.stat().st_mtime_ns)
        self.assertTrue(entry.enqueue_pending(self.root,'试标水槽15米','另一位成员'))
        self.assertEqual(self.tables()['逐条标注'],original)
        queued=self.tables()['待标注']
        self.assertEqual(queued[:len(existing)],existing)
        self.assertEqual([r['提交人'] for r in queued[len(existing):]],['测试成员甲','另一位成员'])
        with self.assertRaises(ValueError):entry.enqueue_pending(self.root,original[0]['代表句'],'测试成员甲')
        self.assertEqual(self.path.with_name('文案结构化标注_首次人工入表前备份.xlsx').read_bytes(),self.source.read_bytes())
        with ZipFile(self.path) as out, ZipFile(self.source) as src:
            self.assertIsNone(out.testzip())
            self.assertEqual(out.read('xl/worksheets/sheet1.xml'),src.read('xl/worksheets/sheet1.xml'))

    def test_revision_audited_atomically_and_visible_to_matching(self):
        before=self.tables()['逐条标注']
        ident='P0005'
        d=entry.edit_draft(self.root,ident)
        cat=next(k for k in d['categories'] if k!=d['form']['category'])
        form=dict(d['form'],category=cat,primary='V12',alternative='V04',
                  action='本次测试可见动作',limit='本次测试限制')
        entry.revise(self.root,ident,d['version'],form,'测试审核员')
        after=self.tables()['逐条标注']
        self.assertEqual([r for r in before if r['观点ID']!=ident],[r for r in after if r['观点ID']!=ident])
        stored=model.dataset(self.root)[0][ident][0]
        self.assertEqual(stored['必须看见的动作'],form['action'])
        self.assertEqual(stored['类别规则']['类别条件编号'],cat)
        self.assertEqual(model.codes(stored['主画面类型']),['V12'])
        self.assertEqual(model.codes(stored['备选画面类型']),['V04'])
        self.assertEqual(stored['标注状态'],'人工确认')
        log=self.tables()['人工修订记录']
        self.assertEqual(len(log),1)
        self.assertEqual(log[0]['修改人'],'测试审核员')
        self.assertIn('V03',json.loads(log[0]['修改前'])['主画面类型'])
        self.assertIn('V12',json.loads(log[0]['修改后'])['主画面类型'])
        with self.assertRaises(ValueError):entry.revise(self.root,ident,d['version'],form,'测试审核员')
        recent=entry.edit_draft(self.root,ident)
        with self.assertRaises(ValueError):
            entry.revise(self.root,ident,recent['version'],dict(form,alternative='V12'),'测试审核员')
        entry.revise(self.root,ident,recent['version'],recent['form'],'测试审核员')
        self.assertEqual(str(self.path.stat().st_mtime_ns),recent['version'])


class DeployedPictureDictionary(unittest.TestCase):
    def test_revision_without_legacy_clean_workbook(self):
        source=Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            book=model.book_path(root)
            book.parent.mkdir(parents=True)
            shutil.copyfile(model.book_path(source),book)
            clean=entry.default_clean_book(root)
            shutil.copyfile(entry.default_clean_book(source),clean)
            ident='P0289'
            draft=entry.edit_draft(root,ident)
            original=draft['form']['action']
            form=dict(draft['form'],action='隔离副本：核对厨房台面。')
            entry.revise(root,ident,draft['version'],form,'副本验收')
            verified=entry.edit_draft(root,ident)
            self.assertEqual(verified['form']['action'],form['action'])
            # 检索源显式指定了另一张字典时，修订也从该来源读取。
            override=clean.with_name('实际检索使用的清洗表.xlsx')
            clean.rename(override)
            entry.revise(root,ident,verified['version'],dict(form,action=original),
                         '副本验收',clean_book=override)
            rows=model.read_tables(book,book.stat().st_mtime_ns)['人工修订记录']
            self.assertEqual([r['观点ID'] for r in rows[-2:]],[ident,ident])
            self.assertEqual(entry.edit_draft(root,ident)['form']['action'],original)


if __name__=='__main__':
    unittest.main()
