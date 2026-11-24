"""通过真实 HTTP 接口操作临时工作簿，正式文件只读。"""
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import structured_entry
import structured_selection as book
import test_slot_review as fixtures


class EntryTests(unittest.TestCase):
    def test_lookup_pending_and_revise_through_member_routes(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / '文案结构化标注.xlsx'
            shutil.copyfile(book.book_path(root), copy)
            with patch.object(book, 'book_path', return_value=copy):
                host = fixtures.SlotReviewTests()
                with patch.object(host, 'first_round'):
                    host.setUp()
                self.addCleanup(host.doCleanups)

                def post(route, data, scope='all'):
                    with host.app.test_client() as client:
                        return client.post('/api/local/' + route, json=data, headers={'X-Material-Scope': scope})

                new = dict(text='独立验收铜铆钉样板署名甲乙', reviewer='测试员')
                stamp = copy.stat().st_mtime_ns
                for route in ('annotation-auto', 'viewpoint'):
                    result = post(route, new)
                    self.assertEqual(result.status_code, 200, result.json)
                    self.assertEqual(result.json['annotation_targets'], [])
                    self.assertFalse(result.json['annotation_pending'])
                self.assertEqual(copy.stat().st_mtime_ns, stamp)
                with ThreadPoolExecutor(2) as pool:
                    records = list(pool.map(lambda scope: post('annotation-pending', new, scope).json, ('all', 'aliyun-import')))
                self.assertEqual(sorted(rec['created'] for rec in records), [False, True])
                view = post('viewpoint', new).json
                self.assertTrue(view['annotation_pending'])
                self.assertFalse(view['entry_id'])
                q = dict(text='现在武汉出现了一支专业翻新团队', id='P0005', reviewer='测试员')
                self.assertEqual(post('annotation-pending', q).status_code, 400)
                self.assertEqual(post('annotation-edit', dict(q, id='P0262')).status_code, 400)
                edit = post('annotation-edit', q).json
                old_view = post('viewpoint', q).json
                self.assertEqual(edit['id'], q['id'])
                form = dict(edit['form'], primary='V04', alternative='V02', action='画面可见安装水管')
                data = dict(q, version=edit['version'], form=form)
                saved = post('annotation-revise', data)
                self.assertEqual(saved.status_code, 200, saved.json)
                self.assertEqual(saved.json['view']['primary'], ['V04'])
                self.assertEqual(saved.json['view']['action'], form['action'])
                self.assertNotEqual(old_view['annotation_revision'], saved.json['view']['annotation_revision'])
                self.assertEqual(post('annotation-revise', dict(data, id='P0262')).status_code, 400)
                self.assertEqual(post('viewpoint', q, 'aliyun-import').json['primary'], ['V04'])
                self.assertEqual(post('annotation-revise', dict(data, form=dict(form, primary='V01'))).status_code, 400)

    def test_existing_alias_new_and_stale_draft(self):
        root=Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp:
            copy=Path(temp)/'草稿验收.xlsx'
            shutil.copyfile(book.book_path(root),copy)
            with patch.object(book,'book_path',return_value=copy):
                # 即使正式表后来已被人工补全，也保持本测试的缺标前提。
                rows=book.read_tables(copy,copy.stat().st_mtime_ns)['逐条标注']
                pos,row=next((i,r) for i,r in enumerate(rows,2) if r['观点ID']=='P0262')
                row=dict(row,主画面类型='',标注状态='待人定类型')
                structured_entry.replace_row(copy,pos,list(row.values()),str(copy.stat().st_mtime_ns))
                host=fixtures.SlotReviewTests()
                with patch.object(host,'first_round'):
                    host.setUp()
                self.addCleanup(host.doCleanups)
                def post(route,data,scope='all'):
                    return host.client.post('/api/local/'+route,json=data,headers={'X-Material-Scope':scope})
                existing=dict(text='卫生间真的不需要过度翻新了',trailing=['传统翻新只会砸掉瓷砖'])
                with ZipFile(copy) as z:before={i:z.read(i) for i in z.namelist()}
                version=copy.stat().st_mtime_ns
                draft=post('annotation-draft',existing,'aliyun-import').json
                self.assertEqual((draft['id'],draft['form']['primary']),('P0262','V12'))
                alias=post('viewpoint',dict(text='传统翻新只会砸掉瓷砖')).json
                self.assertEqual((alias['id'],alias['primary']),('P0263',['V08']))
                self.assertNotEqual(post('viewpoint',dict(text='传统翻新不会砸掉瓷砖')).json['id'],'P0263')
                new=dict(text='试标专用玻璃隔断铭牌甲乙')
                pending=post('annotation-draft',new).json
                self.assertEqual(pending['id'],'')
                self.assertEqual(copy.stat().st_mtime_ns,version)
                def confirm(query,draft,scope='all'):
                    return post('annotation-confirm',dict(query,id=draft['id'],form=draft['form'],version=draft['version'],reviewer='临时测试'),scope)
                self.assertEqual(confirm(existing,draft,'aliyun-import').json,{'id':'P0262'})
                self.assertEqual(post('viewpoint',existing).json['primary'],['V12'])
                updated=book.read_tables(copy,copy.stat().st_mtime_ns)['逐条标注'][pos-2]
                self.assertEqual(updated['主画面类型'],'V12 · 旧房旧态')
                for k,v in row.items():
                    if k not in ('主画面类型','备选画面类型','标注状态','同类型粗标原片数'):
                        self.assertEqual(updated[k],v,k)
                self.assertEqual(confirm(new,pending).status_code,400)
                pending=post('annotation-draft',new).json
                pending['form'].update(category='T07-23',primary='V12',alternative='V08、V23',action='拍见卫生间隔断上的铭牌',limit='只展示铭牌与隔断位置')
                self.assertEqual(confirm(new,pending).status_code,400)
                self.assertEqual(len(book.dataset(root)[0]),len(rows))
                with ZipFile(copy) as z:
                    self.assertEqual([i for i in before if z.read(i)!=before[i]],['xl/worksheets/sheet1.xml'])
