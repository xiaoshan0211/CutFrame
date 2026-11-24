"""用原片显示帧推定镜头边界，再由视觉模型复核候选窗口。"""
import bisect
import json
import math
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def tool_path(directory, program):
    return Path(directory) / (program + (".exe" if os.name == "nt" else ""))


@lru_cache(maxsize=4)
def media_info(file, tools, run):
    probe = tool_path(tools, 'ffprobe')
    container = json.loads(run([probe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', file], 45))
    streams = container['streams']
    video = next((s for s in streams if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')),None)
    if video is None:
        raise EmptyFootage('已核对容器内全部流，没有运动视频轨')
    return container,video


def read_media(file, tools, run):
    container,video=media_info(file,tools,run)
    streams=container['streams']
    meta = json.loads(run([tool_path(tools, 'ffprobe'), '-v', 'error', '-select_streams', str(video['index']), '-show_frames',
                           '-show_entries', 'frame=best_effort_timestamp_time,pkt_duration_time,duration_time', '-of', 'json', file], 180))
    pts = [float(f['best_effort_timestamp_time']) for f in meta['frames']]
    duration = float(video['duration'])
    if pts and pts[0] > .001 and abs(float(container['format'].get('start_time') or 0))<=.001:
        # 音频先起播的原片，首个视频帧的正偏移属于原片时间轴，不移去。
        last=meta['frames'][-1]
        frame_duration=float(last.get('duration_time',last.get('pkt_duration_time',0)))
        end=round(pts[-1]+frame_duration,6)
        movie_duration=float(container['format']['duration'])
        if frame_duration<=0 or end>movie_duration+.002 or min(abs(end-duration),abs(end-pts[0]-duration))>.003:
            raise ValueError('待用播放器校准原片末帧时间')
        duration=end
    elif pts and pts[0]>.001:
        raise ValueError('非零容器起点，需用播放器核实原片时间轴')
    if not pts or min(pts)<0 or pts[-1]>=duration or any(y <= x for x,y in zip(pts,pts[1:])):
        raise ValueError('需校准显示帧时间')
    width, height = video['width'], video['height']
    if any(abs(int(item.get('rotation', 0))) % 180 == 90 for item in video.get('side_data_list', [])):
        width, height = height, width
    return pts, duration, width, height, any(s['codec_type'] == 'audio' for s in streams)


class EmptyFootage(ValueError):
    """完整解码均为黑场，没有可剪用画面。"""


def scene_ranges(file, count, tools, run):
    source='0:'+str(media_info(file,tools,run)[1]['index'])
    if count>20000:
        # 只传回候选切镜的原帧序号。长原片的缩略帧也不应一次性驻留内存。
        filters=('scale=32:24,settb=1/1000000,setpts=N,select=gt(scene\\,0.30),'
                 'metadata=mode=print:key=lavfi.scene_score:file=-')
        raw=run([tool_path(tools, 'ffmpeg'),'-v','error','-i',file,'-map',source,'-vf',filters,
                 '-an','-vsync','0','-f','null','-'],max(240,count//30))
        cuts=[0]+[int(i) for i in re.findall(rb'\bpts:\s*(\d+)\b',raw) if 0<int(i)<count]+[count]
        cuts=sorted(set(cuts))
        return list(zip(cuts,cuts[1:]))
    raw = run([tool_path(tools, 'ffmpeg'), '-v', 'error', '-i', file, '-map', source, '-vf', 'scale=32:24',
               '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], 240)
    pixels = np.frombuffer(raw, np.uint8).reshape(-1, 24, 32, 3)
    if len(pixels) != count:
        raise ValueError('两次解码的显示帧数不同')
    if np.max(pixels)==0:
        # 小图无像素只能触发核对，再对全分辨率的每一帧检查亮度最大值。
        stats=subprocess.run([str(tool_path(tools, 'ffmpeg')),'-v','error','-i',str(file),'-map',source,'-vf',
                              'format=yuv420p,signalstats,metadata=mode=print:key=lavfi.signalstats.YMAX:file=-',
                              '-an','-f','null','-'],check=True,capture_output=True,timeout=300)
        maxima=re.findall(rb'lavfi\.signalstats\.YMAX=(\d+)',stats.stdout)
        if len(maxima)==count and all(int(v)<=16 for v in maxima):
            raise EmptyFootage(f'原片完整解码 {count} 帧，逐帧最高亮度均处于黑电平，无可见画面')
    cuts = [0]
    for i in range(1, count, 256):
        end = min(i+256, count)
        diff = np.abs(pixels[i:end].astype(np.int16)-pixels[i-1:end-1]).mean(axis=(1, 2, 3))
        cuts.extend((np.flatnonzero(diff > 30)+i).tolist())
    cuts.append(count)
    return list(zip(cuts, cuts[1:]))


def samples(first, last, count):
    return np.linspace(first, last, min(count, last-first+1), dtype=int).tolist()


@lru_cache(maxsize=1)
def _small_preview(file, stamp, source, w, h, count, tools, run):
    raw=run([tool_path(tools, 'ffmpeg'),'-v','error','-i',file,'-map',source,'-vf',f'scale={w}:{h}',
             '-frames:v',str(count+1),'-vsync','0','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],150)
    if len(raw)==count*w*h*3:
        return np.frombuffer(raw,np.uint8).reshape(count,h,w,3)
    return None


def panel(file, indices, width, height, tools, run, size=224):
    w = max(64, round(size*width/max(width,height)))
    h = max(64, round(size*height/max(width,height)))
    selected = '+'.join(f'eq(n\\,{num})' for num in sorted(set(indices)))
    source='0:'+str(media_info(file,tools,run)[1]['index'])
    frame_count=str(media_info(file,tools,run)[1].get('nb_frames',''))
    count=int(frame_count) if frame_count.isdigit() else 0
    frames=None
    if size==224 and max(indices)<count and count*w*h*3<=80_000_000:
        frames=_small_preview(file,file.stat().st_mtime_ns,source,w,h,count,tools,run)
    if frames is None:
        raw = run([tool_path(tools, 'ffmpeg'), '-v', 'error', '-i', file, '-map', source, '-vf',
                   f'select={selected},scale={w}:{h}', '-frames:v', str(len(set(indices))), '-vsync', '0',
                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], 150)
        arr = np.frombuffer(raw,np.uint8).reshape(-1,h,w,3)
        if len(arr) != len(set(indices)):
            raise ValueError('复核图缺帧')
        frames = dict(zip(sorted(set(indices)),arr))
    cols = min(4,len(indices))
    board = Image.new('RGB', (cols*w, math.ceil(len(indices)/cols)*(h+26)))
    draw = ImageDraw.Draw(board)
    for i,num in enumerate(indices):
        x,y = i%cols*w, i//cols*(h+26)
        board.paste(Image.fromarray(frames[num]),(x,y))
        draw.text((x+4,y+h+1),str(i+1),fill='white',font_size=19)
    return board


def window_vote(image, count, ask, times=None):
    prompt = f'这是同一原片按时间排列的{count}格，黑底格号只是复看用。按连续的现场动作或空间展示，保留从第一个能剪用的画面到最后一个能剪用的画面，尽量留足3秒。只要仍在清楚展示同一动作就继续保留。原画面全段有硬字幕、水印或尾卡写 NO。整段可用写 FULL。仅部分可用写 RANGE 起始格序号 结束格序号，序号限1到{count}。没有精华写 NO。下一行只说实际起止画面。'
    if times:prompt+=' 原片时刻（秒）：'+', '.join(f'{i+1}={t:.2f}' for i,t in enumerate(times))
    for attempt in range(2):
        answer=ask(image,prompt if not attempt else prompt+' 第一行必须只含FULL、NO或RANGE和两个整数。')
        vote=re.search(r'(?im)^\s*(?:\*\*)?(FULL|NO|RANGE(?:\s*[:：]?\s+)(\d+)\s*[-—至,，\s]+\s*(\d+))\b',answer)
        if not vote:
            continue
        if vote[1].upper()=='NO':return None
        left,right=(1,count) if vote[1].upper()=='FULL' else (int(vote[2]),int(vote[3]))
        if not 1<=left<right<=count:continue
        evidence=answer[vote.end():].strip(' *：:\n。')
        if len(re.findall(r'[\u4e00-\u9fff]',evidence))<6:
            evidence=ask(image,f'只用一句中文描述第{left}格至第{right}格的实际画面。起点看到什么，末尾看到什么？').strip()
        if len(re.findall(r'[\u4e00-\u9fff]',evidence))>=6:return left-1,right-1,evidence
    raise ValueError('视觉复核未返回有效格序')


def labels(image, groups, dims, ask):
    options={code:(dim,label) for dim in dims for code,label in groups[dim].items()}
    menu='\n'.join(dim+'：'+'、'.join(k if k==v else k+'='+v for k,v in groups[dim].items()) for dim in dims)
    prompt='逐项对照当前秒段和字典，返回有直接可见依据的标签。第一行用中文描述本段动作、对象和位置。其余行每行写一个“正式编码 | 支持该标签的具体画面”。素材类别的编码就是中文名称。无法确认就省略。不得猜人名、材料品名、旧态、前后对照或长期性能。\n'+menu
    ans=ask(image,prompt)
    lines=[line.strip() for line in ans.splitlines() if line.strip()]
    if not lines:return '',{}
    found={}
    for line in lines:
        fields=re.split(r'\s*[|｜]\s*',line.strip(' |-•*\t'),maxsplit=1)
        if len(fields)!=2:continue
        code=re.sub(r'^\d+[.)、]\s*','',fields[0]).strip(' *')
        code=re.sub(r'\s*[·=（(].*$','',code).strip()
        if code not in options: 
            matches=[c for c,(_,label) in options.items() if code==label]
            if len(matches)==1:code=matches[0]
        evidence=fields[1].strip()
        if code in options and code not in ('B5R08','V12','C4A04') and len(re.findall(r'[\u4e00-\u9fff]',evidence))>=5 and not any(x in evidence for x in ['无法确认','不能确认','可能是','疑似']):
            found[code]=evidence
    return lines[0].strip('*# '),found


def complete_primary(image, groups, dim, found, ask):
    if any(code in groups[dim] and code != 'B1U01' for code in found):
        return
    options=[(code,label) for code,label in groups[dim].items() if code not in ('B1U01','V12')]
    menu='\n'.join(f'{i}. {label}' for i,(_,label) in enumerate(options,1))
    answer=ask(image,f'为此镜头选一个有直接依据的{dim}。准确抄写选项名称，换行写一句你看到的具体画面。没有合适选项就只写无。只回答这两行。\n'+menu)
    lines=[line.strip(' *#\t') for line in answer.splitlines() if line.strip()]
    if not lines:return
    top=re.sub(r'^.{0,8}[:：]\s*','',lines[0],count=1)
    pieces=re.split(r'\s*[|｜]\s*',top,maxsplit=1)
    choice=pieces[0].strip('“”「」')
    named=[code for code,label in options if label==choice or label in choice or code==choice]
    number=re.match(r'^(?:序号\s*)?(\d{1,2})\b',choice)
    code=named[0] if len(named)==1 else (options[int(number[1])-1][0] if number and 1<=int(number[1])<=len(options) else None)
    if not code:return
    evidence=(pieces[1] if len(pieces)==2 else ' '.join(lines[1:])).strip()
    if len(re.findall(r'[\u4e00-\u9fff]',evidence))>=6 and not any(x in evidence for x in ('可能','推测','疑似','无法','不能确定')):
        found[code]=evidence


def inspect_media(file, groups, tools, run, ask, all_scenes=False, progress=None, retry=False):
    pts,duration,width,height,audio=read_media(file,tools,run)
    scenes=scene_ranges(file,len(pts),tools,run)
    last_time=lambda i: pts[i] if i<len(pts) else duration
    scenes.sort(key=lambda ab:last_time(ab[1])-pts[ab[0]],reverse=True)
    allowed=[dim for dim in groups if dim not in ['声音','说话','可用时长','可配句意','画幅']]
    results=[]
    reasons=[]
    for first,stop in scenes:
        if progress:progress(f'核对原片 {pts[first]:.3f} 至 {last_time(stop):.3f} 秒')
        if stop-first<2:continue
        indices=samples(first,stop-1,min(40 if retry else 32,max(8,math.ceil((last_time(stop)-pts[first])*(3 if retry else 2)))))
        picture=panel(file,indices,width,height,tools,run,size=336 if retry else 224)
        try:vote=window_vote(picture,len(indices),ask)
        except ValueError:
            reasons.append('初选未给有效边界')
            continue
        if vote is None:
            reasons.append('初看未选中精华')
            continue
        left,right,why=vote
        a,b=indices[left],indices[right]
        # 对初选两端和段内重新抽样。此处格号仅用作查表，绝不直接充当原片帧号。
        start=max(first,indices[max(0,left-1)])
        finish=min(stop-1,indices[min(len(indices)-1,right+1)])
        refine=sorted(set(samples(start,a,4)+samples(a,b,16)+samples(b,finish,4)))
        pic=panel(file,refine,width,height,tools,run)
        try:verified=window_vote(pic,len(refine),ask)
        except ValueError:
            reasons.append('精查未给有效边界')
            continue
        if verified is None:
            reasons.append('边界复看未通过')
            continue
        l,r,reason=verified
        a,b=refine[l],refine[r]
        length=last_time(b+1)-pts[a]
        if length<3 and last_time(stop)-pts[first]>=3:
            start=max(first,bisect.bisect_left(pts,pts[a]-3))
            finish=min(stop-1,bisect.bisect_left(pts,pts[b]+3))
            wider=sorted(set(samples(start,finish,18)+[a,b]))
            wider_board=panel(file,wider,width,height,tools,run)
            try:expanded=window_vote(wider_board,len(wider),ask,[pts[i] for i in wider])
            except ValueError:expanded=None
            if expanded:
                l,r,extra=expanded
                if wider[l]<=a and wider[r]>=b:
                    a,b=wider[l],wider[r]
                    reason=extra
                    length=last_time(b+1)-pts[a]
        if length<3 and b+1!=stop:continue
        if length<3 and stop<len(pts):
            # 亮度突变也会触发候选切点。短段须另看切变两侧才能使用切镜例外。
            before=samples(max(first,b-5),b,3)
            after=samples(stop,min(len(pts)-1,stop+5),3)
            short_context=panel(file,before+after,width,height,tools,run)
            verdict=ask(short_context,f'格1至{len(before)}是候选切点前，后续格是切点后。核实此处是否从一个镜头切到另一个不同镜头。如果切镜明确，第一行写 CUT，第二行列出前后两个镜头分别看到什么。镜头晃动、闪光、快速转动或不确定都写 NO。')
            if not re.match(r'(?is)^\s*CUT\s*\n\s*\S{4}',verdict):continue
            reason+=' '+verdict.split('\n',1)[1].strip()
        image=panel(file,samples(a,b,9),width,height,tools,run)
        desc,tags=labels(image,groups,['画面类型','素材类别'],ask)
        for dim in ('画面类型','素材类别'):
            candidates=[c for c in tags if c in groups[dim]]
            if len(candidates)>2:
                for code in candidates:tags.pop(code)
        for dim in ('画面类型','素材类别'):
            complete_primary(image,groups,dim,tags,ask)
        if not any(code in groups['画面类型'] and code!='B1U01' for code in tags) or not any(code in groups['素材类别'] for code in tags):
            reasons.append('精华窗口缺少明确类别或画面类型')
            continue
        tags.pop('B1U01',None)
        if '|' in desc or '｜' in desc or len(re.findall(r'[\u4e00-\u9fff]',desc))<10 or desc.endswith(('：',':')) or re.search(r'正式编码|用中文描述|第[一二]行用|描述本段|输出',desc):
            desc=ask(image,'这些格是同一镜头在不同时间的画面。只写一句中文，按先后顺序说画面中主体、位置和动作。不要标题、编码或序号。').strip()
            if len(re.findall(r'[\u4e00-\u9fff]',desc))<10 or '|' in desc or '\n' in desc:
                continue
        # 以较大的原帧再次查画面下方、四周及主要动作，避免把模型抄字典写成可检索的事实。
        check=panel(file,samples(a,b,6),width,height,tools,run,size=448)
        selected=[groups[d][c] for d in ('画面类型','素材类别') for c in tags if c in groups[d]]
        check_prompt='这是候选秒段的原帧。请逐项核对描述和所选类别，特别看工具究竟接触墙或地面，移动的是镜头还是物件，以及画面中下方有无消字条、硬字幕、水印、尾卡。每格下方的白色序号是查看器所加，忽略。全部得到原帧支持并且画面干净，第一行写 PASS；看到矛盾、缺少依据或有残留遮罩，写 NO。第二行写可指认的事实。'
        verdict=ask(check,check_prompt+'\n描述：'+desc+'\n类别：'+'、'.join(selected))
        if retry and not re.match(r'(?i)^\s*\**PASS\b',verdict):
            # 对初判冲突的素材，在更大的原图上重述事实、重选两个检索维度。
            revision=ask(check,'重新看图。按时间写一句能逐帧指认的主体、位置与动作，省去原判断所猜测的用途、人物身份与工艺。只写这句话。')
            replacement={}
            for dim in ('画面类型','素材类别'):
                complete_primary(check,groups,dim,replacement,ask)
            if (len(re.findall(r'[\u4e00-\u9fff]',revision))>=8 and '\n' not in revision and
                all(any(c in groups[dim] for c in replacement) for dim in ('画面类型','素材类别'))):
                names=[groups[dim][c] for dim in ('画面类型','素材类别') for c in replacement if c in groups[dim]]
                revised=ask(check,check_prompt+'\n描述：'+revision+'\n类别：'+'、'.join(names))
                if re.match(r'(?i)^\s*\**PASS\b',revised):
                    tags={c:e for c,e in tags.items() if c not in groups['画面类型'] and c not in groups['素材类别']}
                    tags.update(replacement)
                    desc,verdict=revision,revised
        if not re.match(r'(?i)^\s*\**PASS\b',verdict):
            reasons.append('复看时动作、类别或画质未同时通过')
            continue
        # 主要类别和原帧复核通过后，再逐维标注可入表秒段。
        other=[d for d in allowed if d not in ['画面类型','素材类别']]
        for pos in range(0,len(other),7):
            _,more=labels(image,groups,other[pos:pos+7],ask)
            tags.update(more)
        for dim in ('空间','部位','人数','主动作','景别'):
            if dim in groups and not any(code in groups[dim] for code in tags):
                complete_primary(image,groups,dim,tags,ask)
        if width!=height:tags['C1F01' if height>width else 'C1F02']=f'原片显示尺寸{width}×{height}'
        if not audio:tags['C4A01']='原片没有音轨'
        tags['C2D01' if length<1 else 'C2D02' if length<2 else 'C2D03' if length<4 else 'C2D04']=f'连续可用 {length:.6f} 秒'
        note=f'基于原片显示帧{a}至{b}，入点含、出点不含。'+why+' '+reason
        if length<3:note+= ' 不足3秒，保留至'+('实际片尾。' if stop==len(pts) else '复看前后画面确认的切镜，待人工抽查。')
        result=dict(file=str(file),start=pts[a],end=last_time(b+1),width=width,height=height,duration=duration,
                    codes=list(tags),evidence=tags,description=desc,absent=[],note=note,逐项复核=verdict)
        if not all_scenes:return result
        results.append(result)
    if results:return sorted(results,key=lambda r:r['start'])
    raise ValueError('原片待复核：'+('、'.join(dict.fromkeys(reasons)) or '未找到符合时长和切镜条件的窗口'))
