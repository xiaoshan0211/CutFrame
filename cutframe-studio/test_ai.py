import unittest,tempfile,json,uuid,random
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'.packages'))
from flask import Flask
from ai_store import connect,latest_feedback,select_diverse
from ai_service import register
class AIFeedbackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name);self.app=Flask(__name__)
  @self.app.errorhandler(ValueError)
  def fail(e):return {'error':str(e)},400
  def submit(kind,worker):
   jid=uuid.uuid4().hex;(self.state/'jobs'/jid).mkdir(parents=True);self.last_result=worker(jid);return jid
  model=self.state/'clip-fixture';model.mkdir();(model/'pytorch_model.bin').touch()
  register(self.app,dict(STATE=self.state,BASE=Path(__file__).parent,CONFIG={'clip_model':str(model)},submit=submit,PROCESSES={},one=lambda *a:{'status':'running'},update_job=lambda *a,**k:None));self.client=self.app.test_client();self.db=self.state/'ai/learning.sqlite3'
  p=dict(text='工人保护家具',context='旧房翻新',project_id='p',task_id='t')
  result=dict(items=[dict(id='c',asset_id='a',start=0,end=2),dict(id='d',asset_id='b',start=0,end=2)])
  with connect(self.db) as db:db.execute('insert into runs values(?,?,?,?)',('r','now',json.dumps(p),json.dumps(result)))
 def tearDown(self):
  # Windows SQLite连接由gc收尾，隔离目录不进入正式经验库。
  import gc;gc.collect();self.tmp.cleanup()
 def post(self,path,**d):return self.client.post('/api/ai/'+path,json=d)
 def feed(self,**kw):return self.post('feedback',**dict(dict(run_id='r',candidate_id='c',reviewer='测试甲',verdict='suitable',reason_code='good'),**kw))
 def historical_feedback(self,candidate='c',reviewer='测试甲',verdict='suitable',code='good'):
  fid=uuid.uuid4().hex
  with connect(self.db) as db:
   db.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?)',(fid,'旧批次','r',candidate,reviewer,verdict,code,''))
  return fid
 def historical_rule(self,code='good'):
  fid=self.historical_feedback(code=code);rid=uuid.uuid4().hex
  payload=dict(scope='project',project_id='p',action='avoid' if code=='duplicate' else 'prefer',reason_code=code,asset_id='a',text='工人保护家具')
  with connect(self.db) as db:
   db.execute('INSERT INTO rules VALUES(?,?,?,?,?,?)',(rid,'旧草稿',fid,'pending','',json.dumps(payload)))
  return rid
 def test_feedback_append_and_reviewers(self):
  self.historical_feedback();self.historical_feedback(verdict='unsuitable');self.historical_feedback(reviewer='测试乙')
  self.assertEqual(self.feed().status_code,400)
  with connect(self.db) as db:
   self.assertEqual(db.execute('select count(*) from feedback').fetchone()[0],3)
   latest=latest_feedback(db,'r');self.assertEqual(len(latest),2);self.assertEqual(latest[0]['verdict'],'unsuitable')
 def test_unreviewed_no_rule(self):
  fid=self.historical_feedback(verdict='unreviewed')
  self.assertEqual(self.post('rules/propose',feedback_id=fid).status_code,400)
  self.assertEqual(self.client.get('/api/ai/rules').json['items'],[])
 def test_rule_pending_review_disable(self):
  rid=self.historical_rule()
  self.assertEqual(self.client.get('/api/ai/rules').json['items'][0]['status'],'pending')
  self.post('rules/review',id=rid,reviewer='测试审核',status='approved',scope='project')
  self.assertEqual(self.client.get('/api/ai/rules').json['items'][0]['status'],'approved')
  self.post('rules/review',id=rid,reviewer='测试审核',status='disabled',scope='project')
  with connect(self.db) as db:self.assertEqual(db.execute('select count(*) from rule_events').fetchone()[0],2)
 def test_duplicate_cannot_apply_all_projects(self):
  rid=self.historical_rule('duplicate')
  self.assertEqual(self.post('rules/review',id=rid,reviewer='测试审核',status='approved',scope='similar').status_code,400)
 def test_adoption_not_feedback(self):
  self.post('adoption',run_id='r',candidate_id='c',project_id='p',task_id='t',action='adopted',shot={})
  with connect(self.db) as db:
   self.assertEqual(db.execute('select count(*) from feedback').fetchone()[0],0)
   self.assertEqual(db.execute('select count(*) from adoptions').fetchone()[0],1)
 def test_foreign_candidate_and_empty_reviewer_rejected(self):
  self.assertEqual(self.feed(candidate_id='unknown').status_code,400)
  self.assertEqual(self.feed(reviewer='').status_code,400)
 def test_search_worker_payload_and_pending_rules_excluded(self):
  from unittest.mock import patch
  (self.state/'ai/active-index.json').write_text(json.dumps(dict(job_id='old')),'utf-8')
  self.historical_rule()
  class Process:
   returncode=0
   def poll(self):return 0
  captured=[]
  def fake(args,**kw):
   p=Path(args[-1]);captured.append(json.loads(p.read_text('utf-8')));(p.parent/'result.json').write_text(json.dumps(dict(items=[],gap=10)),'utf-8');return Process()
  with patch('ai_service.subprocess.Popen',fake):
   response=self.post('search',text='工人保护家具',duration=2,project_id='p',task_id='t',board_context='ctx')
  self.assertEqual(response.status_code,200,response.json);self.assertEqual(captured[0]['rules'],[]);self.assertEqual(captured[0]['board_context'],'ctx')
  rid=self.client.get('/api/ai/rules').json['items'][0]['id']
  self.post('rules/review',id=rid,reviewer='测试审核',status='approved',scope='project')
  with patch('ai_service.subprocess.Popen',fake):
   self.post('search',text='工人保护家具',duration=2,project_id='p',task_id='t')
   self.post('search',text='工人保护家具',duration=2,project_id='another',task_id='t')
   self.post('search',text='工人保护家具',duration=2,project_id='p',task_id='t',use_experience=False)
  self.assertEqual(len(captured[1]['rules']),1);self.assertEqual(captured[2]['rules'],[]);self.assertEqual(captured[3]['rules'],[])
 def test_zero_or_all_feedback_and_export(self):
  self.historical_feedback();self.historical_feedback(candidate='d')
  self.assertEqual(self.feed(candidate_id='all',verdict='unsuitable').status_code,400)
  data=self.client.get('/api/ai/export').data.decode()
  self.assertEqual(sum(json.loads(l)['record_type']=='feedback' for l in data.splitlines()),2)
 def test_distinct_assets_and_visual_duplicate(self):
  rng=random.Random(4);items=[dict(asset_id=str(i),phash=f'{rng.getrandbits(64):016x}',score=1-i*.01) for i in range(20)]
  items.insert(0,dict(items[0],score=1.1));items.append(dict(items[1],asset_id='same_image',score=.5))
  out=select_diverse(items);self.assertEqual(len(out),10);self.assertEqual(len(set(x['asset_id'] for x in out)),10)
  self.assertNotIn('same_image',[x['asset_id'] for x in out])
if __name__=='__main__':unittest.main()
