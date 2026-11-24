"""人工选片的单条成片；不调用模型，不自动补片或变速。"""
from __future__ import annotations
import io
import json
import math
import re
import uuid
import hashlib
from pathlib import Path
from flask import request, jsonify, send_file
from media import probe, seconds, validate_range, sdr_filter, encoder_args
from caption_fonts import FAMILIES, font_style, subtitle_filter

def parse_srt(text):
    text=text.lstrip('\ufeff').replace('\r\n','\n').strip()
    cues=[]
    def stamp(t):
        h,m,s,ms=map(int,re.split('[:,.]',t))
        if m>=60 or s>=60: raise ValueError('字幕时间格式无效')
        return h*3600+m*60+s+ms/1000
    for block in re.split(r'\n\s*\n',text):
        lines=block.splitlines()
        if lines and lines[0].strip().isdigit(): lines=lines[1:]
        if not lines: continue
        match=re.fullmatch(r'(\d{2,}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2,}:\d{2}:\d{2}[,.]\d{3})',lines[0].strip())
        if not match or len(lines)<2: raise ValueError('字幕需为 UTF-8 SRT，包含时间码和文字')
        start,end=stamp(match[1]),stamp(match[2])
        if end<=start: raise ValueError('字幕结束时间必须晚于开始')
        if cues and start<cues[-1]['end']-.001: raise ValueError('字幕存在重叠或时间倒序，请先修正')
        body=''.join(lines[1:]).strip()
        if any(x in body for x in ('{','}','\\','<','>')): raise ValueError('首版只接受纯文字字幕，请移除格式控制标签')
        if not body: raise ValueError('字幕内容为空')
        cues.append(dict(start=start,end=end,text=body))
    if not cues: raise ValueError('字幕为空')
    return cues

def ass_time(t):
    cs=round(t*100)
    return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'

