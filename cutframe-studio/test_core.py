import unittest
from pathlib import Path
from media import validate_range, seconds, clip_command
import os
if not os.environ.get('CUTFRAME_STATE'): raise RuntimeError('请使用 run_tests.py，在独立测试台账运行')
from app import app, TOKEN, PORT, safe_child, clean_name
from composition import parse_srt, write_ass
import tempfile

class CoreTests(unittest.TestCase):
    def test_uniform_subtitle_uses_requested_size(self):
        sentence='武汉的家家户户都找阿文做旧房改造'
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'字幕.ass'
            write_ass(target,[dict(start=1.84,end=5.2,text=sentence),dict(start=5.2,end=6.9,text='短字幕')],1080,1920,72,360,0)
            content=target.read_text('utf-8-sig')
        lines=[line for line in content.splitlines() if line.startswith('Dialogue:')]
        self.assertEqual(len(lines),2)
        self.assertIn('0:00:01.84,0:00:05.20',lines[0])
        self.assertIn('{\\fs72}'+sentence,lines[0])
        self.assertIn('{\\fs72}短字幕',lines[1])
        self.assertNotIn('\\N',lines[0])
        self.assertIn('WrapStyle: 2',content)
    def test_invalid_times(self):
        for v in ['nan','inf',-1,None]:
            with self.assertRaises(ValueError): seconds(v)
        for a,b in [(2,1),(0,0),(0,11)]:
            with self.assertRaises(ValueError): validate_range(a,b,10)
    def test_path_boundary(self):
        root=Path.cwd()
        with self.assertRaises(ValueError): safe_child(root,'../escape.mp4')
        self.assertEqual(safe_child(root,'中文 文件.mp4').name,'中文 文件.mp4')
    def test_names(self):
        for s in ['../x','CON','a/b','a\\b','x.']:
            with self.assertRaises(ValueError): clean_name(s)
    def test_no_transcode_fallback(self):
        c=clip_command({'ffmpeg':'ffmpeg'},'中文 (测试).mov','out.mp4',1,3,'copy',{})
        self.assertIn('copy',c)
        self.assertNotIn('h264_mf',c)
        self.assertIn('中文 (测试).mov',c)
    def test_local_security(self):
        c=app.test_client()
        self.assertEqual(c.get('/api/state',headers={'Host':'evil.test'}).status_code,403)
        self.assertEqual(c.post('/api/events',json={},headers={'Host':f'127.0.0.1:{PORT}'}).status_code,403)
        self.assertEqual(c.post('/api/events',json={},headers={'Host':f'127.0.0.1:{PORT}','X-Local-Token':TOKEN,'Origin':'https://evil.test'}).status_code,403)
    def test_pagination(self):
        c=app.test_client()
        r=c.get('/api/assets?root=xiaoq',headers={'Host':f'127.0.0.1:{PORT}'})
        self.assertEqual(r.status_code,200)
        self.assertLessEqual(len(r.json['items']),60)
    def test_srt_preserves_text(self):
        cues=parse_srt('1\n00:00:00,100 --> 00:00:01,200\n原始中文不改写\n')
        self.assertEqual(cues[0]['text'],'原始中文不改写')
        self.assertAlmostEqual(cues[0]['start'],.1)
    def test_srt_overlap_rejected(self):
        with self.assertRaises(ValueError): parse_srt('1\n00:00:00,000 --> 00:00:02,000\n甲\n\n2\n00:00:01,000 --> 00:00:03,000\n乙')
    def test_srt_control_code_rejected(self):
        with self.assertRaises(ValueError): parse_srt('1\n00:00:00,000 --> 00:00:02,000\n{\\pos(0,0)}文字')

if __name__=='__main__': unittest.main()
