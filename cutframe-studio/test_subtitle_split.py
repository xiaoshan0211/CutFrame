import unittest
from subtitle_split import split_cue


class SplitTests(unittest.TestCase):
    def test_real_word_boundary_not_equal_ratio(self):
        cue=dict(text='我们在武汉搞了一个团队',start=1,end=6)
        words=[dict(word='我们在武汉',start=1,end=2.1),dict(word='搞了一个团队',start=2.3,end=6)]
        result=split_cue(cue,5,words)
        self.assertEqual(result[0]['end'],2.1)
        self.assertEqual(result[1]['start'],2.3)
        self.assertEqual(''.join(c['text'] for c in result),cue['text'])

    def test_internal_word_has_no_invented_time(self):
        with self.assertRaises(ValueError):
            split_cue(dict(text='武汉翻新',start=0,end=2),1,[dict(word='武汉',start=0,end=1),dict(word='翻新',start=1,end=2)])

    def test_missing_boundary_rejected(self):
        with self.assertRaises(ValueError):
            split_cue(dict(text='从这样改造成这样',start=0,end=2),3,[dict(word='从这样',start=0,end=2)])

    def test_empty_half_rejected(self):
        with self.assertRaises(ValueError):
            split_cue(dict(text='武汉',start=0,end=1),0,[])
