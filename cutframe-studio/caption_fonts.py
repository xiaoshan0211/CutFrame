"""字幕字体白名单及随镜序分发的思源黑体。"""
import os
from pathlib import Path
import shutil

FONT_DIR = Path(__file__).resolve().parent / 'static' / 'fonts'
FAMILIES = {'yahei': 'Microsoft YaHei', 'source-han': 'Source Han Sans CN'}


def font_style(settings):
    family = settings.get('subtitle_font', 'yahei')
    weight = settings.get('subtitle_weight', 'regular')
    if not isinstance(family, str) or family not in FAMILIES or weight not in ('regular', 'bold'):
        raise ValueError('请选择列表中的字幕字体和字重')
    return family, weight


def source_font(weight):
    return FONT_DIR / ('SourceHanSansCN-Bold.otf' if weight == 'bold' else 'SourceHanSansCN-Regular.otf')


def subtitle_filter(work, family, weight):
    if family == 'source-han':
        folder = work / 'caption-fonts'
        folder.mkdir(exist_ok=True)
        src = source_font(weight)
        if not src.is_file():
            raise ValueError('缺少所选字重的思源黑体文件')
        target = folder / src.name
        if not target.exists():
            try:
                os.link(src, target)
            except OSError:
                shutil.copyfile(src, target)
        return 'subtitles=filename=captions.ass:fontsdir=caption-fonts'
    return 'subtitles=filename=captions.ass'
