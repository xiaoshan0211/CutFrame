"""临时学习库、真实审核接口、真实 CatBoost 和下次候选。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_slot_review as fixtures
from ranking_feedback import export
from selection_ranker import DATA, INFO, LEGACY, MODEL, candidate_snapshot, train

NEED = '人物面向镜头招呼观众'


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SlotReviewTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.catalog = self.fixture.fixture
        self.client = self.fixture.client
        self.directory = self.fixture.rule_dir
        self.ids = set()

    def asset(self, name, greeting=False):
        sid = self.catalog.asset(name)
        self.catalog.tag(sid, 'V01', human=True)
        self.catalog.tag(sid, 'B5O01' if greeting else 'B5O02', human=True, dim='朝向')
        self.catalog.tag(sid, 'B6H09' if greeting else 'B6H10', human=True, dim='主动作')
        self.ids.add(name)

    def search(self, task, allowed, need=NEED):
        req = dict(self.catalog.req, text='等一下，帮个忙', task_id=task, need=need,
                   conditions={'must':[dict(dimension='画面类型',tags=['V01'])]},
                   exclude_assets=sorted(self.ids-set(allowed)))
        res=self.client.post('/api/local/discover',json=req)
        self.assertEqual(res.status_code,200,res.get_data(as_text=True))
        return res.json

    def submit(self, run, reviews, previous=(), missing=''):
        body=dict(run_id=run['run_id'], reviewer='临时验收',previous=sorted(previous),
                  reviews=reviews,missing=missing)
        return self.client.post('/api/local/slot-batch',json=body)

    def entry(self, slot, good=False, code='动作没发生', fact=None):
        return dict(slot=slot,verdict='采用' if good else '不合适',code='动作发生了' if good else code,
                    fact=fact if fact is not None else '人物面向镜头抬手招呼' if good else '人物在门边回头，没有面向镜头招呼',
                    anchor='等一下')

    def pair(self, task, winner_first=True, need=NEED, code='动作没发生'):
        names=[task+'-'+s for s in 'abc']
        win,lose=('A','B') if winner_first else ('B','A')
        for name,s in zip(names,'ABC'):
            self.asset(name,s==win)
        run=self.search(task,names,need)
        res=self.submit(run,[self.entry(win,True),self.entry(lose,code=code)])
        self.assertEqual(res.status_code,200,res.json)
        self.assertFalse(res.json.get('warning'),res.json)
        return run

    def rows(self):
        return [json.loads(l) for l in (self.directory/DATA).read_bytes().splitlines()]

    def receipt(self, task):
        response=self.client.get('/api/ai/runs',query_string=dict(project_id=self.catalog.req['project_id'], task_id=task))
        return response.get_json()['items'][0]['training']

    def evidence(self, name, data):
        dest=os.environ.get('CUTFRAME_RANK_EVIDENCE')
        if dest:
            Path(dest,name).write_text(data,encoding='utf8')

    def test_real_retraining_and_unseen_clip(self):
        with patch('socket.socket.connect',side_effect=AssertionError('训练和检索必须离线')):
            self.pair('第一组')
            receipt=self.receipt('第一组')
            self.assertIn('还差 1 条',receipt['progress'])
            self.assertIn('已进训练，A 排在 B 前面',receipt['details'][0])
            self.assertIn('未进训练，尚未单独评价',receipt['details'][2])
            row,=self.rows()
            self.assertEqual((row['胜出']['槽位'],row['落选']['槽位']),('A','B'))
            self.assertNotIn('第一组-c',json.dumps(row,ensure_ascii=False))
            self.assertEqual(row['胜出']['画面类型'],['V01'])
            self.assertEqual(row['胜出']['朝向'],['B5O01'])
            self.assertEqual(row['胜出']['主动作'],['B6H09'])
            fresh=['新-%02d'%i for i in range(9)]
            for n in fresh:self.asset(n,n==fresh[-1])
            baseline=['对照-'+name for name in fresh]
            for n in baseline:self.asset(n,n==baseline[-1])
            before=self.search('未达门槛',baseline)
            self.assertEqual([x['asset_id'] for x in before['items']],baseline[:3])
            self.assertEqual(before['rank_version'],LEGACY)
            self.pair('第二组',False)
            ranked=self.search('新素材验收',fresh)
            after=[x['asset_id'] for x in ranked['items']]
            self.assertEqual(len(after),3)
            self.assertEqual(after[0],fresh[-1])
            self.assertEqual([x['slot'] for x in ranked['items']],list('ABC'))
            self.assertEqual(ranked['items'][0]['rank_input_order'],9)
            self.assertIn('已可使用模型排序',self.receipt('新素材验收')['progress'])
            self.assertEqual(self.search('另一要求',fresh,'工人拆柜门')['rank_version'],LEGACY)
            # 两个未评价的普通镜头与任何退回记录无关；相同可见标签沿用稳定次序。
            self.assertEqual(after[1:],fresh[:2])
            self.asset('新的横屏招呼',True)
            self.catalog.metas['新的横屏招呼']['width']=1920
            horizontal=self.search('横屏挡片',['新的横屏招呼'])
            self.assertEqual(horizontal['items'],[])
            self.assertEqual(horizontal['filters']['非原生9比16'],1)
            oldrows=self.rows()
            # 已启用模型后展示次序可能改变，所以第三组用真实候选的标签决定胜负。
            names=['增量-a','增量-b','增量-c']
            for i,n in enumerate(names):self.asset(n,i==1)
            third=self.search('追加组',names)
            w=next(x['slot'] for x in third['items'] if x['asset_id']==names[1])
            l=next(x['slot'] for x in third['items'] if x['asset_id']==names[0])
            response=self.submit(third,[self.entry(w,True),self.entry(l)])
            self.assertFalse(response.json.get('warning'))
            self.assertEqual(self.rows()[:2],oldrows)
            self.assertEqual(len(self.rows()),3)
            latest=self.search('重训练后',fresh)
            self.assertNotEqual(ranked['rank_version'],latest['rank_version'])
            self.assertNotEqual(latest['rank_version'],LEGACY)
            text=(self.directory/DATA).read_bytes()
            export(self.catalog.learning,self.directory)
            self.assertEqual(text,(self.directory/DATA).read_bytes())
            with tempfile.TemporaryDirectory() as temp:
                copied=Path(temp)/DATA
                copied.write_bytes(text)
                with patch('sqlite3.connect',side_effect=AssertionError('训练不可回表')):
                    self.assertEqual(train(copied)['模型版本'],latest['rank_version'])
            self.evidence('对比样例.jsonl',text.decode())
            self.evidence('新素材排序.json',json.dumps(dict(原顺序=fresh,一条时展示=baseline[:3],
                         两条时展示=after,两条时版本=ranked['rank_version'],三条时版本=latest['rank_version'],
                         模型说明=json.loads((self.directory/INFO).read_bytes())),ensure_ascii=False,indent=2))
            (self.directory/MODEL).unlink()
            self.assertEqual(self.search('无模型',fresh)['rank_version'],LEGACY)

    def test_exclusions_placeholders_and_corrections(self):
        for i,code in enumerate(('同条重复','没看连续画面','晃动、失焦、拖影')):
            self.pair('非匹配'+str(i),code=code)
        self.assertFalse(any(row['能否训练'] for row in self.rows()))
        run=self.pair('占位',need='见原句')
        row=self.rows()[-1]
        self.assertFalse(row['能否训练'])
        self.assertEqual(row['不能训练的原因'],'画面要求不足')
        res=self.submit(run,[self.entry('B',code='阶段不对')],row['来源审核编号'])
        self.assertEqual(res.status_code,200)
        self.assertEqual([r['原因码'] for r in self.rows() if r['任务']=='占位'],[['阶段不对']])

    def test_gap_or_adoption_alone(self):
        for n in 'abc':self.asset(n)
        run=self.search('只采用','abc')
        self.assertEqual(self.submit(run,[self.entry('A',True,fact='看着不合适')]).status_code,400)
        self.assertEqual(self.submit(run,[self.entry('A',True)]).status_code,200)
        self.assertEqual(self.rows(),[])
        for n in 'def':self.asset(n)
        run=self.search('整批缺口','def')
        drafts=[self.entry(s,fact='') for s in 'ABC']
        self.assertEqual(self.submit(run,drafts,missing='不好看').status_code,400)
        self.assertEqual(self.submit(run,drafts,missing='缺少人物面向镜头招呼观众').status_code,200)
        gap,=self.rows()
        self.assertEqual((gap['样本类型'],gap['能否训练'],gap['本批素材编号']),('检索缺口',False,list('def')))
        self.evidence('检索缺口样例.jsonl',(self.directory/DATA).read_text('utf8'))

    def test_transition_can_be_adopted_without_teaching_a_match(self):
        for n in 'abc':self.asset(n)
        run=self.search('过渡镜头','abc')
        transition=dict(self.entry('A',True),code='过渡采用',fact='师傅和业主在交谈')
        response=self.submit(run,[transition,self.entry('B')])
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.rows(),[])
        saved=[json.loads(s) for s in self.client.get('/api/local/slot-export').data.splitlines()]
        record=next(r for r in saved if r['slot']=='A')
        self.assertEqual((record['verdict'],record['relation']),('采用','仅作过渡'))
        self.assertEqual(self.client.post('/api/local/slot-adopt',json=dict(run_id=run['run_id'],
                         candidate_id=run['items'][0]['id'])).status_code,200)

    def test_snapshot_dimension_whitelist_and_empty_need(self):
        item=dict(asset_id='片段',start=0,end=2,layer=1,local_kind='人确认',
                  tags=['V01','B5O01','B6H04','B6P01','其他维度'],machine_description='不能用的事后文字')
        side=candidate_snapshot(item,2)
        self.assertEqual(side['主动作'],['B6H04'])
        self.assertEqual(side['朝向'],['B5O01'])
        self.assertNotIn('B6P01',json.dumps(side,ensure_ascii=False))
        from ranking_feedback import contract_rows
        items=[dict(item,slot='A'),dict(item,slot='B',asset_id='普通')]
        reviews=[dict(status='已确认',slot='A',verdict='采用',id='1'),
                 dict(status='已确认',slot='B',verdict='不合适',id='2',codes=['动作做反了'],sentence='保留标准句')]
        row,=contract_rows('批',dict(text='未对上观点',task_id='任务',project_id='工程',need=''),
                           dict(items=items),reviews)
        self.assertEqual((row['能否训练'],row['不能训练的原因']),(False,'画面要求不足'))
