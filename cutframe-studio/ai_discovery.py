"""按需扩大视觉检索；每轮最多10条，已展示源永不在该工程新批次重复。"""
import json,hashlib,re,time,subprocess,math
from pathlib import Path
from collections import defaultdict
from media import probe,FLAGS,is_portrait_916
from ai_store import select_diverse

GROUPS=[('厨房','厨房 橱柜 水槽 灶台 全屋展示'),('卫生间','卫生间 厨卫 马桶 淋浴'),('垃圾 清理 保洁 打扫','垃圾 清洁 清理 保洁 施工'),('拆除 拆砸 铲墙','拆除 拆砸 铲墙 拆砖 施工前处理'),('保护 不搬家 家具','家具保护 保护 覆膜'),('材料 产品 墙布 陶泥','材料 微陶泥 墙布 展示'),('老人','老人 人物 出镜'),('人物 团队 我们 上门 讲述 出镜','人物 出镜 上门 谈单 沟通'),('设计 安装','设计 安装 施工'),('改造 翻新 老房','旧房 老房 施工 前处理')]

def scene_group(asset):
    """目录只作为保守分组，不冒充已识别的真实项目。"""
    parts=asset['rel'].replace('\\','/').split('/')[:-1]
    if asset.get('root')=='xiaoq':
        if parts and parts[0] in ('1新的未分类','2其他'):parts=parts[1:]
        label=parts[0] if parts else '未知项目'
    else:label='/'.join(parts) or '未知场景'
    return asset.get('root','')+':'+label

def diverse_scenes(scored,limit=10):
    chosen=[];groups=set();sources=set()
    for item in sorted(scored,key=lambda x:x['score'],reverse=True):
        if item['asset_id'] in sources or item['scene_group'] in groups:continue
        if any(bin(int(item['phash'],16)^int(x['phash'],16)).count('1')<=8 for x in chosen):continue
        if any(sum(a*b for a,b in zip(item['_visual'],x['_visual']))>=.93 for x in chosen):continue
        chosen.append(item);sources.add(item['asset_id']);groups.add(item['scene_group'])
        if len(chosen)>=limit:break
    return chosen

