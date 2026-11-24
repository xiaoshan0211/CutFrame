"""W11–W16：只用临时库，纯查询与既有 HTTP 接口兼容。"""
import contextlib,copy,gc,json,sqlite3,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from annotation_store import Store,dump,now
from annotation_rules import Rules
from import_machine_annotations import ensure_schema
from ai_store import connect
from local_selection import Selection,similarity,active_conditions

class LocalSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.addCleanup(gc.collect);self.state=Path(self.tmp.name);(self.state/'ai').mkdir();self.store=Store(self.state/'annotation.sqlite3');ensure_schema(self.store)
        self.base=Path(__file__).parent;self.tree=json.loads((self.base/'rules/label-tree-v0.2.json').read_text('utf-8'));Rules(self.store).create(dict(label_tree=self.tree,rules=[]))
        self.catalog=self.state/'catalog.sqlite3';self.learning=self.state/'ai/learning.sqlite3'
        with contextlib.closing(sqlite3.connect(self.catalog)) as c,c:
            c.execute('CREATE TABLE assets(id TEXT PRIMARY KEY,root TEXT,rel TEXT,name TEXT,available INTEGER)');c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY,data TEXT)');c.execute('INSERT INTO projects VALUES(?,?)',('p',dump(dict(shots=[]))))
        with contextlib.closing(connect(self.learning)):pass
        self.metas={};self.roots={'xiaoq':{'role':'raw'},'baba':{'role':'raw'}};self.blocked=set()
        self.req=dict(text='测试字幕',duration=2,project_id='p',task_id='t',scope='all',conditions={'must':[dict(dimension='画面类型',tags=['V05'])]})
    def query(self,request=None):return Selection(self.store.path,self.catalog,self.learning,self.roots,lambda a:self.metas[a['id']],self.blocked).query(request or self.req)
    def asset(self,aid='a',root='xiaoq',start=0,end=8,raw=None):
        with contextlib.closing(sqlite3.connect(self.catalog)) as c,c:c.execute('INSERT INTO assets VALUES(?,?,?,?,?)',(aid,root,'目录/'+aid+'.mp4',aid+'.mp4',1))
        self.store.original(aid,logical_path='目录/'+aid+'.mp4',duration=10,raw=raw or {'画幅':'竖','可用状态':'可用'});self.metas[aid]=dict(width=1080,height=1920,sar='1:1',rotation=0,duration=10)
        return self.store.create(aid,start,end)
    def tag(self,sid,tag='V05',human=False,negative=False,flags=None,dim='画面类型'):
        return self.store.annotate(sid,dict(dimension=dim,labels=[tag],source='人工' if human else '机器',review_status='人工确认' if human else '未审',negative=negative,flags=flags or []))
    def desc(self,sid,text):
        with self.store.db() as c:c.execute('INSERT INTO machine_descriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(None,sid,text,'分时段','s',sid,sid,'input.jsonl',1,1,None,now()))
    def history(self,aid='a',start=0,end=5,text='测试字幕',action='adopted',feedback=None,project='other'):
        rid=uuid.uuid4().hex;cand=dict(id='c',asset_id=aid,start=start,end=end);payload=dict(text=text,context='',project_id=project,task_id='old',duration=end-start)
        with contextlib.closing(sqlite3.connect(self.learning)) as c,c:
            c.execute('INSERT INTO runs VALUES(?,?,?,?)',(rid,now(),dump(payload),dump(dict(items=[cand]))));c.execute('INSERT INTO adoptions VALUES(?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,now(),project,'old',rid,'c',action,dump(cand)))
            if feedback:c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,now(),rid,'c','人',feedback,'',''))
        return rid
    def restrict(self,level,aid='a',start=0,end=1):
        with self.store.db() as c:c.execute('INSERT INTO restrictions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,level,aid,start,end,'目录','目录限制原文','甲','s',1,'{}',now()))
    def test_W11_no_budget_process_or_network_needed(self):
        self.tag(self.asset(),human=True)
        with patch('subprocess.Popen',side_effect=AssertionError('不得启动进程')),patch('socket.socket',side_effect=AssertionError('不得联网')),patch('gpt_provider.budget_status',side_effect=AssertionError('不得读预算')):
            self.assertEqual(len(self.query()['items']),1)
        self.assertFalse((self.state/'ai/gpt-costs.sqlite3').exists())
    def test_W12_windows_limits_unique_stable(self):
        for i in range(13):self.tag(self.asset(str(i)),human=True)
        sid=self.store.create('0',2,7);self.tag(sid,human=True)
        a=self.query();b=self.query();self.assertEqual(a['items'],b['items']);self.assertEqual(len(a['items']),3);self.assertEqual(len({x['asset_id'] for x in a['items']}),3)
        self.assertEqual((a['remaining'],a['unchecked_sources']),(3,7))
        for x in a['items']:
            s=self.store.get(x['segment_id']);r=next(r for r in s['ranges'] if r['id']==s['current_range']);self.assertEqual(x['end']-x['start'],2);self.assertGreaterEqual(x['start'],r['start']);self.assertLessEqual(x['end'],r['end'])
    def test_classified_intervals_join_exact_path_and_respect_restrictions(self):
        import csv
        for aid in ['match','short','blocked','wrong','corrected']:
            sid=self.asset(aid)
            if aid=='wrong':self.tag(sid,'V05',human=True,negative=True)
            if aid=='corrected':self.store.annotate(sid,dict(dimension='画面类型',labels=['V02'],source='人工',review_status='人工改正',reviewer='甲'))
        self.roots['xiaoq']['path']='Y:/原片'
        with (self.state/'500条素材路径总表.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['画面类型','原片路径','入点秒','出点秒','依据来源','画面依据'])
            for aid in ['match','short','blocked','wrong','corrected']:
                w.writerow(['V05',f'Y:/原片/目录/{aid}.mp4',2,3 if aid=='short' else 6,'既有描述','墙面批刮'])
            w.writerow(['V10','Y:/原片/目录/match.mp4',2,4,'既有描述','清洁墙面'])
            w.writerow(['V05','Z:/其他/目录/short.mp4',0,7,'既有描述','同名异库'])
        selector=Selection(self.store.path,self.catalog,self.learning,self.roots,lambda a:self.metas[a['id']],{'blocked'},self.state)
        result=selector.query(self.req)
        self.assertEqual([(c['asset_id'],c['start'],c['end'],c['local_kind']) for c in result['items']],[('match',2,4,'分类表·待核对')])
        req=copy.deepcopy(self.req);req['conditions']['forbid']=[dict(dimension='画面类型',tags=['V10'])]
        self.assertEqual(selector.query(req)['items'],[])
    def test_W13_each_hard_filter_and_count(self):
        cases=['禁用来源','素材不可用','请求排除','本工程已用','历史检索已展示的原片','片段长度不足','可用状态不是可用','原片限制','秒段限制','人工反例命中必须条件','禁止条件命中人工','禁止条件命中机器','竖屏复核取不到原片','非原生9比16','真实时长不足']
        for reason in cases:
            with self.subTest(reason=reason):
                # 每个过滤使用全新临时库，确保计数可对账。
                t=LocalSelectionTests();t.setUp()
                try:
                    sid=t.asset(end=1 if reason=='片段长度不足' else 8);t.tag(sid,human=True);req=copy.deepcopy(t.req)
                    if reason=='禁用来源':t.blocked.add('a')
                    elif reason=='请求排除':req['exclude_assets']=['a']
                    elif reason in ('素材不可用',):
                        with contextlib.closing(sqlite3.connect(t.catalog)) as c,c:c.execute('UPDATE assets SET available=0')
                    elif reason=='本工程已用':
                        with contextlib.closing(sqlite3.connect(t.catalog)) as c,c:c.execute('UPDATE projects SET data=?',(dump(dict(shots=[dict(asset_id='a')])),))
                    elif reason=='历史检索已展示的原片':
                        with contextlib.closing(sqlite3.connect(t.learning)) as c,c:c.execute('INSERT INTO runs VALUES(?,?,?,?)',('seen',now(),dump(dict(provider='local',project_id='p',task_id='t')),dump(dict(items=[dict(asset_id='a')]))))
                    elif reason=='可用状态不是可用':
                        with t.store.db() as c:c.execute('UPDATE originals SET raw=?',(dump({'画幅':'竖','可用状态':'需打码后可用' if reason=='可用状态不是可用' else '可用'}),))
                    elif reason in ('原片限制','秒段限制'):t.restrict('原片' if reason=='原片限制' else '秒段')
                    elif reason=='人工反例命中必须条件':t.tag(sid,human=True,negative=True)
                    elif reason.startswith('禁止条件'):
                        req['conditions']['forbid']=[dict(dimension='画面类型',tags=['V10'])];t.tag(sid,'V10',human=reason.endswith('人工'))
                    elif reason=='最近评价不合适':t.history(feedback='unsuitable')
                    elif reason=='竖屏复核取不到原片':t.metas['a']=None
                    elif reason=='非原生9比16':t.metas['a']['width']=1920
                    elif reason=='真实时长不足':t.metas['a']['duration']=1
                    result=t.query(req);self.assertEqual(result['items'],[]);self.assertGreaterEqual(result['filters'].get(reason,0),1)
                    # 历史采用会与片段各产生一个受过滤窗口，其余恰为一个。
                    self.assertEqual(sum(result['filters'].values()),2 if reason=='最近评价不合适' else 1)
                finally:t.doCleanups()
    def test_display_rotation_overrides_old_landscape_annotation(self):
        for i,rotation in enumerate([-90,90,-90,0]):
            aid=str(i)
            self.tag(self.asset(aid,raw={'画幅':'横','可用状态':'可用'}))
            self.metas[aid].update(width=1920,height=1080,rotation=rotation)
        self.assertEqual([r['asset_id'] for r in self.query()['items']],['0','1','2'])
        result=self.query(dict(self.req,exclude_assets=['0','1']))
        self.assertEqual([r['asset_id'] for r in result['items']],['2'])
        self.assertEqual(result['filters']['非原生9比16'],1)

    def test_W13_directory_warning_last_and_overlap_boundary(self):
        self.tag(self.asset('a'),human=True);self.tag(self.asset('b'),human=True);self.restrict('目录')
        with self.store.db() as c:c.execute("UPDATE originals SET logical_path='别处/b.mp4' WHERE asset_id='b'")
        # b 的原片路径不在受限目录。
        with contextlib.closing(sqlite3.connect(self.catalog)) as c,c:c.execute("UPDATE assets SET rel='别处/b.mp4' WHERE id='b'")
        result=self.query();self.assertEqual([x['asset_id'] for x in result['items']],['b','a']);self.assertEqual(result['items'][1]['warnings'],['目录限制原文'])
        self.restrict('秒段','b',2,4);self.assertIn('b',[x['asset_id'] for x in self.query()['items']])
    def test_W14_layers_negative_conflict_baba_and_keywords(self):
        self.tag(self.asset('human'),human=True);self.tag(self.asset('machine'));sid=self.asset('description');self.desc(sid,'真正的批刮施工描述');self.tag(self.asset('conflict'),human=True,flags=['冲突待确认']);self.tag(self.asset('baba',root='baba'),human=True)
        req=copy.deepcopy(self.req);req['keywords']=['批刮'];r=self.query(req);self.assertEqual({x['asset_id']:x['layer'] for x in r['items']},{'human':1,'machine':2});self.assertEqual(r['layer_counts'],{'1':1,'2':1,'3':0})
        rid=self.history('baba');r=self.query(req);self.assertNotIn('baba',[x['asset_id'] for x in r['items']])
        self.assertEqual(r['filters']['历史检索已展示的原片'],1)
        with contextlib.closing(sqlite3.connect(self.learning)) as c,c:c.execute('INSERT INTO adoptions VALUES(?,?,?,?,?,?,?,?)',('removed',now(),'other','old',rid,'c','removed','{}'))
        self.assertNotIn('baba',[x['asset_id'] for x in self.query(req)['items']])
    def test_must_AND_tags_OR_partial_unknown_and_literal_keyword(self):
        sid=self.asset();self.tag(sid,'V06');req=copy.deepcopy(self.req);req['conditions']['must'][0]['tags'].append('V06');req['conditions']['must'].append(dict(dimension='材料类目',tags=['B7M01']))
        self.assertEqual(self.query(req)['items'],[])
        self.tag(sid,'B7M01',dim='材料类目')
        self.assertEqual(self.query(req)['items'][0]['layer'],2)
        self.desc(sid,'百分号没有');req['conditions']={};req['keywords']=['%'];self.assertEqual(self.query(req)['items'],[])
    def test_no_conditions_only_history_similarity_and_short_adoption(self):
        self.tag(self.asset(),human=True);req=dict(self.req,conditions={});self.assertEqual(self.query(req)['items'],[]);self.assertIn('请选条件',self.query(req)['notice']);self.history(start=0,end=1);self.assertEqual(self.query(req)['items'],[]);self.history(start=2,end=5,text='测试字幕！')
        result=self.query(req)
        self.assertEqual(result['items'],[])
        self.assertEqual(result['filters']['历史检索已展示的原片'],1)
        self.assertEqual(similarity('字，幕！','字幕'),1)
    def test_W15_W16_http_review_old_interfaces_and_history_functions(self):
        from flask import Flask,jsonify
        import ai_service,local_selection_service
        sid=self.asset();machine=self.tag(sid);before=self.store.get(sid)
        env=dict(STATE=self.state,BASE=self.base,CONFIG={'roots':self.roots,'ffmpeg':'does-not-exist'},metadata=lambda a:self.metas[a['id']],get_asset=lambda aid:dict(id=aid,name='a',rel='目录/a.mp4',root='xiaoq'),asset_path=lambda a:self.state/'missing.mp4')
        app=Flask(__name__);app.extensions['annotation_store']=self.store
        @app.errorhandler(ValueError)
        def bad(e):return jsonify(error=str(e)),400
        ai_service.register(app,env);local_selection_service.register(app,env);client=app.test_client()
        with patch('gpt_provider.budget_status',side_effect=AssertionError('不得查预算')),patch('subprocess.Popen',side_effect=AssertionError('不得起云进程')):
            response=client.post('/api/local/discover',json=self.req);self.assertEqual(response.status_code,200,response.json)
        result=response.json;c=result['items'][0];rid=result['run_id'];self.assertEqual(c['thumbnail_status'],'缩略图取不到')
        with client.get(f'/api/ai/thumb/{rid}/{c["id"]}') as thumb:self.assertEqual(thumb.status_code,200)
        review=dict(run_id=rid,candidate_id=c['id'],verdict='confirm',tag='V05');self.assertEqual(client.post('/api/local/review-type',json=review).status_code,400);review['reviewer']='核对人';done=client.post('/api/local/review-type',json=review);self.assertEqual(done.status_code,200,done.json);self.assertNotEqual(done.json['segment_id'],sid)
        self.assertEqual(self.store.get(sid),before);window=self.store.get(done.json['segment_id']);self.assertEqual([(r['start'],r['end']) for r in window['ranges']],[(0,2)]);self.assertEqual(json.loads(window['annotations'][0]['evidence'])['machine_annotation_ids'],[machine])
        self.assertEqual(client.post('/api/ai/feedback',json=dict(run_id=rid,candidate_id=c['id'],reviewer='评价人',verdict='suitable')).status_code,400)
        counts=self.store.counts();self.assertEqual(client.post('/api/ai/adoption',json=dict(run_id=rid,candidate_id=c['id'],project_id='p',task_id='t',action='adopted',shot=c)).status_code,200);self.assertEqual(counts,self.store.counts())
        self.assertEqual(len(client.get('/api/ai/runs?project_id=p&task_id=t').json['items']),1)
        from ai_discovery import history_exclusions,query_key
        with contextlib.closing(sqlite3.connect(self.learning)) as db:
            db.row_factory=sqlite3.Row;h=history_exclusions(db.execute('SELECT payload,result FROM runs'),'p','t',query_key(self.req));self.assertIn('a',h['seen'])
        next_result=client.post('/api/local/discover',json=self.req).json;self.assertEqual(next_result['items'],[])
        previous=client.get('/api/local/previous?project_id=p&task_id=t').json['previous'];self.assertEqual(previous['conditions']['must'][0]['tags'],['V05'])
