"""选片审核的中文听写。录音在内存中解码，接口只返回可编辑的文字。"""
import subprocess
import threading
from functools import lru_cache

from flask import jsonify, request

from media import FLAGS


MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 60
SAMPLE_RATE = 16000


def decode_recording(data, ffmpeg):
    import numpy as np

    # MediaRecorder 生成的 WebM 不一定有时长头；按实际解码样本限制时长。
    cmd = [ffmpeg, '-nostdin', '-v', 'error', '-protocol_whitelist', 'pipe',
           '-i', 'pipe:0', '-map', '0:a:0', '-t', str(MAX_SECONDS + 1),
           '-ac', '1', '-ar', str(SAMPLE_RATE), '-f', 's16le', 'pipe:1']
    try:
        result = subprocess.run(cmd, input=data, capture_output=True, timeout=15, creationflags=FLAGS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('本机录音解码失败，请重新录音') from exc
    if result.returncode or not result.stdout:
        raise ValueError('录音无法读取，请重新录音')
    samples = np.frombuffer(result.stdout, dtype='<i2')
    if len(samples) > MAX_SECONDS * SAMPLE_RATE:
        raise ValueError('每次语音输入最多 60 秒，请分段录制')
    if len(samples) < SAMPLE_RATE // 5 or not samples.any():
        raise ValueError('没有听清语音，请靠近麦克风再说一次')
    return samples.astype(np.float32) / 32768


@lru_cache(maxsize=1)
def local_recognizer(folder):
    if not all((folder / name).is_file() for name in ('model.bin', 'tokenizer.json')):
        raise ValueError('本机听写模型不完整，可先用键盘输入')
    from faster_whisper import WhisperModel
    from opencc import OpenCC

    return (WhisperModel(str(folder), device='cpu', compute_type='int8', cpu_threads=6,
                         local_files_only=True), OpenCC('t2s'))


def transcribe(data, ffmpeg, folder):
    samples = decode_recording(data, ffmpeg)
    model, simplify = local_recognizer(folder)
    segments, _ = model.transcribe(samples, language='zh', beam_size=5, vad_filter=True,
                                   condition_on_previous_text=False,
                                   initial_prompt='装修现场口述。常用词有翻新、瓷砖、卷尺、微陶泥、批刮和水电。')
    text = simplify.convert(''.join(part.text for part in segments).strip())
    if not text:
        raise ValueError('没有听清语音，请靠近麦克风再说一次')
    return text


def register(app, env):
    folder = env['BASE'].parent / 'local/asr-models/whisper-small'
    available = threading.Lock()

    @app.post('/api/local/review-dictation')
    def review_dictation():
        if request.mimetype not in {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/x-wav'}:
            return jsonify(error='不支持这种录音格式'), 415
        if (request.content_length or 0) > MAX_AUDIO_BYTES:
            return jsonify(error='录音过大，请分段录制'), 413
        data = request.stream.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            return jsonify(error='录音过大，请分段录制'), 413
        if not data:
            return jsonify(error='没有收到录音，请重试'), 400
        if not available.acquire(blocking=False):
            return jsonify(error='本机正在识别另一段录音，请稍后重试'), 429
        try:
            text = transcribe(data, env['CONFIG']['ffmpeg'], folder)
            return jsonify(text=text)
        finally:
            available.release()
