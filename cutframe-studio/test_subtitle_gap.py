import unittest,copy
from subtitle_board import continue_gap_shots
class GapTests(unittest.TestCase):
 def setUp(self):
  self.tasks=[dict(id='a',text='厨房',start=0,end=13.58),dict(id='b',text='卫生间',start=14.22,end=15.76)]
  self.shots=[dict(asset_id='a',task_ids=['a'],timeline_start=0,start=1,end=14.58,source_duration=20,available_end=14.58),dict(asset_id='b',task_ids=['b'],timeline_start=14.22,start=0,end=1.54,source_duration=10,available_end=1.54)]
 def test_gap_coverage_and_preserve_choices(self):
  old=copy.deepcopy(self.shots);s=continue_gap_shots(self.tasks,self.shots,16.22)
  self.assertAlmostEqual(s[0]['end'],15.22);self.assertAlmostEqual(s[1]['end'],2);self.assertEqual(old,self.shots)
  self.assertAlmostEqual(sum(x['end']-x['start'] for x in s),16.22)
  self.assertEqual(continue_gap_shots(self.tasks,self.shots,16.22),s)
 def test_actual_metadata_overrides_stale_browser_duration(self):
  with self.assertRaisesRegex(ValueError,'原片剩余不足'):continue_gap_shots(self.tasks,self.shots,16.22,{'a':15,'b':10})
 def test_double_shot_only_extends_last(self):
  s=[dict(self.shots[0],end=3),dict(self.shots[0],timeline_start=2,start=5,end=16.58,source_duration=30),self.shots[1]]
  p=continue_gap_shots(self.tasks,s,16.22);self.assertEqual(p[0]['end'],3);self.assertAlmostEqual(p[1]['end'],17.22)
 def test_missing_leading_and_overlap_rejected(self):
  self.tasks[0]['start']=1
  with self.assertRaisesRegex(ValueError,'片头'):continue_gap_shots(self.tasks,self.shots,16.22)
  self.tasks[0]['start']=0;self.tasks[1]['start']=13
  with self.assertRaisesRegex(ValueError,'重叠'):continue_gap_shots(self.tasks,self.shots,16.22)
