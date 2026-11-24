"""用临时台账核对云端来源入库、断网读取和候选隔离。"""
import io
import os
import subprocess
import unittest
from unittest.mock import patch

if not os.environ.get('CUTFRAME_STATE'):
    raise RuntimeError('请使用 run_tests.py 在临时台账运行')

from app import app, CONFIG, TOKEN, PORT
from cloud_materials import ROOT
import test_local_selection as fixtures


class CloudMaterialTests(unittest.TestCase):
    def test_offline_copy_and_duplicate(self):
        client=app.test_client()
        headers={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN}
        video=subprocess.run([CONFIG['ffmpeg'],'-v','error','-f','lavfi','-i','color=size=90x160:rate=5',
                              '-t','1','-c:v','mpeg4','-f','mp4','-movflags','frag_keyframe+empty_moov',
                              'pipe:1'],capture_output=True,check=True).stdout
        link='https://test-bucket.oss-cn-hangzhou.aliyuncs.com/test.mp4?example=fixture'
        incoming=io.BytesIO(video)
        incoming.headers={'Content-Length':str(len(video))}
        with patch('cloud_materials.build_opener') as remote:
            remote.return_value.open.return_value=incoming
            imported=client.post('/api/materials/aliyun/oss',json={'url':link},headers=headers)
            self.assertEqual(imported.status_code,200,imported.json)
            self.assertFalse(imported.json['duplicate'])
        aid=imported.json['id']
        with patch('socket.socket.connect',side_effect=AssertionError('离线读取不能连接云端')):
            other=app.test_client()
            repeat=other.post('/api/materials/aliyun/file',query_string={'name':'同步盘/另一份.mp4'},
                              data=video,content_type='application/octet-stream',headers=headers)
            self.assertEqual((repeat.json['id'],repeat.json['duplicate']),(aid,True))
            listed=other.get('/api/assets',query_string={'root':ROOT},headers=headers).json
            self.assertEqual([a['id'] for a in listed['items'] if a['id']==aid],[aid])
            detail=other.get('/api/assets/'+aid,headers=headers).json
            self.assertEqual(detail['asset']['root'],ROOT)
            self.assertEqual(detail['meta']['width'],90)
            with other.get('/media/'+aid,headers=dict(headers,Range='bytes=20-119')) as played:
                self.assertEqual(played.status_code,206)
                self.assertEqual(played.data,video[20:120])
            refused=other.post('/api/materials/aliyun/oss',json={'url':'https://example.com/clip.mp4'},headers=headers)
            self.assertEqual(refused.status_code,400)
            invalid=other.post('/api/materials/aliyun/file?name=bad.mp4',data=b'broken',headers=headers)
            self.assertEqual(invalid.status_code,400)

    def test_classified_sources_stay_separate(self):
        f=fixtures.LocalSelectionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.roots[ROOT]=dict(role='raw',origin='cloud')
        f.tag(f.asset('local'),human=True)
        f.tag(f.asset('cloud',root=ROOT),human=True)
        f.asset('unclassified',root=ROOT)
        self.assertEqual([c['asset_id'] for c in f.query()['items']],['local'])
        from local_selection import Selection
        selection=Selection(f.store.path,f.catalog,f.learning,f.roots,lambda a:f.metas[a['id']],clean_book='本测试的云端来源使用已核秒段')
        result=selection.query(dict(f.req,scope=ROOT))
        self.assertEqual([c['asset_id'] for c in result['items']],['cloud'])
