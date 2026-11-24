"""以用户逐段确认的身份检索；不做人脸推断，不把标签扩展到整个源片。"""
import hashlib,json,time,subprocess
from pathlib import Path
from media import probe,is_portrait_916,FLAGS

def blocked_sources(folder):
    p=folder/'person-usage-restrictions.json'
    return {r['reference_source']['id'] for r in json.loads(p.read_text('utf-8')).get('rules',[])} if p.exists() else set()

def confirmed_aming(folder):
    rows=[]
    for p in sorted(folder.glob('person-[0-9][0-9].json')):
        for r in json.loads(p.read_text('utf-8')).get('rows',[]):
            if not r.get('confirmed_by') or not r.get('confirmation_evidence'):continue
            targets=[x.get('description','') for x in r.get('person_targets',[]) if x.get('identity')=='阿文']
            if r.get('person_identity')=='阿文' or targets:
                rows.append(dict(r,target='；'.join(targets) or '画面主体阿文'))
    return rows

def search(req,folder,cache,resolve,ffprobe,ffmpeg):
    started=time.monotonic();items=[];errors=[];checked=[];seen=set(req['exclude_assets']);blocked=blocked_sources(folder)
    assets={a['id']:a for a in req['catalog']};cache.mkdir(parents=True,exist_ok=True)
    for r in confirmed_aming(folder):
        s=r['source'];aid=s['id'];length=req['duration']
        if aid not in assets or aid in seen or aid in blocked or s['end']-s['start']+1e-6<length:continue
        checked.append(aid)
        try:
            a=assets[aid];source=Path(resolve(a));st=source.stat();meta=probe(ffprobe,source)
            if not is_portrait_916(meta) or meta['duration']<s['end']:continue
            start=float(s['start']);end=round(start+length,6)
            key=hashlib.sha256(f'{aid}:{st.st_size}:{st.st_mtime_ns}:{start}'.encode()).hexdigest()
            image=cache/(key+'.jpg')
            if not image.exists():
                subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-ss',str(start),'-i',str(source),'-frames:v','1','-vf','scale=384:-2','-y',str(image)],check=True,capture_output=True,timeout=30,creationflags=FLAGS)
            evidence=f"人工身份标注 {r['sample_id']}：{r['target']}；仅使用已确认 {s['start']}–{s['end']} 秒，不代表拍摄城市已确认"
            items.append(dict(id=hashlib.sha256((req['run_id']+aid).encode()).hexdigest()[:24],asset_id=aid,name=a['name'],root=a['root'],rel=a['rel'],path=str(source),duration=meta['duration'],start=start,end=end,image=str(image),score=1.,base_score=1.,rule_ids=[],reason=evidence,identity_evidence=evidence,match_type='人工确认阿文',fallback=False,size=st.st_size,mtime=st.st_mtime_ns,scene_group=a['rel'].split('/')[0]))
            seen.add(aid)
            if len(items)==10:break
        except Exception as e:errors.append(dict(asset_id=aid,error=str(e)[:250]))
    return dict(items=items,model='人工确认身份片段检索',mode='discover',identity_search=True,round=req['round'],query=req['text'],gap=10-len(items),checked=len(checked),examined_assets=checked,remaining=0,exhausted=True,budget_hit=False,errors=errors,rules_considered=[],seconds=round(time.monotonic()-started,2),limits='仅检索已确认阿文的时间段；不足10条不以无关画面补齐。已展示和已采用源片仍排除。')
