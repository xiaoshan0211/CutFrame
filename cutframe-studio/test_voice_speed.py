import os,unittest,json,time,wave,math,struct,hashlib,uuid
if not os.environ.get('CUTFRAME_STATE'): raise RuntimeError('需要独立测试目录')
from app import app,TOKEN,PORT,STATE,execute,one
class VoiceSpeedTests(unittest.TestCase):
 def setUp(self):
  self.c=app.test_client();self.h={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN}
 def test_speed_preserves_original_and_does_not_stack(self):
  iid=uuid.uuid4().hex;p=STATE/'imports'/(iid+'.wav')
  with wave.open(str(p),'wb') as w:
   w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b''.join(struct.pack('<h',int(8000*math.sin(i*2*math.pi*440/16000))) for i in range(64000)))
  self.ids=[iid];self.addCleanup(lambda: [execute('DELETE FROM imports WHERE id=?',(x,)) for x in self.ids]);digest=hashlib.sha256(p.read_bytes()).hexdigest();execute('INSERT INTO imports VALUES(?,?,?,?,?)',(iid,'中文测试.wav',str(p),'voice',json.dumps({'duration':4,'audio':True,'tts':{'text':'原文不变'}})))
  def change(source,rate):
   r=self.c.post('/api/tts/speed',json={'voice_id':source,'speed':rate},headers=self.h);self.assertEqual(r.status_code,200,r.json)
   for _ in range(200):
    j=one('SELECT * FROM jobs WHERE id=?',(r.json['job_id'],))
    if j['status'] in ('done','failed','cancelled'):break
    time.sleep(.05)
   self.assertEqual(j['status'],'done',j);result=json.loads(j['result']);self.ids.append(result['id']);return result
  a=change(iid,1.25);self.assertAlmostEqual(a['duration'],3.2,delta=.08)
  b=change(a['id'],.8);self.assertAlmostEqual(b['duration'],5,delta=.1)
  self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),digest)
  meta=json.loads(one('SELECT meta FROM imports WHERE id=?',(b['id'],))['meta']);self.assertEqual(meta['speed_original_id'],iid);self.assertEqual(meta['tts']['text'],'原文不变')
 def test_invalid_and_token(self):
  for value in [0,-1,3,'bad',None]:self.assertEqual(self.c.post('/api/tts/speed',json={'speed':value},headers=self.h).status_code,400)
  self.assertEqual(self.c.post('/api/tts/speed',json={'speed':1}).status_code,403)
