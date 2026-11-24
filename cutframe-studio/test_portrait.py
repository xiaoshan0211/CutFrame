import unittest
from media import is_portrait_916
class PortraitTest(unittest.TestCase):
 def test_ratios(self):
  for w,h,r,yes in [(1080,1920,0,True),(720,1280,0,True),(1920,1080,90,True),(1920,1080,-90,True),(1920,1080,0,False),(1080,1920,90,False),(1080,1440,0,False),(1080,1080,0,False),(1080,1920,45,False)]:
   self.assertEqual(is_portrait_916(dict(width=w,height=h,rotation=r)),yes)
  self.assertFalse(is_portrait_916(dict(width=1080,height=1920,sar='2:1')))
  self.assertFalse(is_portrait_916({}))
