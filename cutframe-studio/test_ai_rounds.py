import unittest,json,tempfile,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent/'.packages'))
from flask import Flask
from ai_service import register
from ai_store import connect
from ai_discovery import history_exclusions,query_key,rank_catalog
class RoundDiscoveryTests(unittest.TestCase):
 def test_history_over_all_rounds_and_other_subtitles(self):
  data=dict(text='施工',need='',context='',duration=2,scope='all');key=query_key(data);rows=[]
  for i in range(30):rows.append(dict(payload=json.dumps(dict(data,project_id='p',task_id='t',query_key=key)),result=json.dumps(dict(items=[{'asset_id':str(i),'phash':f'{i:016x}'}],examined_assets=['checked'+str(i)]))))
  rows.append(dict(payload=json.dumps({'project_id':'p','task_id':'other'}),result=json.dumps({'items':[{'asset_id':'other-shown'}]})))
  result=history_exclusions(rows,'p','t',key);self.assertEqual(len(result['seen']),31);self.assertEqual(len(result['examined']),30);self.assertEqual(result['round'],31)
  self.assertEqual(history_exclusions(rows,'p','t','changed-query')['examined'],set())
  self.assertEqual(history_exclusions(rows,'another','t',key)['seen'],set())
 def test_catalog_rank_does_not_limit_scope_to_fifty(self):
  assets=[dict(id=str(i),name=f'{i}.mp4',rel=('施工/拆除/' if i==99 else '其他/')+f'{i}.mp4') for i in range(120)]
  ranked=rank_catalog(assets,'从设计到拆除再到安装');self.assertEqual(len(ranked),120);self.assertEqual(ranked[0]['id'],'99')
 def test_discovery_round_api_and_guard(self):
  with tempfile.TemporaryDirectory() as folder:
   state=Path(folder);app=Flask(__name__);captured=[];outputs=[]
   @app.errorhandler(ValueError)
   def fail(e):return {'error':str(e)},400
   assets=[dict(id=str(i),root='raw',name=f'{i}.mp4',rel=f'施工/{i}.mp4') for i in range(120)]
   def one(sql,args=()):return {'data':json.dumps({'shots':[{'asset_id':'used'}]})} if 'projects' in sql else {'status':'running'}
   def submit(kind,worker):
    jid=str(len(captured));(state/'jobs'/jid).mkdir(parents=True);outputs.append(worker(jid));return jid
   register(app,dict(STATE=state,BASE=Path(__file__).parent,CONFIG={'roots':{'raw':{'role':'raw','path':folder,'label':'测试原片'}},'ffmpeg':'test','ffprobe':'test'},many=lambda *a:assets,one=one,submit=submit,PROCESSES={},update_job=lambda *a,**k:None))
   client=app.test_client()
   class Process:
    returncode=0
    def poll(self):return 0
   def fake(args,**kw):
    p=Path(args[-1]);r=json.loads(p.read_text('utf-8'));captured.append(r);cid=str(99+len(captured))
    item=dict(id=cid,asset_id=cid,start=1,end=3,duration=10,phash='f0f0f0f0f0f0f0f0')
    (p.parent/'result.json').write_text(json.dumps(dict(items=[item],examined_assets=['examined'+str(len(captured))],gap=9)),'utf-8');return Process()
   req=dict(project_id='p',task_id='t',text='拆除',duration=2,scope='all',context='',need='')
   with patch('ai_service.subprocess.Popen',fake):
    first=client.post('/api/ai/discover',json=req);self.assertEqual(first.status_code,200,first.json)
    second=client.post('/api/ai/discover',json=req);self.assertEqual(second.status_code,200,second.json)
   self.assertEqual(len(captured[0]['catalog']),120);self.assertIn('100',captured[1]['exclude_assets']);self.assertIn('used',captured[1]['exclude_assets']);self.assertIn('examined1',captured[1]['examined_before']);self.assertEqual(captured[1]['round'],2)
   with connect(state/'ai/learning.sqlite3') as db:self.assertEqual(db.execute('select count(*) from feedback').fetchone()[0],0)
   run_id=db.execute('select id from runs order by rowid desc limit 1').fetchone()[0]
   reviewed=client.post('/api/ai/feedback',json=dict(run_id=run_id,candidate_id='all',verdict='unsuitable',reviewer='测试员',reason='画面不对应'))
   self.assertEqual(reviewed.status_code,400,reviewed.json)
   with patch('ai_service.subprocess.Popen',fake):third=client.post('/api/ai/discover',json=req)
   self.assertEqual(third.status_code,200,third.json);self.assertIn('101',captured[2]['exclude_assets'])
   self.assertEqual(db.execute('select count(*) from feedback').fetchone()[0],0)
   def duplicate(args,**kw):
    p=Path(args[-1]);(p.parent/'result.json').write_text(json.dumps(dict(items=[dict(id='x',asset_id='100',start=1,end=3,duration=10)],examined_assets=[])),'utf-8');return Process()
   with patch('ai_service.subprocess.Popen',duplicate):r=client.post('/api/ai/discover',json=req)
   self.assertEqual(r.status_code,400);self.assertIn('排重',r.json['error'])
   self.assertEqual(client.post('/api/ai/discover',json=dict(req,scope='reference')).status_code,400)
   db.close()
   import gc;gc.collect()
