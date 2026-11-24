"""单条本地配音，复用工作台任务锁、取消与资源记录。"""
import json, uuid, subprocess, shutil, time, math, hashlib
from pathlib import Path
from flask import request, jsonify, send_file
from media import probe, FLAGS

def register(app, env):
    state=env['STATE']; base=env['BASE']
    approval=base.parent/'local/songchi-trained/音色定版.json'
    def approved():
        if not approval.is_file(): raise ValueError('缺少已确认的音色配置')
        result=json.loads(approval.read_text('utf-8'))
        for path in (result['selected']['gpt_model'],result['selected']['sovits_model'],result['selected']['parameters']['ref_audio_path']):
            if not Path(path).is_file(): raise ValueError('配音模型或参考音频不可读')
        return result

    @app.get('/api/tts')
    def history():
        rows=env['many']("SELECT * FROM imports WHERE kind='voice' ORDER BY rowid DESC LIMIT 100")
        items=[]
        for row in rows:
            meta=json.loads(row['meta'])
            if meta.get('tts'):
                items.append(dict(id=row['id'],name=row['name'],duration=meta['duration'],text=meta['tts']['text'],speed=meta.get('voice_speed',1),url='/api/voice/'+row['id']))
        return jsonify(items=items,voice='松弛男 · G版定版')

    @app.get('/api/voice/<iid>')
    def audio(iid):
        row=env['one']("SELECT * FROM imports WHERE id=? AND kind='voice'",(iid,))
        if not row: raise ValueError('配音不存在')
        path=env['safe_child'](state/'imports',Path(row['path']).name)
        return send_file(path,conditional=True)

    @app.post('/api/tts/speed')
    def change_speed():
        data=request.get_json() or {}
        try: rate=float(data.get('speed'))
        except (TypeError,ValueError): raise ValueError('请输入有效的配音语速')
        if not math.isfinite(rate) or not .5<=rate<=2: raise ValueError('配音语速范围为0.5—2.0倍')
        selected=env['one']("SELECT * FROM imports WHERE id=? AND kind='voice'",(data.get('voice_id'),))
        if not selected: raise ValueError('请先选择配音')
        selected_meta=json.loads(selected['meta'])
        original_id=selected_meta.get('speed_original_id',selected['id'])
        original=env['one']("SELECT * FROM imports WHERE id=? AND kind='voice'",(original_id,))
        if not original: raise ValueError('原始配音不存在，请重新导入')
        original_meta=json.loads(original['meta'])
        if not original_meta.get('tts'): raise ValueError('请选择生成的配音')
        source=env['safe_child'](state/'imports',Path(original['path']).name)
        def worker(jid):
            path=state/'jobs'/jid/'speed.wav'
            env['run_media'](jid,[env['CONFIG']['ffmpeg'],'-hide_banner','-nostdin','-n','-i',str(source),'-vn','-af',f'atempo={rate:.6f}','-c:a','pcm_s16le',str(path)],original_meta['duration']/rate)
            meta=probe(env['CONFIG']['ffprobe'],path)
            if not meta['audio']: raise ValueError('变速结果缺少音轨')
            meta.update(tts={**original_meta['tts'],'review':'变速后待人工试听'},voice_speed=rate,speed_original_id=original_id,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            iid=uuid.uuid4().hex;dest=state/'imports'/(iid+'.wav');shutil.copyfile(path,dest)
            label=Path(original['name']).stem+f'_语速{rate:g}倍_'+iid[:6]+'.wav'
            env['execute']('INSERT INTO imports VALUES(?,?,?,?,?)',(iid,label,str(dest),'voice',json.dumps(meta,ensure_ascii=False)))
            return dict(id=iid,name=label,duration=meta['duration'],text=meta['tts']['text'],speed=rate,url='/api/voice/'+iid)
        return jsonify(job_id=env['submit']('生成变速配音试听',worker))

    @app.post('/api/tts')
    def generate():
        data=request.get_json() or {}
        text=data.get('text')
        if not isinstance(text,str) or not text.strip(): raise ValueError('请输入配音文案')
        if len(text)>500: raise ValueError('首版单条配音最多500字，请缩短文案')
        if any(ord(c)<32 and c not in '\n\r\t' for c in text): raise ValueError('文案含无效控制字符')
        name=env['clean_name'](data.get('name') or '武汉翻新')
        selection=approved()
        def worker(jid):
            folder=state/'jobs'/jid
            (folder/'request.json').write_text(json.dumps(dict(text=text,approved=selection),ensure_ascii=False,indent=2),'utf-8')
            env['update_job'](jid,message='本地加载G版音色并生成，首次加载约需1分钟')
            with (folder/'tts.log').open('w',encoding='utf-8') as log:
                process=subprocess.Popen([env['CONFIG']['python'],'-u','-X','utf8',str(base/'tts_worker.py'),str((folder/'request.json').resolve())],stdout=log,stderr=log,creationflags=FLAGS)
                env['PROCESSES'][jid]=process
                started=time.monotonic()
                try:
                    while process.poll() is None:
                        status=env['one']('SELECT status FROM jobs WHERE id=?',(jid,))['status']
                        if status=='cancelled' or time.monotonic()-started>600:
                            process.terminate();process.wait(timeout=15)
                            raise ValueError('配音已取消或处理超时，源文件未改动')
                        time.sleep(.3)
                    if process.returncode: raise ValueError('本地配音失败，请查看任务目录中的tts.log')
                finally:
                    env['PROCESSES'].pop(jid,None)
                    if process.poll() is None: process.terminate()
            if env['one']('SELECT status FROM jobs WHERE id=?',(jid,))['status']=='cancelled': raise ValueError('已取消')
            path=folder/'voice.wav';meta=probe(env['CONFIG']['ffprobe'],path)
            if not meta['audio']: raise ValueError('生成文件没有音轨')
            record=json.loads((folder/'generation.json').read_text('utf-8'))
            meta.update(sha256=record['sha256'],tts=dict(text=text,job_id=jid,voice='G版',review='待人工试听'))
            iid=uuid.uuid4().hex;dest=state/'imports'/(iid+'.wav')
            shutil.copyfile(path,dest)
            label=name+'_松弛男G_'+jid[:6]+'.wav'
            env['execute']('INSERT INTO imports VALUES(?,?,?,?,?)',(iid,label,str(dest),'voice',json.dumps(meta,ensure_ascii=False)))
            return dict(id=iid,name=label,duration=meta['duration'],text=text,url='/api/voice/'+iid)
        return jsonify(job_id=env['submit']('本地配音 · 松弛男G版',worker))
