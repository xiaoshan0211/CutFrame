"""审核听写接口只返回文字，空录音、并发和识别失败均可恢复。"""
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
import review_dictation


class ReviewDictationTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_error_handler(ValueError, lambda e: ({'error': str(e)}, 400))
        review_dictation.register(app, {'BASE': Path(__file__).parent, 'CONFIG': {'ffmpeg': 'ffmpeg'}})
        self.client = app.test_client()

    def post(self, data, kind='audio/webm;codecs=opus'):
        return self.client.post('/api/local/review-dictation', data=data, content_type=kind)

    def test_invalid_audio_never_starts_the_model(self):
        with patch('review_dictation.transcribe') as worker:
            self.assertEqual(self.post(b'').status_code, 400)
            self.assertEqual(self.post(b'abc', 'text/plain').status_code, 415)
            self.assertEqual(self.post(b'x' * (review_dictation.MAX_AUDIO_BYTES+1)).status_code, 413)
            worker.assert_not_called()

    def test_busy_and_failed_recognition_release_the_model(self):
        def busy(*_):
            self.assertEqual(self.post(b'concurrent').status_code, 429)
            raise ValueError('没有听清语音')
        with patch('review_dictation.transcribe', side_effect=busy):
            self.assertEqual(self.post(b'first').status_code, 400)
        with patch('review_dictation.transcribe', return_value='工人用卷尺测量墙面'):
            self.assertEqual(self.post(b'retry').get_json(), {'text': '工人用卷尺测量墙面'})
