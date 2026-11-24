"""离线Chinese-CLIP抽帧索引与候选排序。绝不调用远程推理服务。"""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
import sys,json,hashlib,subprocess,time
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from transformers import ChineseCLIPModel,ChineseCLIPProcessor
from ai_store import select_diverse

MODEL='OFA-Sys/chinese-clip-vit-base-patch16@36e679e65c2a2fead755ae21162091293ad37834'
reqpath=Path(sys.argv[1]);req=json.loads(reqpath.read_text('utf-8'));work=reqpath.parent
device='cuda' if torch.cuda.is_available() else 'cpu'
torch.set_num_threads(4)
model=ChineseCLIPModel.from_pretrained(req['model_path'],local_files_only=True).to(device).eval()
processor=ChineseCLIPProcessor.from_pretrained(req['model_path'],local_files_only=True)

def vector_images(paths):
    ims=[Image.open(p).convert('RGB') for p in paths]
    try:
        data=processor(images=ims,return_tensors='pt').to(device)
        with torch.inference_mode(): v=model.get_image_features(**data)
        return torch.nn.functional.normalize(v,dim=-1).cpu().numpy()
    finally:
        for im in ims:im.close()

def vector_text(text):
    data=processor(text=[text],padding=True,truncation=True,max_length=512,return_tensors='pt').to(device)
    # transformers 4.57.3 的辅助方法误取未启用的 pooler；本模型使用最后层 CLS 投影。
    with torch.inference_mode(): v=model.text_projection(model.text_model(**data).last_hidden_state[:,0,:])
    return torch.nn.functional.normalize(v,dim=-1).cpu().numpy()[0]

def phash(path):
    with Image.open(path) as im:
        a=np.asarray(im.convert('L').resize((9,8))).astype(float)
    bits=(a[:,1:]>a[:,:-1]).flatten()
    return hex(int(''.join('1' if b else '0' for b in bits),2))[2:].zfill(16)

if req['mode']=='discover':
    from ai_discovery import discover
    output=discover(req,work,vector_images,vector_text,phash,MODEL,device)
    (work/'result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),'utf-8')
    sys.exit(0)
if req['mode']=='index':
    rows=[];vectors=[];errors=[]
    previous=[];previous_vectors=[]
    if req.get('reuse_index'):
        old=Path(req['reuse_index']);previous=json.loads(old.read_text('utf-8'))['frames'];previous_vectors=np.load(old.with_name('vectors.npy'))
    for n,a in enumerate(req['assets']):
        try:
            source=Path(a['path']);st=source.stat()
            cached=[i for i,r in enumerate(previous) if r['asset_id']==a['id'] and r['size']==st.st_size and r['mtime']==st.st_mtime_ns and Path(r['image']).exists()]
            if cached:
                rows.extend(previous[i] for i in cached);vectors.extend(previous_vectors[i] for i in cached)
                (work/'progress.json').write_text(json.dumps(dict(done=n+1,total=len(req['assets']))),'utf-8')
                continue
            # 均匀覆盖全源，最长片最多60采样点；记录密度，避免冒充逐帧理解。
            count=max(1,min(60,int(a['duration']/2)+1))
            times=np.linspace(0,max(0,a['duration']-.3),count)
            folder=work/'frames'/a['id'];folder.mkdir(parents=True,exist_ok=True)
            images=[];current=[]
            for i,t in enumerate(times):
                dest=folder/(str(i)+'.jpg')
                command=[req['ffmpeg'],'-hide_banner','-loglevel','error','-ss',str(t),'-i',str(source),'-frames:v','1','-vf','scale=384:-2','-q:v','4','-y',str(dest)]
                subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=40,creationflags=0x08000000)
                if not dest.exists():
                    errors.append(dict(asset_id=a['id'],error=f'源 {t:.3f} 秒无可解码画面，跳过该采样点'))
                    continue
                images.append(str(dest));current.append(dict(asset_id=a['id'],name=a['name'],root=a['root'],rel=a['rel'],path=str(source),duration=a['duration'],center=round(float(t),4),image=str(dest),phash=phash(dest),size=st.st_size,mtime=st.st_mtime_ns,sample_step=round(a['duration']/max(1,count-1),3)))
            current_vectors=[]
            for i in range(0,len(images),16):current_vectors.extend(vector_images(images[i:i+16]))
            vectors.extend(current_vectors)
            rows.extend(current)
        except Exception as e:errors.append(dict(asset_id=a['id'],error=str(e)[:300]))
        (work/'progress.json').write_text(json.dumps(dict(done=n+1,total=len(req['assets'])),ensure_ascii=False),'utf-8')
    if not rows:raise RuntimeError('没有可用素材，索引未发布')
    np.save(work/'vectors.npy',np.asarray(vectors,dtype=np.float32))
    result=dict(model=MODEL,device=device,frames=rows,errors=errors,asset_count=len(set(r['asset_id'] for r in rows)),sampling='每约2秒抽一帧，每个源最多60帧；无连续动作证明、无自动分镜保证')
    (work/'index.json').write_text(json.dumps(result,ensure_ascii=False),'utf-8')
    output=dict(asset_count=result['asset_count'],frames=len(rows),errors=errors,model=MODEL)
