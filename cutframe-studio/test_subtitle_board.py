import unittest,json,copy
from subtitle_board import validate_subtitle_board,frame_duration
class SubtitleBoardTests(unittest.TestCase):
 def setUp(self):
  self.cues=[dict(start=0,end=2,text='测试画面')];self.shots=[dict(task_ids=['t'],start=1,end=3,timeline_start=0,available_end=4)]
  self.settings=dict(fps=30,subtitle_offset=0,voice_offset=0);self.imports=dict(voice='v',subtitle='s');self.workflow=dict(script='测试画面')
  ctx=json.dumps(dict(text='测试画面',voice='v',subtitle='s',cues=self.cues,fps='30',voiceOffset='0',subtitleOffset='0'))
  t=dict(id='t',text='测试画面',start=0,end=2,need='测试',accepted=json.dumps(dict(text='测试画面',start=0,end=2,need='测试',split=None,shots=self.shots,context=ctx)))
  self.board=dict(tasks=[t],confirmed='confirmed')
 def check(self):validate_subtitle_board(self.board,self.shots,self.cues,2,self.workflow,self.settings,self.imports)
 def test_valid(self):self.check()
 def test_identical_subtitle_saved_as_new_id(self):
  self.imports['subtitle']='new-id';self.check()
 def test_complete_legacy_project_without_confirmations(self):
  self.board.pop('confirmed');self.board['tasks'][0].pop('accepted');self.check()
 def test_missing_second_shot(self):
  self.board['tasks'][0]['planned_shots']=2
  with self.assertRaisesRegex(ValueError,'还缺一个镜头'):self.check()
 def test_gap_rejected(self):
  self.shots[0]['timeline_start']=.1
  with self.assertRaises(ValueError):self.check()
 def test_editing_notes_does_not_require_confirmation(self):
  self.shots[0]['reason']='修改'
  self.check()
 def test_changed_subtitle(self):
  self.cues[0]['text']='不同'
  with self.assertRaises(ValueError):self.check()
 def test_cumulative_frame_budget(self):
  edges=[0,.78,1.84,5.2,6.9]
  durations=[frame_duration(a,b,30) for a,b in zip(edges,edges[1:])]
  self.assertAlmostEqual(sum(durations),6.9)
  with self.assertRaises(ValueError):frame_duration(0,.001,30)
