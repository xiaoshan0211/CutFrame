"""逐标签表和旧版逐段表应提供相同的定位点及分类窗口。"""
import unittest
from pathlib import Path
from unittest.mock import patch

import cloud_segments


class CloudSegmentTests(unittest.TestCase):
    def test_segment_and_tag_rows_produce_the_same_windows(self):
        asset = {'镜序素材ID': 'm1', '云端素材编号': 's1', '结论': '有分类待抽查', '媒体': '视频'}
        first = dict(asset, 段序='1', 起秒='0', 止秒='6.01', 云端维度与标签原文='空间：厨房')
        first['镜头内容 · 云端原文'] = '工人安装台面柜体。'
        second = dict(first, 段序='2', 起秒='6.01', 止秒='12.02')
        second['镜头内容 · 云端原文'] = '暂无描述'
        labels = [('画面类型', 'V04'), ('画面类型', 'V23'), ('主动作', 'B6C12'),
                  ('素材类别', '卫浴与洁具'), ('素材类别', '改造服务与安装')]
        tags = [dict(first, 标签维度=dim, 标签=code, 修正标签='', 核验状态='候选待看片')
                for dim, code in labels]
        wide = dict(first, 已列画面类型='V04、V23', 已列素材类别='卫浴与洁具、改造服务与安装',
                    本轮抽帧依据='男子扶起玻璃门框')
        for rows in ([second, first], [tags[0], second, *tags[1:]], [wide, second]):
            with self.subTest(row_count=len(rows)):
                sheets = {'云端秒段': rows, '已核标签': [], '候选标签': tags, '全目录清单': [asset]}
                cloud_segments._index.cache_clear()
                self.addCleanup(cloud_segments._index.cache_clear)
                with patch.object(cloud_segments, 'read_tables', return_value=sheets), \
                     patch.object(cloud_segments, 'version', return_value='fixture'):
                    book = Path('测试素材表.xlsx')
                    segments = cloud_segments.index(book)[0]['m1']
                    self.assertEqual([(r['ordinal'], r['start'], r['end'], r['text']) for r in segments], [
                        ('1', 0, 6.01, '工人安装台面柜体。'), ('2', 6.01, 12.02, '暂无描述')])
                    for types in ({'V04'}, {'V23'}, {'V04', 'V23'}):
                        windows = list(cloud_segments.windows(book, {'m1': asset}, types, []))
                        self.assertEqual(len(windows), 1)
                        window = windows[0]
                        self.assertIn(window['picture'], types)
                        self.assertEqual(window['start'], 0)
                        available = [(dim, code) for dim, code, sheet in window['extra_tags']]
                        self.assertCountEqual(available+[('画面类型', window['picture'])], labels)
                    if wide in rows:
                        self.assertFalse(list(cloud_segments.windows(book, {'m1': asset}, set(), ['安装'])))
                        observed=list(cloud_segments.windows(book, {'m1': asset}, set(), ['扶起']))
                        self.assertEqual([w['description'] for w in observed], ['男子扶起玻璃门框'])
