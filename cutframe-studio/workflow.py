# -*- coding: utf-8 -*-
"""本地制作流程所需的资源、字幕、音乐与版本查询。"""
import json,uuid,hashlib,subprocess,time,re,difflib
from pathlib import Path
from flask import request,jsonify,send_file
from media import probe,FLAGS
from composition import parse_srt
from subtitle_split import split_cue,acoustic_words

def register(app,env):
    state=env['STATE'];base=env['BASE'];config=env['CONFIG']
    music_root=Path(config.get('music_root',state/'music'))
    def resource(iid,kind=None):
        row=env['one']('SELECT * FROM imports WHERE id=?',(iid,))
        if not row or (kind and row['kind']!=kind):raise ValueError('资源不存在或类型不符')
        p=env['safe_child'](state/'imports',Path(row['path']).name)
        if not p.is_file():raise ValueError('资源文件不可读')
        return row,p,json.loads(row['meta'])
    def save_subtitles(cues,voice_id=None):
        if not isinstance(cues,list) or not 1<=len(cues)<=500:raise ValueError('字幕应为1至500条')
        def stamp(value):
            ms=round(float(value)*1000)
            if ms<0:raise ValueError('字幕时间不可为负')
            return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
        parts=[]
        for i,c in enumerate(cues):
            text=str(c['text']).strip()
            if '\n' in text or '\r' in text:raise ValueError('字幕须保持单行，请拆分字幕页')
            text=re.sub(r'[，。！？、；：,.!?;:]+$','',text)
            parts.append(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{text}')
        srt='\n\n'.join(parts)+'\n';clean=parse_srt(srt)
        meta=dict(cues=clean,duration=clean[-1]['end'])
        if voice_id:
            _,_,voice=resource(voice_id,'voice')
            if meta['duration']>voice['duration']+.05:raise ValueError('字幕超出配音时长')
            meta['voice_id']=voice_id;meta['voice_sha256']=voice['sha256']
        iid=uuid.uuid4().hex;p=state/'imports'/(iid+'.srt');p.write_text(srt,'utf-8')
        meta['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        name='单行字幕_'+iid[:6]+'.srt'
        env['execute']('INSERT INTO imports VALUES(?,?,?,?,?)',(iid,name,str(p),'subtitle',json.dumps(meta,ensure_ascii=False)))
        return dict(id=iid,name=name,meta=meta)
    @app.get('/api/workflow/resources/<iid>')
    def get_resource(iid):
        row,p,meta=resource(iid)
        return jsonify(id=iid,name=row['name'],kind=row['kind'],meta=meta,url='/api/workflow/media/'+iid)
    @app.get('/api/workflow/media/<iid>')
    def get_media(iid):
        _,p,_=resource(iid);return send_file(p,conditional=True)
    @app.post('/api/workflow/subtitles/save')
    def edit_subtitles():
        d=request.get_json() or {};return jsonify(save_subtitles(d.get('cues'),d.get('voice_id')))
    @app.post('/api/workflow/subtitles/split')
    def split_subtitle():
        d=request.get_json() or {}
        _,audio,voice=resource(d.get('voice_id'),'voice')
        _,_,subtitle=resource(d.get('subtitle_id'),'subtitle')
        if subtitle.get('voice_sha256')!=voice.get('sha256'):
            raise ValueError('字幕与当前配音版本不匹配，请先生成对应字幕')
        # 复用当前音频本地识别结果；仅返回拆分草稿，不覆盖原字幕。
        words=None
        for folder in sorted((state/'jobs').iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
            req=folder/'request.json'
            evidence=folder/'recognition.json'
            if not evidence.is_file(): evidence=folder/'subtitles.json'
            if not req.is_file() or not evidence.is_file(): continue
            r=json.loads(req.read_text('utf-8'))
            if r.get('audio') and Path(r['audio']).resolve()==audio.resolve():
                words=json.loads(evidence.read_text('utf-8')).get('words')
                if words: break
        try:
            return jsonify(cues=split_cue(d['cue'],d.get('position'),words or []),basis='配音识别词边界，待试听核对')
        except ValueError as e:
            if any(s in str(e) for s in ('缺少可靠','识别词内部','时间戳重叠')):
                refined=acoustic_words(words or [],audio,config['ffmpeg'])
                return jsonify(cues=split_cue(d['cue'],d.get('position'),refined),basis='词内声学估计，需试听确认',estimated=True)
            raise
    @app.post('/api/workflow/subtitles/generate')
    def generate_subtitles():
        d=request.get_json() or {};text=d.get('text','')
        if not isinstance(text,str) or not text.strip() or len(text)>500:raise ValueError('请输入1–500字配音原稿')
        _,audio,meta=resource(d.get('voice_id'),'voice');voice_id=d['voice_id']
        # 只检查已生成配音的版本关联，不校验或改写用户文案。
        generated_text=meta.get('tts',{}).get('text','')
        normalize=lambda value: ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',value)).lower()
        if generated_text and difflib.SequenceMatcher(None,normalize(text),normalize(generated_text),autojunk=False).ratio()<.5:
            raise ValueError('当前工程仍采用另一版配音（开头：'+generated_text[:24]+'）。请到第2步选择当前文案对应的配音，试听后点击“用作本工程配音”，再生成字幕；文案未修改。')
        model=base.parent/'local/asr-models/whisper-small'
        if not (model/'model.bin').is_file():raise ValueError('本地字幕模型尚未安装')
        def worker(jid):
            work=state/'jobs'/jid
            req=work/'request.json';req.write_text(json.dumps(dict(audio=str(audio.resolve()),text=text,model=str(model.resolve())),ensure_ascii=False),'utf-8')
            env['update_job'](jid,message='本地识别时间戳，按原稿生成单行字幕')
            with (work/'subtitle.log').open('w',encoding='utf-8') as log:
                p=subprocess.Popen([config['python'],'-u','-X','utf8',str(base/'subtitle_worker.py'),str(req.resolve())],stdout=log,stderr=log,creationflags=FLAGS)
                env['PROCESSES'][jid]=p;start=time.monotonic()
                try:
                    while p.poll() is None:
                        if env['one']('SELECT status FROM jobs WHERE id=?',(jid,))['status']=='cancelled' or time.monotonic()-start>600:
                            p.terminate();p.wait(timeout=15);raise ValueError('字幕任务已取消或超时')
                        time.sleep(.3)
                    if p.returncode:raise ValueError((work/'subtitle.log').read_text('utf-8',errors='replace')[-1200:])
                finally:
                    env['PROCESSES'].pop(jid,None)
                    if p.poll() is None:p.terminate()
            if env['one']('SELECT status FROM jobs WHERE id=?',(jid,))['status']=='cancelled':raise ValueError('已取消')
            result=json.loads((work/'subtitles.json').read_text('utf-8'))
            saved=save_subtitles(result['cues'],voice_id);saved['warnings']=result['warnings'];return saved
        return jsonify(job_id=env['submit']('生成单行字幕',worker))
    def music_items():
        if not music_root.is_dir():raise ValueError('本地音乐目录不可达，可改用文件导入')
        return {hashlib.sha256(p.name.encode()).hexdigest()[:24]:p for p in music_root.iterdir() if p.is_file() and p.suffix.lower() in ('.wav','.mp3','.m4a','.aac')}
    @app.get('/api/workflow/music')
    def list_music():
        return jsonify(items=[dict(id=i,name=p.name) for i,p in sorted(music_items().items(),key=lambda x:x[1].name)])
    @app.get('/api/workflow/music/<key>')
    def play_music(key):
        p=music_items().get(key)
        if not p:raise ValueError('音乐不存在')
        return send_file(p,conditional=True)
    @app.post('/api/workflow/music/use')
    def use_music():
        p=music_items().get((request.get_json() or {}).get('id'))
        if not p:raise ValueError('音乐不存在')
        if p.stat().st_size>256*1024*1024:raise ValueError('音乐文件过大')
        import shutil
        iid=uuid.uuid4().hex;dest=state/'imports'/(iid+p.suffix.lower());shutil.copyfile(p,dest)
        meta=probe(config['ffprobe'],dest)
        if not meta['audio']:raise ValueError('没有音轨')
        meta.update(sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),source_name=p.name)
        env['execute']('INSERT INTO imports VALUES(?,?,?,?,?)',(iid,p.name,str(dest),'music',json.dumps(meta,ensure_ascii=False)))
        return jsonify(id=iid,name=p.name,meta=meta)
    @app.get('/api/workflow/films/<pid>')
    def films(pid):
        items=[]
        for row in env['many']("SELECT id,result FROM jobs WHERE kind='单条完整成片' AND status='done' ORDER BY created DESC"):
            r=json.loads(row['result'])
            if r['project_id']==pid:
                p=state/'jobs'/row['id']/'project.json'
                items.append(dict(result=r,project=json.loads(p.read_text('utf-8')) if p.exists() else None))
        return jsonify(items=items)