def query_key(data):
    return hashlib.sha256(json.dumps(dict(policy='portrait916-scenes-v1',**{k:data.get(k) for k in ('text','need','context','duration','scope')}),ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def history_exclusions(rows,project,task,key):
    seen=set();examined=set();hashes=set();rounds=0
    for row in rows:
        p=json.loads(row['payload']);r=json.loads(row['result'])
        if p.get('project_id')!=project:continue
        for c in r.get('items',[]):
            seen.add(c['asset_id'])
            if c.get('phash'):hashes.add(c['phash'])
        if p.get('task_id')==task:
            rounds+=1
            if p.get('query_key')==key:examined.update(r.get('examined_assets',[]))
    return dict(seen=seen,examined=examined,hashes=hashes,round=rounds+1)

def rank_catalog(assets,text,need='',context=''):
    """目录词仅决定先看哪些原片，最终候选必须另过视觉检查。"""
    weighted={}
    for query,weight in [(text,4),(need,6),(context,1)]:
        for triggers,terms in GROUPS:
            if any(t in query for t in triggers.split()):
                for term in terms.split():weighted[term]=max(weighted.get(term,0),weight)
        for word in re.findall('[\\u4e00-\\u9fff]{2,}',query):
            for i in range(len(word)-1):weighted.setdefault(word[i:i+2],weight*.15)
    ranked=[]
    for a in assets:
        path=a['rel']+' '+a['name'];score=sum(v for k,v in weighted.items() if k in path)
        ranked.append((score,a))
    # 同分时分散目录，避免连续查看同一个拍摄目录。
    groups=defaultdict(list)
    for score,a in sorted(ranked,key=lambda x:(-x[0],x[1]['rel'])):groups[(score,str(Path(a['rel']).parent))].append(a)
    buckets=defaultdict(list)
    for (score,folder),items in groups.items():buckets[score].append(items)
    output=[]
    for score in sorted(buckets,reverse=True):
        entries=buckets[score]
        for i in range(max((len(x) for x in entries),default=0)):
            for items in entries:
                if i<len(items):output.append(items[i])
    # 每轮先查看不同项目/目录的最佳文件，避免先填满同一场景。
    projects={}
    for a in output:projects.setdefault(scene_group(a),[]).append(a)
    return [items[i] for i in range(max((len(x) for x in projects.values()),default=0)) for items in projects.values() if i<len(items)]

def semantic_gate(text,need):
    intent=text+' '+need
    if '垃圾' in intent and any(w in intent for w in ('清理','清运','打扫')):return ('清理垃圾',['工人把装修垃圾和碎砖装袋清运','工人用扫把打扫地上的垃圾','工人正在抹灰刮腻子','工人安装家具和橱柜','工人砸墙拆除','人物站着面对镜头讲话'],{0,1})
    if '厨房' in intent:return ('厨房画面',['厨房里有橱柜灶台和水槽','卫生间里有马桶淋浴洗脸盆','工人在刷墙或铺砖','客厅和卧室'],{0})
    if any(w in need for w in ('出镜','讲述','开场')):return ('人物出镜',['人物面对镜头站着讲话','空的房间没有人','工人弯腰低头施工','厨房整体展示'],{0})
    return None

def discover(req,work,vector_images,vector_text,phash,model_name,device):
    import numpy as np
    started=time.monotonic();cache=Path(req['cache_path']);cache.mkdir(parents=True,exist_ok=True)
    excluded=set(req.get('exclude_assets',[]));already=set(req.get('examined_before',[]));seen_hashes=req.get('exclude_hashes',[])
    queue=rank_catalog([a for a in req['catalog'] if a['id'] not in excluded and a['id'] not in already],req['text'],req.get('need',''),req.get('context',''))
    query=vector_text(req['text']+('，画面：'+req['need'] if req.get('need') else ''));q=.8*query+.2*vector_text(req.get('context') or req['text']);q/=np.linalg.norm(q)
    gate=semantic_gate(req['text'],req.get('need',''));gate_vectors=np.stack([vector_text(t) for t in gate[1]]) if gate else None
    rule_q=vector_text(req['text']);rules=[]
    for r in req.get('rules',[]):
        similarity=float(vector_text(r['text'])@rule_q)
        if similarity>=.80:rules.append((r,similarity))
    pool=[];chosen=[];examined=[];errors=[];cache_hits=0;budget_hit=False;duration=req['duration'];effective=.22
    roots={key:Path(value).resolve() for key,value in req['roots'].items()}
    def progress(message):
        (work/'progress.json').write_text(json.dumps(dict(done=len(examined),total=len(queue),progress=min(95,len(chosen)*9),message=message),ensure_ascii=False),'utf-8')
    progress(f'范围 {len(req["catalog"])} 个原片；已排除历史及已用源，开始寻找10条新候选')
    for a in queue:
        if time.monotonic()-started>req.get('budget_seconds',120):budget_hit=True;break
        examined.append(a['id']);progress(f'本轮已检查 {len(examined)} 个原片，找到 {len(chosen)}/10 条；正在查看 {a["name"]}')
        try:
            source=(roots[a['root']]/a['rel']).resolve();source.relative_to(roots[a['root']]);st=source.stat()
            meta=probe(req['ffprobe'],source)
            if not is_portrait_916(meta):continue
            folder=cache/a['id'];folder.mkdir(exist_ok=True);manifest=folder/'index.json';entry=None
            if manifest.exists():
                candidate=json.loads(manifest.read_text('utf-8'))
                if candidate.get('model')==model_name and candidate.get('size')==st.st_size and candidate.get('mtime')==st.st_mtime_ns and all(Path(f['image']).exists() for f in candidate['frames']) and (folder/'vectors.npy').exists():entry=candidate;cache_hits+=1
            if entry is None:
                meta=probe(req['ffprobe'],source);length=meta['duration']
                if not math.isfinite(length) or length<duration:continue
                # 首次查看源片时均匀抽最多8帧；不声称已经逐帧或识别真实镜头边界。
                count=max(2,min(8,int(length/2)+1));times=np.linspace(0,max(0,length-.3),count);frames=[]
                for i,t in enumerate(times):
                    path=folder/f'{st.st_mtime_ns}-{i}.jpg'
                    subprocess.run([req['ffmpeg'],'-hide_banner','-loglevel','error','-ss',str(t),'-i',str(source),'-frames:v','1','-vf','scale=384:-2','-q:v','4','-y',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=25,creationflags=FLAGS)
                    if path.exists():frames.append(dict(center=round(float(t),4),image=str(path),phash=phash(path)))
                if not frames:continue
                vectors=vector_images([f['image'] for f in frames]);np.save(folder/'vectors.npy',vectors)
                entry=dict(model=model_name,size=st.st_size,mtime=st.st_mtime_ns,duration=length,frames=frames)
                tmp=folder/'index.tmp';tmp.write_text(json.dumps(entry,ensure_ascii=False),'utf-8');tmp.replace(manifest)
            else:vectors=np.load(folder/'vectors.npy')
            if entry['duration']<duration:continue
            scores=vectors@q;labels=np.argmax(vectors@gate_vectors.T,axis=1) if gate else None
            for i,f in enumerate(entry['frames']):
                if gate and int(labels[i]) not in gate[2]:continue
                base=float(scores[i])
                if base<.22:continue
                if any(bin(int(f['phash'],16)^int(h,16)).count('1')<=5 for h in seen_hashes):continue
                bonus=0;applied=[];blocked=False
                for rule,sim in rules:
                    if rule['asset_id']==a['id'] and rule.get('start',0)<=f['center']<=rule.get('end',entry['duration']):
                        if rule['action']=='avoid':blocked=True
                        else:bonus=max(bonus,.03*sim)
                        applied.append(rule['id'])
                if blocked:continue
                start=round(max(0,min(f['center']-duration/2,entry['duration']-duration)),3)
                pool.append(dict(**f,asset_id=a['id'],name=a['name'],root=a['root'],rel=a['rel'],path=str(source),duration=entry['duration'],start=start,end=round(start+duration,6),score=base+bonus,base_score=base,rule_ids=applied,size=entry['size'],mtime=entry['mtime'],reason='本轮按需查看原片后做中文图文匹配；需人工看完整片段，分数不是正确率',match_type='待人工判断',fallback=False))
            effective=max(.22,max((x['base_score'] for x in pool),default=.22)-.035)
            for x in pool:
                if x['asset_id']==a['id']:
                    x['scene_group']=scene_group(a)
                    x['_visual']=vectors[next(j for j,f in enumerate(entry['frames']) if f['image']==x['image'])].tolist()
            chosen=diverse_scenes([x for x in pool if x['base_score']>=effective])
            if len(chosen)>=10:break
        except Exception as e:errors.append(dict(asset_id=a['id'],error=str(e)[:250]))
    for c in chosen:
        c.pop('_visual',None)
        c['id']=hashlib.sha256((req['run_id']+c['asset_id']+str(c['start'])).encode()).hexdigest()[:24]
    remaining=len(queue)-len(examined)
    progress(f'本轮完成：{len(chosen)}/10条新候选，查看{len(examined)}个原片；还有{remaining}个未查看')
    return dict(items=chosen,model=model_name,device=device,threshold=effective,semantic_gate=gate[0] if gate else '通用语义',query=req['text'],context=req.get('context',''),gap=10-len(chosen),mode='discover',round=req['round'],catalog_total=len(req['catalog']),remaining=remaining,examined_assets=examined,checked=len(examined),cache_hits=cache_hits,budget_hit=budget_hit,exhausted=remaining==0,errors=errors,seconds=round(time.monotonic()-started,2),rules_considered=[r['id'] for r,_ in rules],limits='从原始目录按需读取；每源最多8个均匀抽帧，未完成全库逐帧分析；未找到足够候选可继续下一轮。')
