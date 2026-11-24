# -*- coding: utf-8 -*-
"""本地转写只提供时间；字幕文字取自用户原稿，差异保留供逐句核对。"""
import json,re,difflib,sys,os
from pathlib import Path
from opencc import OpenCC

# 只规范化识别侧用于时间匹配的字符，绝不改写用户原稿。
_simplify = OpenCC('t2s')

def align(text, words):
    chars=[];times=[]
    for word in words:
        cs=re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',_simplify.convert(word['word']))
        for i,c in enumerate(cs):
            chars.append(c);times.append((word['start']+(word['end']-word['start'])*i/len(cs),word['start']+(word['end']-word['start'])*(i+1)/len(cs)))
    original=''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',text));heard=''.join(chars)
    if not original or not heard: raise ValueError('没有可对齐的语音或文字')
    matcher=difflib.SequenceMatcher(None,original,heard,autojunk=False)
    if matcher.ratio()<.5: raise ValueError('本地识别可用时间锚点不足，暂不能生成可靠字幕；这不代表原稿或配音有误')
    mapped={};warnings=[];uncertain=set()
    for op,a,b,c,d in matcher.get_opcodes():
        if op=='equal':
            for i in range(b-a):mapped[a+i]=times[c+i]
        elif op=='replace' and b-a==d-c:
            for i in range(b-a):mapped[a+i]=times[c+i]
            warnings.append(f'识别文字存在差异，字幕已保留原稿「{original[a:b]}」')
        elif op=='replace':
            # 只在识别给出的局部时间窗中分配原稿字符，不修改文字。
            left,right=times[c][0],times[d-1][1]
            for i in range(b-a):
                mapped[a+i]=(left+(right-left)*i/(b-a),left+(right-left)*(i+1)/(b-a))
                uncertain.add(a+i)
        elif op=='delete':
            # 识别遗漏不是配音遗漏；留给整句的相邻锚点定位。
            uncertain.update(range(a,b))
        elif op=='insert':
            warnings.append('识别出现原稿之外的文字，未写入字幕；请试听对应句时间')
    # 按原稿自然停顿分页，不按固定字数拆词；超出单行宽度由导出校验提示。
    parts=[]
    for clause in re.split(r'[，。！？；：,.!?;:\n\r]+',text):
        clause=clause.strip()
        if clause:
            parts.append(clause)
    cues=[];offset=0
    for part in parts:
        count=len(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',part))
        if not count: continue
        first,last=offset,offset+count-1;offset+=count
        anchors=[i for i in range(first,last+1) if i in mapped]
        if not anchors:
            raise ValueError(f'「{part}」没有可用的局部时间锚点，需手动定位；原稿和配音未修改')
        start=mapped[anchors[0]][0];end=mapped[anchors[-1]][1]
        if first not in mapped:
            previous=[i for i in mapped if i<first]
            if not previous: raise ValueError('开头缺少时间锚点，需手动定位；原稿和配音未修改')
            start=mapped[max(previous)][1]
        if last not in mapped:
            following=[i for i in mapped if i>last]
            if not following: raise ValueError('末句结尾缺少时间锚点，需手动定位；原稿和配音未修改')
            end=mapped[min(following)][0]
        if any(i in uncertain for i in range(first,last+1)):
            warnings.append(f'「{part}」识别时间不完整，已保留整句并按局部锚点定位，请试听核对 {start:.2f}–{end:.2f}秒')
        if end<=start: raise ValueError('时间戳异常，请人工核对配音')
        cues.append(dict(start=round(start,3),end=round(end,3),text=part))
    return cues,warnings

if __name__=='__main__':
    os.environ['HF_HUB_OFFLINE']='1'
    from faster_whisper import WhisperModel
    request_path=Path(sys.argv[1]);data=json.loads(request_path.read_text('utf-8'))
    model=WhisperModel(data['model'],device='cpu',compute_type='int8',cpu_threads=6)
    segments,_=model.transcribe(data['audio'],language='zh',beam_size=5,word_timestamps=True,condition_on_previous_text=False)
    words=[dict(start=w.start,end=w.end,word=w.word) for s in segments for w in s.words]
    # 无论对齐是否成功，都保留本地识别证据，便于定位问题。
    (request_path.parent/'recognition.json').write_text(json.dumps(dict(words=words),ensure_ascii=False,indent=2),'utf-8')
    try:
        cues,warnings=align(data['text'],words)
    except ValueError as exc:
        print(str(exc),flush=True)
        sys.exit(2)
    (request_path.parent/'subtitles.json').write_text(json.dumps(dict(cues=cues,warnings=warnings,words=words),ensure_ascii=False,indent=2),'utf-8')