def write_ass(path,cues,w,h,size,bottom,offset,family='yahei',weight='regular'):
    # 使用用户设置的统一字号，不自动缩小；保持单行。
    fitted=size
    text=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FAMILIES[family]},{size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,{-1 if weight=='bold' else 0},0,0,0,100,100,0,0,1,2,1,2,50,50,{bottom},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    for cue in cues:
        display=re.sub(r'[，。！？、；：,.!?;:]+$','',cue['text'].strip())
        text+=f"Dialogue: 0,{ass_time(cue['start']+offset)},{ass_time(cue['end']+offset)},Default,,0,0,0,,{{\\fs{fitted}}}{display}\n"
    path.write_text(text,'utf-8-sig')

def register(app, env):
    STATE,CONFIG=env['STATE'],env['CONFIG']
    execute,one,many=env['execute'],env['one'],env['many']
    get_asset,asset_path,metadata=env['get_asset'],env['asset_path'],env['metadata']
    now,clean_name=env['now'],env['clean_name']

    def get_import(iid,kind):
        row=one('SELECT * FROM imports WHERE id=?',(iid,))
        if not row or row['kind']!=kind: raise ValueError('导入资源不存在或类型不符：'+kind)
        path=env['safe_child'](STATE/'imports',Path(row['path']).name)
        if not path.is_file(): raise ValueError('导入资源缺失：'+row['name'])
        return row,path,json.loads(row['meta'])

    @app.post('/api/imports')
    def import_file():
        kind=request.form.get('kind')
        f=request.files.get('file')
        if kind not in ('voice','music','subtitle') or not f: raise ValueError('请选择配音、字幕或音乐文件')
        suffix=Path(f.filename).suffix.lower()
        if kind=='subtitle' and suffix!='.srt': raise ValueError('只接受 SRT 字幕')
        if kind!='subtitle' and suffix not in ('.mp3','.wav','.m4a','.aac'): raise ValueError('声音格式需为 WAV/MP3/M4A/AAC')
        iid=uuid.uuid4().hex
        path=STATE/'imports'/(iid+suffix)
        f.save(path)
        if kind=='subtitle':
            try: text=path.read_text('utf-8-sig')
            except UnicodeDecodeError: raise ValueError('请将字幕另存为 UTF-8 后导入')
            cues=parse_srt(text); meta=dict(cues=cues,duration=cues[-1]['end'])
        else:
            meta=probe(CONFIG['ffprobe'],path)
            if not meta['audio']: raise ValueError('文件没有可用音轨')
        meta['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        execute('INSERT INTO imports VALUES(?,?,?,?,?)',(iid,f.filename,str(path),kind,json.dumps(meta,ensure_ascii=False)))
        return jsonify(id=iid,name=f.filename,meta={k:v for k,v in meta.items() if k!='cues'})

    def validate(data,render=False):
        name=clean_name(data.get('name',''))
        shots=data.get('shots',[])
        if len(shots)>100: raise ValueError('单条工程最多 100 个镜头')
        s=data.get('settings',{})
        font_style(s)
        if s.get('canvas','1080x1920') not in ('1080x1920','1920x1080'): raise ValueError('不支持的画幅')
        if s.get('fps',30) not in (24,25,30): raise ValueError('不支持的帧率')
        if s.get('fit','contain') not in ('contain','cover'): raise ValueError('画面适配无效')
        if s.get('source_audio','mute') not in ('mute','keep'): raise ValueError('原声设置无效')
        for key,default,lo,hi in [('voice_offset',0,0,3600),('music_start',0,0,36000),('music_volume',.12,0,1),('music_fade',0,0,10),('subtitle_offset',0,-3600,3600),('subtitle_bottom',360,0,600)]:
            v=float(s.get(key,default))
            if not math.isfinite(v) or not lo<=v<=hi: raise ValueError('设置超出范围：'+key)
            s[key]=v
        font=float(s.get('font_size',72))
        if not math.isfinite(font) or font<=0: raise ValueError('字幕字号须为大于0的有限数值')
        s['font_size']=font
        total=0;source_durations={};render_shots=None
        for shot in shots:
            a=get_asset(shot['asset_id'])
            if render:
                meta=metadata(a); start,end=validate_range(shot['start'],shot['end'],meta['duration'])
                from media import probe,is_portrait_916
                if not is_portrait_916(probe(env['CONFIG']['ffprobe'],asset_path(a))):raise ValueError('仅允许原始9:16竖屏素材，请替换：'+a['name'])
                source_durations[shot['asset_id']]=meta['duration']
            else:
                start,end=seconds(shot['start']),seconds(shot['end'])
                if end<=start: raise ValueError('镜头出点必须晚于入点')
            total+=end-start
        early_board=data.get('workflow',{}).get('storyboard',{}) or {}
        if render and early_board.get('mode')=='subtitle' and early_board.get('gap_policy')=='continue_previous':
            from subtitle_board import continue_gap_shots
            _,_,voice=get_import(data.get('imports',{}).get('voice'),'voice')
            render_shots=continue_gap_shots(early_board.get('tasks',[]),shots,voice['duration']+s['voice_offset'],source_durations)
            total=sum(x['end']-x['start'] for x in render_shots)
        if total>1800: raise ValueError('单条验证片最多 30 分钟')
        if render and not shots: raise ValueError('请先添加镜头')
        imported=data.get('imports',{})
        for kind,iid in imported.items():
            if kind not in ('voice','music','subtitle'): raise ValueError('不支持的资源类型')
            row,path,meta=get_import(iid,kind)
            if render:
                if kind=='subtitle' and meta.get('voice_id') and meta['voice_id']!=imported.get('voice'):
                    raise ValueError('字幕对应旧配音，请按当前配音重新生成字幕')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']: raise ValueError('导入文件内容发生变化，请重新导入')
                if kind=='voice' and meta['duration']+s['voice_offset']>total+.05: raise ValueError('配音超出画面总时长，请增加画面或调整起点；不自动截断配音')
                if kind=='music' and meta['duration']-s['music_start']<total-.05: raise ValueError('音乐长度不足，请更换音乐或调整入点；不自动循环')
                if kind=='subtitle' and (meta['cues'][0]['start']+s['subtitle_offset']<0 or meta['duration']+s['subtitle_offset']>total+.05): raise ValueError('字幕超出成片时间范围，请调整偏移或字幕')
        if render and 'voice' not in imported: raise ValueError('B阶段请导入现成配音')
        if render and 'subtitle' not in imported: raise ValueError('B阶段请导入现成字幕')
        workflow=data.get('workflow',{})
        if not isinstance(workflow,dict):raise ValueError('流程记录无效')
        script=str(workflow.get('script',''))
        if len(script)>500:raise ValueError('文案最多500字')
        storyboard=workflow.get('storyboard')
        if storyboard is not None:
            if not isinstance(storyboard,dict) or len(json.dumps(storyboard,ensure_ascii=False))>500000:
                raise ValueError('选片工作台记录无效或过大')
            tasks=storyboard.get('tasks',[]); candidates=storyboard.get('candidates',[])
            if not isinstance(tasks,list) or len(tasks)>100 or not isinstance(candidates,list) or len(candidates)>300:
                raise ValueError('画面任务最多100项，候选最多300项')
            ids=set()
            for task in tasks:
                if not isinstance(task,dict) or not isinstance(task.get('id'),str) or task['id'] in ids:
                    raise ValueError('画面任务标识无效')
                ids.add(task['id'])
                for key in ('start','end'):
                    if not isinstance(task.get(key),(int,float)) or not math.isfinite(task[key]) or not 0<=task[key]<=1800:
                        raise ValueError('画面任务时间无效')
                for key in ('text','need','role'):
                    if not isinstance(task.get(key),str) or len(task[key])>2000:raise ValueError('画面任务文字无效')
            for candidate in candidates:
                if not isinstance(candidate,dict) or not isinstance(candidate.get('asset_id'),str):raise ValueError('候选记录无效')
        if render and storyboard and storyboard.get('mode')=='subtitle':
            from subtitle_board import validate_subtitle_board
            _,_,sub=get_import(imported['subtitle'],'subtitle')
            _,_,voice=get_import(imported['voice'],'voice')
            validate_subtitle_board(storyboard,shots,sub['cues'],voice['duration']+s['voice_offset'],workflow,s,imported)
        scope=workflow.get('material_scope','all')
        if scope!='all' and CONFIG['roots'].get(scope,{}).get('role')!='raw':
            raise ValueError('工程所选素材库不可用，请重新选择素材来源')
        workflow=dict(script=script,step=max(1,min(6,int(workflow.get('step',1)))),confirmed_voice=workflow.get('confirmed_voice'),confirmed_subtitle=workflow.get('confirmed_subtitle'),no_music=bool(workflow.get('no_music',False)))
        if scope!='all':workflow['material_scope']=scope
        if storyboard is not None:workflow['storyboard']=storyboard
        result=dict(id=data.get('id'),name=name,shots=shots,imports=imported,settings=s,duration=total,workflow=workflow)
        if render_shots is not None:result['render_shots']=render_shots
        return result

    def save(data):
        data=validate(data)
        pid=data.get('id') or uuid.uuid4().hex
        if not re.fullmatch('[0-9a-f]{32}',pid): raise ValueError('工程标识无效')
        data['id']=pid
        previous=one('SELECT data FROM projects WHERE id=?',(pid,))
        data['version']=(json.loads(previous['data']).get('version',0)+1) if previous else 1
        execute('INSERT INTO projects VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,data=excluded.data,updated=excluded.updated',
                (pid,data['name'],json.dumps(data,ensure_ascii=False),now()))
        (STATE/'metadata'/f"project-{pid}-v{data['version']}.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
        return data

    @app.get('/api/projects')
    def projects(): return jsonify(items=many('SELECT id,name,updated FROM projects ORDER BY updated DESC'))

    @app.post('/api/projects')
    def save_project(): return jsonify(save(request.get_json()))

    @app.get('/api/projects/<pid>')
    def load_project(pid):
        row=one('SELECT data FROM projects WHERE id=?',(pid,))
        if not row: raise ValueError('工程不存在')
        data=json.loads(row['data'])
        data['import_names']={kind:get_import(iid,kind)[0]['name'] for kind,iid in data['imports'].items()}
        return jsonify(data)

    @app.post('/api/render')
    def render():
        data=validate(request.get_json(),True)
        render_shots=data.pop('render_shots',None);render_duration=data['duration']
        data=save(data)
        # 工程仍保存人工选段；渲染单独使用派生范围，避免再次导出时重复延长。
        data['duration']=render_duration
        render_shots=render_shots if render_shots is not None else data['shots']
        data['render_shots']=render_shots
        w,h=map(int,data['settings'].get('canvas','1080x1920').split('x'))
        s=data['settings'];fps=int(s.get('fps',30));total=data['duration']
        def worker(jid):
            work=STATE/'jobs'/jid
            (work/'project.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
            source_records=[]
            for i,shot in enumerate(render_shots):
                a=get_asset(shot['asset_id']);source=asset_path(a);m=metadata(a);st=source.stat()
                source_records.append(dict(asset_id=a['id'],root_alias=a['root'],relative_path=a['rel'],size=st.st_size,stamp=st.st_mtime_ns))
                start,end=validate_range(shot['start'],shot['end'],m['duration']);duration=end-start
                if data.get('workflow',{}).get('storyboard',{}).get('mode')=='subtitle':
                    from subtitle_board import frame_duration
                    duration=frame_duration(shot['timeline_start'],shot['timeline_start']+duration,fps)
                segment=work/f'segment-{i:03d}.mkv'
                cmd=[CONFIG['ffmpeg'],'-hide_banner','-nostdin','-n','-ss',str(start),'-i',str(source)]
                use_audio=s.get('source_audio','mute')=='keep' and m['audio']
                if not use_audio: cmd+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                vf=sdr_filter(m)
                if s.get('fit','contain')=='contain': vf+=f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black'
                else: vf+=f'scale={w}:{h}:force_original_aspect_ratio=increase:force_divisible_by=2,crop={w}:{h}'
                vf+=f',setsar=1,fps={fps},setpts=PTS-STARTPTS'
                cmd+=['-t',str(duration),'-map','0:'+str(m.get('video_index',0)),'-map','0:a:0' if use_audio else '1:a:0','-vf',vf,
                      '-af','aresample=48000,asetpts=PTS-STARTPTS,apad']+encoder_args(CONFIG)+['-c:a','pcm_s16le','-ar','48000','-ac','2',str(segment)]
                env['update_job'](jid,message=f'统一镜头 {i+1}/{len(data["shots"])}')
                env['run_media'](jid,cmd,duration,f'segment-{i:03d}.log')
            listing=work/'concat.txt'
            listing.write_text(''.join(f"file 'segment-{i:03d}.mkv'\n" for i in range(len(data['shots']))),'utf-8')
            joined=work/'joined.mkv'
            env['run_media'](jid,[CONFIG['ffmpeg'],'-hide_banner','-nostdin','-n','-f','concat','-safe','1','-i','concat.txt','-c','copy',str(joined)],total,'concat.log',str(work))
            inputs=[CONFIG['ffmpeg'],'-hide_banner','-nostdin','-n','-i',str(joined)]
            filters=[];audios=['[0:a]'] if s.get('source_audio')=='keep' else [];input_index=1
            for kind in ('voice','music'):
                iid=data['imports'].get(kind)
                if not iid: continue
                _,p,m=get_import(iid,kind)
                inputs+=['-i',str(p)]
                if kind=='voice': af=f'atrim=0:{m["duration"]},asetpts=PTS-STARTPTS,adelay={round(s["voice_offset"]*1000)}:all=1,apad'
                else:
                    fade=min(s.get('music_fade',0),total)
                    af=f'atrim=start={s["music_start"]}:duration={total},asetpts=PTS-STARTPTS,volume={s["music_volume"]}'
                    if fade:af+=f',afade=t=out:st={total-fade}:d={fade}'
                    af+=',apad'
                filters.append(f'[{input_index}:a]{af}[{kind}]');audios.append(f'[{kind}]');input_index+=1
            # 只有人声时直接使用原配音。混音时扣除限幅器的前视延迟，让原句始终落在原时间点。
            if len(audios)==1:
                filters.append(f'{audios[0]}atrim=duration={total}[audio]')
            else:
                mix=f'amix=inputs={len(audios)}:duration=longest:dropout_transition=0,volume={len(audios)}'
                filters.append(''.join(audios)+f'{mix},alimiter=limit=0.891:attack=5:level=false,atrim=start=0.005,asetpts=PTS-STARTPTS,atrim=duration={total}[audio]')
            _,_,submeta=get_import(data['imports']['subtitle'],'subtitle')
            family,weight=font_style(s)
            if env.get('caption_artwork'):
                overlay_input, overlay_filter = env['caption_artwork'](work,submeta['cues'],s,w,h,fps,total,input_index)
                inputs.extend(overlay_input)
                filters.append(overlay_filter)
            else:
                write_ass(work/'captions.ass',submeta['cues'],w,h,s['font_size'],int(s['subtitle_bottom']),s['subtitle_offset'],family,weight)
                filters.append('[0:v]'+subtitle_filter(work,family,weight)+'[video]')
            out=work/'film.mp4'
            cmd=inputs+['-filter_complex',';'.join(filters),'-map','[video]','-map','[audio]','-t',str(total)]+encoder_args(CONFIG)+['-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-movflags','+faststart',str(out)]
            env['update_job'](jid,message='合成字幕、配音和音乐')
            env['run_media'](jid,cmd,total,'composition.log',str(work))
            meta=probe(CONFIG['ffprobe'],out)
            if abs(meta['duration']-total)>.25: raise ValueError('合成时长偏差超出容差，未发布结果')
            for r in source_records:
                st=asset_path(get_asset(r['asset_id'])).stat()
                if st.st_size!=r['size'] or st.st_mtime_ns!=r['stamp']: raise ValueError('合成期间原始素材发生变化，未发布')
            env['update_job'](jid,message='验证整条文件可解码')
            env['run_media'](jid,[CONFIG['ffmpeg'],'-v','error','-i',str(out),'-f','null','-'],total,'decode.log')
            if one('SELECT status FROM jobs WHERE id=?',(jid,))['status']=='cancelled': raise ValueError('用户已取消')
            target=env['publish'](out,'成片验证',data['name']+f"_v{data['version']}")
            result=dict(path=str(target),project_id=data['id'],version=data['version'],duration=meta['duration'],url='/api/films/'+jid,
                        review='技术生成完成，仍需人工完整观看、听审与切点验收')
            (STATE/'metadata'/f'film-{jid}.json').write_text(json.dumps(dict(project=data,result=result,sources=source_records),ensure_ascii=False,indent=2),'utf-8')
            return result
        jid=env['submit']('单条完整成片',worker)
        return jsonify(job_id=jid,project_id=data['id'])

    @app.get('/api/films/<jid>')
    def film(jid):
        row=one('SELECT result,status,kind FROM jobs WHERE id=?',(jid,))
        if not row or row['status']!='done' or row['kind']!='单条完整成片': raise ValueError('成片尚未完成')
        path=Path(json.loads(row['result'])['path'])
        if not path.resolve().is_relative_to(env['output_root']()): raise ValueError('输出不属于当前目录')
        return send_file(path,conditional=True)
