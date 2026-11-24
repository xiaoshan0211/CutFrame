"""用正式标注表只读验证第四步的整句拼接和拒绝误配。"""
import unittest
from pathlib import Path

from copy_viewpoints import Viewpoints


class ShortSubtitlesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = Viewpoints(Path(__file__).resolve().parent.parent)
        if cls.index.lookup('我就是那个一年在成都翻新1000多家卫生间的成都阿文')['id'] != 'P0297':
            raise unittest.SkipTest('这些断言按特定业务句库的原始行号核对')

    def selected(self, cues, i):
        return self.index.lookup(cues[i], leading=cues[:i], trailing=cues[i+1:])

    def test_each_host_cue(self):
        for city, name in [('成都', '啊文'), ('成都', '阿文'), ('哈尔滨', '阿文')]:
            cues = ['我就是那个一年在'+city, '翻新1000多家卫生间的', city+name]
            for i in range(3):
                with self.subTest(city=city, name=name, cue=i):
                    v = self.selected(cues, i)
                    self.assertEqual((v['id'], v['defaults'], v['joined']), ('P0297', ['V01'], ''.join(cues)))

    def test_each_customer_cue(self):
        for first in ['今天给金牛区一位张阿姨家', '今天给武侯区一位刘阿姨家', '今天给石家庄的欧阳阿姨家']:
            cues = [first, '四平方大的老卫生间', '做微陶泥翻新']
            for i in range(3):
                v = self.selected(cues, i)
                self.assertEqual((v['id'], v['defaults']), ('P0298', ['V02']))

        for place in ['东区','某个小区','装修']:
            cues=['今天给'+place+'一位张阿姨家', '四平方大的老卫生间', '做微陶泥翻新']
            self.assertFalse(self.selected(cues, 0)['id'])

    def test_keep_facts(self):
        for mid, end in [('五平方大的老卫生间', '做微陶泥翻新'), ('四米长的老卫生间', '做微陶泥翻新'),
                         ('四平方大的老厨房', '做微陶泥翻新'), ('四平方大的老卫生间', '做微水泥翻新'),
                         ('四平方大的老卫生间', '做微陶泥拆除')]:
            self.assertFalse(self.selected(['今天给金牛区一位张阿姨家', mid, end], 0)['defaults'])
        for mid, end in [('翻新1001多家卫生间的', '成都啊文'), ('翻新1000多家卫生间的', '南京啊文')]:
            self.assertFalse(self.selected(['我就是那个一年在成都', mid, end], 0)['defaults'])

    def test_unrelated_cue_is_a_boundary(self):
        for gap in ['另一件事情', '']:
            cues = ['我就是那个一年在成都', gap, '翻新1000多家卫生间的', '成都啊文']
            self.assertFalse(self.selected(cues, 0)['id'])

    def test_four_characters_and_fillers(self):
        cues = ['我就是那个一年在成都', '翻新1000', '多家卫', '生间', '的', '成都啊文']
        self.assertFalse(self.selected(cues, 2)['id'])
        self.assertFalse(self.selected(cues, 4)['id'])
        self.assertFalse(self.selected(['翻新完', '了'], 1)['defaults'])

    def test_ambiguous_window(self):
        v = self.selected(['他就是成都', '最抠门的局改师'], 0)
        self.assertFalse(v['defaults'])
        self.assertEqual([r['id'] for r in v['alternatives_by_id']], ['P0018', 'P0952'])
        self.assertTrue(all(r['title'] and r['primary'] for r in v['alternatives_by_id']))

    def test_exact_row_priority(self):
        for text, ident, types in [('现在武汉出现了一支专业翻新团队', 'P0005', ['V03', 'V04']),
                                   ('不砸瓷砖', 'P0299', []), ('卫生间真的不需要过度翻新了', 'P0262', [])]:
            v = self.index.lookup(text, '做微陶泥翻新', '传统翻新要砸掉瓷砖')
            self.assertEqual((v['id'], v['defaults'], v['joined']), (ident, types, ''))
        # 独立的原句即使也是较长观点的一部分，也优先保留原来的精确匹配。
        v = self.selected(['我就是那个一年在武汉', '翻新1000多家卫生间的', '武汉阿文'], 2)
        self.assertEqual(v['id'], 'P1841')

    def test_pending_joined_row(self):
        v = self.selected(['不管是老房改造', '还是二手房翻新', '传统翻新要砸掉瓷砖'], 0)
        self.assertEqual((v['id'], v['defaults'], v['inherited']), ('P0059', [], ''))

    def test_equivalent_wording_still_requires_a_unique_full_row(self):
        for text,ident in [('阿文全程不需要你动手','P0075'),('可以给我点个免费的爱心吗','P0302')]:
            v=self.index.lookup(text)
            self.assertEqual(v['id'],ident)
            self.assertTrue(v['equivalent'])
        v=self.index.lookup('完工即可使用')
        self.assertEqual([r['id'] for r in v['alternatives_by_id']],['P0146','P0279','P0606'])
        self.assertFalse(v['defaults'])
        self.assertFalse(self.index.lookup('5天完工即可使用')['defaults'])