else:
    index_path=Path(req['index_path']);index=json.loads(index_path.read_text('utf-8'));frames=index['frames'];vectors=np.load(index_path.with_name('vectors.npy'))
    # 当前短句为主，上下文为辅；不把语义短句擅自改成具体动作。
    query=vector_text(req['text']+('，画面：'+req['need'] if req.get('need') else ''));context=vector_text(req.get('context') or req['text'])
    q=query*.8+context*.2;q=q/np.linalg.norm(q)
    scores=vectors@q;duration=req['duration'];excluded=set(req.get('exclude_assets',[]));items=[]
    # 对明确的画面要求做第二次图文对比；仍是模型粗筛，不能替代观看。
    intent=req['text']+' '+req.get('need','');gate=None
    if '垃圾' in intent and any(w in intent for w in ('清理','清运','打扫')):
        gate=('清理垃圾',[ '工人把装修垃圾和碎砖装袋清运','工人用扫把打扫地上的垃圾','工人正在抹灰刮腻子','工人安装家具和橱柜','工人砸墙拆除','人物站着面对镜头讲话'],{0,1})
    elif '厨房' in intent:
        gate=('厨房画面',['厨房里有橱柜灶台和水槽','卫生间里有马桶淋浴洗脸盆','工人在刷墙或铺砖','客厅和卧室'],{0})
    elif any(w in req.get('need','') for w in ('出镜','讲述','开场')):
        gate=('人物出镜',['人物面对镜头站着讲话','空的房间没有人','工人弯腰低头施工','厨房整体展示'],{0})
    gate_labels=None
    if gate:
        gate_vectors=np.stack([vector_text(t) for t in gate[1]])
        gate_labels=np.argmax(vectors@gate_vectors.T,axis=1)
    used_hashes=[x['phash'] for x in frames if x['asset_id'] in excluded]
    rules=[]
    rule_query=vector_text(req['text']) if req.get('rules') else query
    for r in req.get('rules',[]):
        v=vector_text(r['text']);similarity=float(v@rule_query)
        if similarity>=.80:rules.append((r,similarity))
    for i,row in enumerate(frames):
        if row['asset_id'] in excluded or row['duration']<duration:continue
        if gate and int(gate_labels[i]) not in gate[2]:continue
        try:
            st=Path(row['path']).stat()
            if st.st_size!=row['size'] or st.st_mtime_ns!=row['mtime']:continue
        except OSError:continue
        if any(bin(int(row['phash'],16)^int(h,16)).count('1')<=5 for h in used_hashes):continue
        base=float(scores[i])
        if base<req.get('threshold',.22):continue
        score=base;bonus=0;applied=[];blocked=False
        for rule,sim in rules:
            if rule['asset_id']!=row['asset_id'] or not rule.get('start',0)<=row['center']<=rule.get('end',row['duration']):continue
            if rule['action']=='avoid':blocked=True;applied.append(rule['id'])
            elif rule['action']=='prefer':bonus=max(bonus,.03*sim);applied.append(rule['id'])
        if blocked:continue
        score+=bonus
        start=round(max(0,min(row['center']-duration/2,row['duration']-duration)),3)
        items.append(dict(**row,start=start,end=round(start+duration,6),base_score=base,score=score,rule_ids=applied,reason='中文图文模型匹配抽帧；相似度不是正确率，需看完整选段确认',match_type='待人工判断',fallback=False))
    # 不因不足10条而继续收进明显低于本批最佳匹配的画面；阈值是待人工校准的启发式。
    effective_threshold=max(req.get('threshold',.22),max((x['base_score'] for x in items),default=.22)-.035)
    chosen=select_diverse([x for x in items if x['base_score']>=effective_threshold])
    for i,r in enumerate(chosen):r['id']=hashlib.sha256((req['run_id']+r['asset_id']+str(r['start'])).encode()).hexdigest()[:24]
    output=dict(items=chosen,model=MODEL,device=device,threshold=effective_threshold,semantic_gate=gate[0] if gate else '通用语义，无专用粗筛',indexed_assets=index['asset_count'],indexed_frames=len(frames),gap=10-len(chosen),query=req['text'],context=req.get('context'),rules_considered=[r['id'] for r,_ in rules],limits=index['sampling'])
(work/'result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),'utf-8')
