"""把浏览器已排好的整句字幕图按已保存字幕的时间码叠加。"""
import base64
import binascii
import io
import math
import re

from PIL import Image


def make_overlay(images, work, cues, settings, width, height, fps, total, input_index):
    lines = [re.sub(r'[，。！？、；：,.!?;:]+$', '', cue['text'].strip()) for cue in cues]
    if not isinstance(images, dict) or set(images) != set(lines):
        raise ValueError('字幕内容已更新，请刷新后重新导出')
    strip_height = min(height, math.ceil(settings['font_size'] * 1.5 + 8))
    dimensions = (width, strip_height)
    names = {}
    for i, (text, encoded) in enumerate(images.items()):
        if not isinstance(encoded, str) or len(encoded) > 2 * 1024**2:
            raise ValueError('单句字幕图过大，请拆分长句')
        try:
            raw = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(raw), formats=['PNG']) as image:
                if image.size != dimensions or image.mode != 'RGBA' or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('整句字幕图尺寸或格式无效')
                filename = f'caption-{i}.png'
                image.save(work / filename, format='PNG')
                names[text] = filename
        except (OSError, binascii.Error, Image.DecompressionBombError) as error:
            raise ValueError('整句字幕图无法读取') from error
    blank = 'caption-gap.png'
    Image.new('RGBA', dimensions).save(work / blank)
    playlist = ['ffconcat version 1.0']

    def clip(name, frames):
        if frames > 0:
            # 单张 PNG 的 FFmpeg 缺省时基为 1/25，先精确记录整数帧，再转换成工程帧率。
            playlist.extend([f"file '{name}'", f'duration {frames/25:.9f}'])

    end_frame = math.ceil(total * fps)
    position = 0
    offset = settings['subtitle_offset']
    for cue, line in zip(cues, lines):
        start = min(end_frame, max(position, math.ceil((cue['start'] + offset)*fps - 1e-8)))
        end = min(end_frame, max(start, math.ceil((cue['end'] + offset)*fps - 1e-8)))
        clip(blank, start-position)
        clip(names[line], end-start)
        position = end
    clip(blank, end_frame-position)
    playlist.append(f"file '{blank}'")
    (work/'caption-art.ffconcat').write_text('\n'.join(playlist)+'\n', 'ascii')
    inputs = ['-f', 'concat', '-safe', '0', '-i', 'caption-art.ffconcat']
    bottom = int(settings['subtitle_bottom'])
    return inputs, (f'[{input_index}:v]settb=1/60000,setpts=round(PTS*25/{fps})[caption];'
                    f'[0:v][caption]overlay=x=0:y=H-h-{bottom}:eof_action=pass:repeatlast=0[video]')
