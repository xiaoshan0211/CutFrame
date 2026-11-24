import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import verified_people as v
class Tests(unittest.TestCase):
 def test_identity_and_constraints(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);src=d/'source.mov';src.write_bytes(b'test')
   rows=[dict(sample_id='R1',source=dict(id='a',start=2,end=6),person_identity='阿文',confirmed_by='用户',confirmation_evidence='是阿文'),dict(sample_id='R2',source=dict(id='b',start=2,end=6),person_identity='其他人物',confirmed_by='用户',confirmation_evidence='不是阿文')]
   (d/'person-01.json').write_text(json.dumps(dict(rows=rows)),'utf-8')
   req=dict(exclude_assets=[],catalog=[dict(id='a',name='a.mov',root='x',rel='项目/a.mov'),dict(id='b',name='b.mov',root='x',rel='项目/b.mov')],duration=.54,run_id='test',round=1,text='成都阿文')
   meta=dict(width=1080,height=1920,duration=10)
   with patch.object(v,'probe',return_value=meta),patch.object(v.subprocess,'run'):
    def search():return v.search(req,d,d/'cache',lambda a:src,'probe','ffmpeg')['items']
    r=search();self.assertEqual([x['asset_id'] for x in r],['a']);self.assertEqual(r[0]['end'],2.54)
    req['exclude_assets']=['a'];self.assertEqual(search(),[])
    req['exclude_assets']=[];req['duration']=5;self.assertEqual(search(),[])
    req['duration']=.54;meta.update(width=1920,height=1080);self.assertEqual(search(),[])
    meta.update(width=1080,height=1920)
    (d/'person-usage-restrictions.json').write_text(json.dumps(dict(rules=[dict(reference_source=dict(id='a'))])),'utf-8');self.assertEqual(search(),[])
if __name__=='__main__':unittest.main()
