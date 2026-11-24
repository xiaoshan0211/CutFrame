"""隔离学习库，使用真实 HTTP 路由验证三槽位审核。"""
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier, local
from unittest.mock import patch
from flask import Flask, jsonify
import test_local_selection as fixtures
import ai_service
import local_selection_service


class SlotReviewTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.LocalSelectionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        for i, tag in enumerate(['V05','V06','V06','V05','V06','V06','V06','V10']):
            sid = f.asset(str(i))
            f.tag(sid, tag)
            f.desc(sid, '测试词')
        app = Flask(__name__)
        app.extensions['annotation_store'] = f.store
        app.register_error_handler(ValueError, lambda e: (jsonify(error=str(e)), 400))
        env = dict(STATE=f.state, BASE=f.base, CONFIG={'roots':f.roots}, metadata=lambda a:f.metas[a['id']])
        self.rule_dir=f.state/'观点标注'
        self.plan=f.state/'选片方案.md'
        self.plan.write_text('## 六、成片优先，经验随用随记\n','utf-8')
        env.update(VIEWPOINT_RULE_DIR=self.rule_dir,VIEWPOINT_PLAN=self.plan)
        ai_service.register(app,env)
        local_selection_service.register(app,env)
        self.app = app
        self.fixture = f
        self.client = app.test_client()
        self.req = dict(f.req, text='工人安装柜门', keywords=['测试词'])
        self.req['conditions']['must'][0]['tags'] = ['V05','V06']
        self.first_round()

    def first_round(self):
        self.result = self.search()
        self.assertEqual([x['asset_id'] for x in self.result['items']], ['0','1','2'])
        self.assertEqual([x['slot'] for x in self.result['items']], list('ABC'))

    def search(self, **changes):
        return self.client.post('/api/local/discover',json=dict(self.req, **changes)).get_json()

    def review(self, i, **changes):
        item=self.result['items'][i]
        body=dict(run_id=self.result['run_id'],candidate_id=item['id'],reviewer='测试员',verdict='不合适',
                  fact='工人正在拆柜门',anchor='安装柜门',relation='做了相反的事',codes=['动作做反了'])
        if changes.get('verdict')=='采用':
            body.update(extra_fact='工人握住柜门装上铰链',differences={x['slot']:'只看见侧面走动' for x in self.result['items'] if x!=item})
        return self.client.post('/api/local/slot-review',json=dict(body,**changes))

    def test_reject_block_and_export(self):
        for change in [dict(fact='看着不合适'),dict(fact=''),dict(anchor=''),dict(codes=[]),dict(relation='')]:
            self.assertEqual(self.review(0,**change).status_code,400)
        a=self.review(0,conflict_tags=['V05']).get_json()
        self.assertIn('工人正在拆柜门',a['sentence'])
        self.assertEqual(self.client.post('/api/local/slot-finish',json=dict(run_id=self.result['run_id'],missing='缺少安装动作',reviewer='甲')).status_code,400)
        self.review(1,codes=['晃动、失焦、拖影'])
        self.review(2)
        def finish(missing):
            return self.client.post('/api/local/slot-finish',json=dict(run_id=self.result['run_id'],missing=missing,reviewer='测试员'))
        self.assertEqual(finish('').status_code,400)
        self.assertEqual(finish('缺少安装柜门动作').status_code,200)
        second=self.search(use_experience=False)
        self.assertEqual([x['asset_id'] for x in second['items']],['4','5','6'])
        self.assertIn(('3',a['id']),[(b['asset_id'],b['id']) for b in second['blocked']])
        on=self.search(task_id='对照任务',use_experience=True)
        self.assertEqual(second['blocked'],on['blocked'])
        self.assertEqual(on['items'],[])
        self.assertTrue(second['items'][0]['warnings_to_review'])
        self.assertIn('ABC均不采用',self.client.get('/api/local/slot-export').get_data(as_text=True))
        self.result=second
        self.assertEqual(self.review(0,verdict='采用',codes=['证据够'],relation='做了').status_code,400)

        warnings=second['items'][0]['warnings_to_review']
        replies={w['id']:dict(choice='没有这个错',fact='柜门全程清晰') for w in warnings}
        yes=dict(verdict='采用',codes=['证据够'],relation='做了',fact='工人装上柜门',answers=replies)
        self.assertEqual(self.review(0,**yes).status_code,200)
        replies[warnings[0]['id']]['fact']='说不清'
        self.assertEqual(self.review(0,**yes).status_code,400)
        still={warnings[0]['id']:dict(choice='仍有这个错')}
        self.assertEqual(self.review(0,**dict(yes,answers=still)).status_code,400)
        self.assertEqual(self.review(0,codes=warnings[0]['codes'],answers=still).status_code,200)
        self.assertEqual(self.client.post('/api/local/slot-adopt',json=dict(run_id=second['run_id'],candidate_id=second['items'][0]['id'])).status_code,400)

    def test_pending_revision_and_duplicate(self):
        first=self.review(0,status='待补看',codes=['同条重复']).get_json()
        pending=self.search(task_id='另一条',text='另一句测试')
        self.assertNotIn('0',[c['asset_id'] for c in pending['items']])
        self.assertNotIn('0',[c['asset_id'] for c in pending['blocked']])
        confirmed=self.review(0,codes=['同条重复']).get_json()
        blocked=self.search(task_id='第三条',text='工程其他句')
        self.assertIn(('0',confirmed['id']),[(b['asset_id'],b['id']) for b in blocked['blocked']])
        new=self.review(0,verdict='采用',codes=['动作发生了'],relation='做了').get_json()
        replay=self.search(task_id='新的同句')
        self.assertNotIn('0',[c['asset_id'] for c in replay['items']])
        self.assertNotIn('0',[c['asset_id'] for c in replay['blocked']])
        export=self.client.get('/api/local/slot-export').get_data(as_text=True)
        for r in [first,confirmed,new]:self.assertIn(r['id'],export)

    def test_concurrent_projects_draw_unseen_originals_until_pool_empty(self):
        # 让两个不同工程同时选中相同的剩余原片，再让它们争抢落库。
        with closing(sqlite3.connect(self.fixture.catalog)) as db,db:
            db.execute("INSERT INTO projects VALUES('other','{}')")
        self.fixture.tag(self.fixture.store.create('0',3,7),'V05')
        barrier=Barrier(2,timeout=15)
        thread=local()
        query=local_selection_service.Selection.query
        def simultaneous(selector,data):
            result=query(selector,data)
            if not getattr(thread,'queried',False):
                thread.queried=True
                barrier.wait()
            return result
        def search_project(project):
            with self.app.test_client() as client:
                response=client.post('/api/local/discover',json=dict(self.req,project_id=project,task_id='新字幕',text='另一句'))
                self.assertEqual(response.status_code,200,response.json)
                return [c['asset_id'] for c in response.json['items']]
        with patch.object(local_selection_service.Selection,'query',simultaneous), ThreadPoolExecutor(2) as pool:
            batches=list(pool.map(search_project,['p','other']))
        self.assertEqual(sorted(map(len,batches)),[1,3])
        self.assertEqual(sorted(batches[0]+batches[1]),list('3456'))
        empty=self.search(task_id='第三句')
        self.assertEqual(empty['items'],[])
        self.assertEqual(empty['filters']['历史检索已展示的原片'],7)
        history=self.client.get('/api/ai/runs',query_string=dict(project_id='p',task_id=self.req['task_id'])).json
        self.assertEqual([c['asset_id'] for c in history['items'][0]['result']['items']],list('012'))

    def test_adoption_gate(self):
        b=self.result['items'][1]
        args=dict(run_id=self.result['run_id'],candidate_id=b['id'])
        self.assertEqual(self.client.post('/api/local/slot-adopt',json=args).status_code,200)
        self.assertEqual(self.client.post('/api/local/slot-adopt',json=dict(args,candidate_id='其他批次')).status_code,400)
        self.review(1,verdict='采用',codes=['动作发生了'],relation='做了',fact='工人安装柜门')
        # 其他两个窗口已有比较结论。未采用不写成不合适训练记录。
        self.assertEqual(self.client.post('/api/local/slot-adopt',json=args).status_code,200)
        records=self.client.get('/api/local/slot-export').get_data(as_text=True).splitlines()
        self.assertEqual([json.loads(line)['verdict'] for line in records],['采用'])

    def test_unreviewed_selection_and_next_batch_leave_training_empty(self):
        from ranking_feedback import export
        from selection_ranker import DATA
        first=self.result
        item=first['items'][0]
        args=dict(run_id=first['run_id'],candidate_id=item['id'])
        self.assertEqual(self.client.post('/api/local/slot-adopt',json=args).status_code,200)
        event=dict(args,action='adopted',project_id=self.req['project_id'],task_id=self.req['task_id'],shot=item)
        self.assertEqual(self.client.post('/api/ai/adoption',json=event).status_code,200)
        second=self.search(trigger='next',previous_run=first['run_id'])
        self.assertEqual([i['asset_id'] for i in second['items']],list('345'))
        self.assertEqual(self.search(trigger='next',previous_run=first['run_id'])['run_id'],second['run_id'])
        third=self.search(trigger='next',previous_run=second['run_id'])
        self.assertEqual([i['asset_id'] for i in third['items']],['6'])
        with closing(sqlite3.connect(self.fixture.learning)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM slot_reviews').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM adoptions').fetchone()[0],1)
        export(self.fixture.learning,self.rule_dir)
        self.assertEqual((self.rule_dir/DATA).read_bytes(),b'')

    def test_round_duration_survives_json_precision(self):
        changed=self.search(trigger='changed',text='测试一秒',duration=1.0400000000000003)
        again=self.search(trigger='changed',text='测试一秒',duration=1.0400000000000005)
        self.assertEqual(changed['run_id'],again['run_id'])
        response=self.client.post('/api/local/reserve',json={'run_id':changed['run_id']})
        self.assertEqual(response.status_code,200,response.get_json())

    def test_missing_primary_uses_three_editable_fallback_types(self):
        req=dict(text='在武汉7天的时间',leading=[],trailing=['2万的预算','把业主的家从这样变成这样'])
        view=self.client.post('/api/local/viewpoint',json=req).get_json()
        types=['V01','V02','V05']
        self.assertEqual((view['primary'],view['defaults'],view['inherited']),([],types,''))
        for code in types:
            self.fixture.tag(self.fixture.asset('默认-'+code),code)
        req.update(task_id='默认范围',keywords=[],exclude_assets=[str(i) for i in range(8)],
                   conditions={'must':[dict(dimension='画面类型',tags=types)]})
        result=self.search(trigger='auto',**req)
        self.assertEqual([c['slot'] for c in result['items']],list('ABC'))
        self.assertEqual({c['asset_id'] for c in result['items']},{'默认-'+code for code in types})
        self.fixture.tag(self.fixture.asset('改选-V02'),'V02')
        chosen=self.search(**dict(req,trigger='changed',conditions={'must':[dict(dimension='画面类型',tags=['V02'])]}))
        self.assertEqual([c['asset_id'] for c in chosen['items']],['改选-V02'])
        known=self.client.post('/api/local/viewpoint',json=dict(text='现在武汉出现了一支专业翻新团队')).get_json()
        self.assertEqual(known['defaults'],['V03','V04'])

    def test_restore_stale_zero_with_manual_types_and_retry(self):
        req=dict(self.req,text='我就是那个一年在成都',trailing=['翻新1000多家卫生间的','成都啊文'],
                 task_id='成都首句',keywords=[],scope='all',board_context='已同步')
        types=['V01','V02','V03']
        def run(trigger,codes,**kwargs):
            return self.client.post('/api/local/discover',json=dict(req,trigger=trigger,
                 conditions={'must':[dict(dimension='画面类型',tags=codes)]},**kwargs)).get_json()
        old=run('changed',types)
        self.assertEqual(old['items'],[])
        # 重现旧版已保存的 0/3，再次打开该句时应恢复手选条件并重新检索。
        with closing(sqlite3.connect(self.fixture.learning)) as db,db:
            old['filters']['非竖屏预筛']=13
            db.execute('UPDATE runs SET result=? WHERE id=?',(json.dumps(old),old['run_id']))
        self.fixture.tag(self.fixture.asset('rotated'), 'V02')
        fixed=run('auto',['V01'])
        self.assertEqual([c['asset_id'] for c in fixed['items']],['rotated'])
        self.assertEqual(run('auto',['V01'])['run_id'],fixed['run_id'])
        with closing(sqlite3.connect(self.fixture.learning)) as db:
            p=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(fixed['run_id'],)).fetchone()[0])
            self.assertEqual((p['type_source'],p['type_selection']['selected']),('manual',types))
            self.assertEqual(json.loads(db.execute('SELECT result FROM runs WHERE id=?',(old['run_id'],)).fetchone()[0]),old)
        empty=run('changed',['V03'])
        self.assertEqual(run('retry',['V03'],retry_of=empty['run_id'])['run_id'],empty['run_id'])
        self.fixture.tag(self.fixture.asset('new-team'),'V03')
        fresh=run('retry',['V03'],retry_of=empty['run_id'])
        self.assertEqual([c['asset_id'] for c in fresh['items']],['new-team'])
        self.assertEqual(run('retry',['V03'],retry_of=empty['run_id'])['run_id'],fresh['run_id'])
