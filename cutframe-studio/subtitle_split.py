"""按配音识别词边界拆字幕；不按字符数量均分时间。"""
import difflib
import math
import re


def normalized(text):
    return ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]', text))


def split_cue(cue, position, words):
    text = cue['text']
    start, end = float(cue['start']), float(cue['end'])
    if not math.isfinite(start + end) or not 0 <= start < end:
        raise ValueError('字幕时间无效')
    if not isinstance(position, int) or not 0 < position < len(text):
        raise ValueError('请将光标放在句子中间，两边都要有文字')
    left, right = text[:position], text[position:]
    boundary = len(normalized(left))
    original = normalized(text)
    if not boundary or boundary >= len(original):
        raise ValueError('分割点两侧都需要有配音文字')
    # 仅取当前句时间范围内的词；每个字符记录所属词，而不是虚构字级时间。
    heard, owners, tokens = '', [], []
    for word in words:
        if word['start'] < start - .06 or word['end'] > end + .06:
            continue
        chars = normalized(word['word'])
        if not chars:
            continue
        owners.extend([len(tokens)] * len(chars))
        heard += chars
        tokens.append(word)
    mapping = {}
    for op, a, b, c, d in difflib.SequenceMatcher(None, original, heard, autojunk=False).get_opcodes():
        if op == 'equal':
            mapping.update({a+i: c+i for i in range(b-a)})
    if boundary-1 not in mapping or boundary not in mapping:
        raise ValueError('分割处缺少可靠语音时间戳，请先试听定位；未修改字幕')
    a, b = mapping[boundary-1], mapping[boundary]
    if b != a+1 or owners[a] == owners[b]:
        raise ValueError('分割点位于同一个识别词内部，暂时没有字级时间戳；请在附近词边界回车，或试听后手动定位')
    left_end = round(float(tokens[owners[a]]['end']), 3)
    right_start = round(float(tokens[owners[b]]['start']), 3)
    if not start < left_end <= right_start < end:
        raise ValueError('分割处时间戳重叠或越界，请试听定位；未修改字幕')
    return [dict(start=start, end=left_end, text=left), dict(start=right_start, end=end, text=right)]

def acoustic_words(words,audio,ffmpeg):
    """词内切点按局部低能量定位，仅为试听草稿，不冒充强制对齐字级真值。"""
    import subprocess,array
    from media import FLAGS
    result=subprocess.run([ffmpeg,'-v','error','-i',str(audio),'-f','s16le','-ac','1','-ar','16000','pipe:1'],capture_output=True,check=True,timeout=45,creationflags=FLAGS)
    samples=array.array('h');samples.frombytes(result.stdout);rate=16000;expanded=[]
    for w in words:
        chars=normalized(w['word']);n=len(chars)
        if n<=1:expanded.append(w);continue
        start,end=float(w['start']),float(w['end']);points=[start]
        for i in range(1,n):
            target=start+(end-start)*i/n;radius=min(.06,(end-start)/n*.35)
            lo=max(int((target-radius)*rate),int(points[-1]*rate)+1);hi=min(int((target+radius)*rate),len(samples)-80)
            choices=list(range(lo,hi+1,32))
            point=min(choices,key=lambda p:sum(v*v for v in samples[max(0,p-40):p+40]))/rate if choices else target
            points.append(point)
        points.append(end)
        expanded.extend(dict(word=char,start=points[i],end=points[i+1]) for i,char in enumerate(chars))
    return expanded
