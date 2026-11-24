import unittest,tempfile,json,hashlib,inspect,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'.packages'))
from flask import Flask
from composition import register
class GapRenderIntegrationTests(unittest.TestCase):
 def test_render_uses_extended_ranges_without_changing_saved_choices(self):
  with tempfile.TemporaryDirectory() as folder:
   state=Path(folder);(state/'imports').mkdir();(state/'metadata').mkdir();imports={};saved={};captured={}
   cues=[dict(start=0,end=1,text='厨房'),dict(start=1.64,end=2.64,text='卫生间')]
   for kind,meta in [('voice',{'duration':3}),('subtitle',{'duration':2.64,'cues':cues})]:
    p=state/'imports'/kind;p.write_bytes(b'test');imports[kind]=dict(id=kind,kind=kind,name=kind,path=str(p),meta=json.dumps(dict(meta,sha256=hashlib.sha256(b'test').hexdigest())))
   def one(sql,args):
    if 'imports' in sql:return imports.get(args[0])
    if 'projects' in sql:return {'data':json.dumps(saved)} if saved else None
   def execute(sql,args):
    if 'projects' in sql:saved.clear();saved.update(json.loads(args[2]))
   def submit(kind,worker):captured.update(inspect.getclosurevars(worker).nonlocals);return 'isolated-job'
   app=Flask(__name__)
   @app.errorhandler(Exception)
   def error(e):return {'error':str(e)},400
   env=dict(STATE=state,CONFIG={},one=one,execute=execute,many=lambda *a:[],get_asset=lambda aid:{'id':aid},asset_path=lambda a:state/'source',metadata=lambda a:{'duration':10},now=lambda:'now',clean_name=lambda n:n,safe_child=lambda root,name:root/name,submit=submit)
   register(app,env)
   shots=[dict(asset_id='a',task_ids=['a'],timeline_start=0,start=2,end=3,available_end=3,source_duration=10),dict(asset_id='b',task_ids=['b'],timeline_start=1.64,start=0,end=1,available_end=1,source_duration=10)]
   ctx=dict(text='厨房卫生间',voice='voice',subtitle='subtitle',cues=cues,fps='30',voiceOffset='0',subtitleOffset='0')
   tasks=[]
   for c,s in zip(cues,shots):
    t=dict(c,id=s['task_ids'][0],need='',role='字幕镜头');t['accepted']=json.dumps(dict(text=t['text'],start=t['start'],end=t['end'],need='',split=None,shots=[s],context=json.dumps(ctx)));tasks.append(t)
   p=dict(name='隔离续播测试',shots=shots,settings={},imports={'voice':'voice','subtitle':'subtitle'},workflow=dict(script='厨房卫生间',storyboard=dict(mode='subtitle',gap_policy='continue_previous',tasks=tasks,candidates=[],confirmed='隔离技术测试')))
   client=app.test_client();r=client.post('/api/render',json=p);self.assertEqual(r.status_code,200,r.json)
   self.assertEqual(saved['shots'],shots);self.assertAlmostEqual(captured['data']['duration'],3);self.assertAlmostEqual(captured['render_shots'][0]['end'],3.64);self.assertAlmostEqual(captured['render_shots'][1]['end'],1.36)
   again=client.post('/api/render',json=dict(saved));self.assertEqual(again.status_code,200,again.json);self.assertAlmostEqual(captured['render_shots'][0]['end'],3.64)
