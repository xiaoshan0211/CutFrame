"""正式候选：分段抽帧粗查，再按字幕固定时长复查；源文件只读。"""
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image
from ai_discovery import rank_catalog, scene_group
from media import probe, is_portrait_916, FLAGS
from gpt_provider import call_gpt, read_key, BudgetStop, GPTRequestError, validate_segments
from ai_knowledge import select_experience
from retrieval_intent import rank_by_intent, rejection


def frames(binary, source, start, end, folder):
    folder.mkdir(parents=True,exist_ok=True); result=[]
    for i in range(8):
        t=start+(end-start)*(i+.5)/8; dest=folder/f'{i}.jpg'
        subprocess.run([binary,'-v','error','-nostdin','-ss',str(t),'-i',str(source),'-frames:v','1','-vf','scale=640:640:force_original_aspect_ratio=decrease','-y',str(dest)],capture_output=True,check=True,timeout=40,creationflags=FLAGS)
        result.append(dict(path=str(dest),time=t))
    return result


def fingerprint(path):
    with Image.open(path) as im:
        v=list(im.convert('L').resize((9,8)).getdata())
    value=0
    for y in range(8):
        for x in range(8):
            value=(value<<1)|int(v[y*9+x+1]>v[y*9+x])
    return f'{value:016x}'


def discover(req, work, caller=call_gpt, key_loader=read_key):
    started=time.monotonic(); rule=req['gpt_rules']; lim=rule['limits']; duration=req['duration']
    excluded=set(req.get('exclude_assets',[])); done=set(req.get('examined_before',[])); cursors=dict(req.get('scan_cursors',{}))
    queue,intent=rank_by_intent([a for a in req['catalog'] if a['id'] not in excluded|done],req['text'],req.get('need',''),req.get('context',''))
    rejections=[]
    def reject(a,code,message):
        rejections.append(dict(asset_id=a.get('id'),name=a.get('name',''),code=code,message=message))
    items=[]; errors=[]; examined=[]; checked=0; calls=0; api_seconds=0; cost=0; stop=''; groups=set(); hashes=list(req.get('exclude_hashes',[])); key=None
    knowledge=req.get('knowledge',dict(facts=[],general=[]))
    evidence=knowledge.get('facts',[]);used_experience=set()
    # 显式身份需求必须先有精确源片段依据，测试样例不作为新候选回填。
    required=[x for x in rule['identity_terms'] if x in req['text']+' '+req.get('need','')]
    confirmed_mode=req.get('source_mode')=='confirmed'
    if required or confirmed_mode:
        eligible={r['asset_id'] for r in evidence if r.get('confirmed_by') and r.get('evidence') and r.get('usable',True) and all(x in r.get('identities',[]) for x in required)}
        queue=[a for a in queue if a['id'] in eligible]
        if not queue: stop='没有具备人工确认身份依据的新素材，待核实；未调用API，未用旧测试样例凑数'
    def progress(message):
        p=work/'progress.tmp';p.write_text(json.dumps(dict(done=checked,total=max(1,len(queue)),progress=min(95,len(items)*9),message=message),ensure_ascii=False),'utf-8');p.replace(work/'progress.json')
    def judge(fs,s,e,phase,a,identity):
        nonlocal calls,key,api_seconds,cost
        if calls>=lim['max_calls_per_round']:raise BudgetStop('本轮请求数量上限已到，下轮继续未检查段落')
        if key is None:key=key_loader(req['home'])
        experience=select_experience(knowledge,a['id'],s,e,req['text']+' '+req.get('need',''))
        try:
            pred,stats=caller(rule,Path(req['ledger']),key,fs,dict(text=req['text'],need=req.get('need',''),context=req.get('context',''),duration=duration,phase=phase,identity_evidence=identity,approved_experience=experience,visual_intent=intent),s,e,dict(run_id=req['run_id'],asset_id=a['id'],phase=phase,start=s,end=e,rule_hash=rule['hash']))
        except GPTRequestError as exc:
            calls+=1;api_seconds+=exc.diagnostic['seconds'];cost+=exc.diagnostic.get('cost_estimate_usd',0)
            errors.append(exc.diagnostic)
            with (work/'gpt-decisions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(exc.diagnostic,ensure_ascii=False)+'\n')
            raise
        calls+=1;api_seconds+=stats['seconds'];cost+=stats['cost_estimate_usd']
        used_experience.update(x['id'] for x in experience)
        with (work/'gpt-decisions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(asset_id=a['id'],start=s,end=e,phase=phase,prediction=pred,stats=stats,experience_used=experience,knowledge_hash=knowledge.get('hash')),ensure_ascii=False)+'\n')
        valid=validate_segments(pred,s,e,duration)
        why=rejection(pred,valid)
        if why:reject(a,*why)
        return valid
    for a in queue:
        if checked>=lim['max_sources_per_round'] or len(items)>=10:break
        group=scene_group(a)
        if group in groups:continue
        checked+=1;progress(f'GPT检查原片 {checked}，已找到 {len(items)}/10 条；仅上传抽帧和文案')
        root=Path(req['roots'][a['root']]).resolve();source=(root/a['rel']).resolve()
        if not source.is_relative_to(root):raise ValueError('素材路径越出授权目录')
        try:
            meta=probe(req['ffprobe'],source);length=meta['duration']
            if not is_portrait_916(meta) or length<duration:
                reject(a,'format_or_duration','非9:16竖屏或原片时长不足')
                examined.append(a['id']);continue
            st=source.stat(); signature=f'{st.st_size}:{st.st_mtime_ns}'
            cursor=cursors.get(a['id'],{});start=float(cursor.get('next',0)) if cursor.get('signature')==signature else 0
            windows=[]
            if required or confirmed_mode:
                for r in evidence:
                    if r.get('asset_id')==a['id'] and r.get('confirmed_by') and r.get('evidence') and r.get('usable',True) and all(x in r.get('identities',[]) for x in required):
                        windows.append((max(start,float(r['start'])),min(length,float(r['end'])),dict(sample_id=r.get('sample_id'),identities=r.get('identities'),person_targets=r.get('person_targets'),product_identity=r.get('product_identity'),confirmed_action=r.get('confirmed_action'),context=r.get('context'),evidence=r['evidence'])))
            else:windows=[(start,length,'身份未知，不得猜测')]
            found=False;windows_checked=0;partial=False
            for lo,hi,identity in windows:
                s=lo
                while s+duration<=hi+.000001:
                    if windows_checked>=1:
                        partial=True;break
                    e=min(hi,s+max(duration,lim['window_seconds']));folder=work/'gpt-frames'/a['id']/f'{s:.3f}'
                    cursors[a['id']]=dict(next=s,signature=signature)
                    fs=frames(req['ffmpeg'],source,s,e,folder/'scan')
                    options=judge(fs,s,e,'寻找匹配时间段',a,identity)
                    windows_checked+=1
                    for option in options:
                        cs=option['start'];ce=round(cs+duration,6)
                        if ce>e+.001:continue
                        if any(r.get('asset_id')==a['id'] and r.get('usable') is False and r['start']<ce and r['end']>cs for r in evidence):continue
                        selected=frames(req['ffmpeg'],source,cs,ce,folder/'verify')
                        # 固定片段复核返回必须覆盖整个片段，不能把短动作扩成整条字幕。
                        valid=judge(selected,cs,ce,'复查整个固定时长是否直接匹配',a,identity)
                        if not valid:continue
                        ph=fingerprint(selected[4]['path'])
                        if any((int(ph,16)^int(h,16)).bit_count()<=8 for h in hashes):
                            reject(a,'duplicate','与已展示画面近似重复');continue
                        verdict=valid[0];reason=f"GPT观察：{verdict['evidence']}；动作：{'、'.join(verdict['actions'])}；部位：{verdict.get('surface','不明')}。待人工确认"
                        items.append(dict(id=hashlib.sha256((req['run_id']+a['id']).encode()).hexdigest()[:24],asset_id=a['id'],name=a['name'],root=a['root'],rel=a['rel'],path=str(source),duration=length,start=cs,end=ce,image=selected[4]['path'],phash=ph,score=0.,base_score=0.,rule_ids=[],reason=reason,identity_evidence=reason,match_type='GPT待人工确认',fallback=False,size=st.st_size,mtime=st.st_mtime_ns,scene_group=group,actions=verdict['actions'],surface=verdict.get('surface','不明'),rule_hash=rule['hash']))
                        preference=verdict.get('preference_score',0)
                        if not any(r.get('kind')=='personal' for r in select_experience(knowledge,a['id'],cs,ce,req['text']+' '+req.get('need',''))):preference=0
                        items[-1]['preference_score']=float(preference) if isinstance(preference,(int,float)) and math.isfinite(preference) and 0<=preference<=1 else 0
                        groups.add(group);hashes.append(ph);found=True;break
                    if found:break
                    # 与前窗重叠一个字幕长度，防止动作恰跨窗丢失。
                    s=e if e>=hi else max(s+.1,e-duration)
                    cursors[a['id']]=dict(next=s,signature=signature)
                if found or partial:break
            if not partial:
                examined.append(a['id']);cursors.pop(a['id'],None)
        except BudgetStop as exc:
            stop=str(exc);break
        except (ValueError,KeyError) as exc:
            # API格式/连接异常停止，不在循环中重试消耗额度。
            stop=str(exc);break
        except (OSError,subprocess.SubprocessError) as exc:
            errors.append(dict(asset_id=a['id'],error=type(exc).__name__))
            reject(a,'media_error','素材读取或抽帧失败：'+type(exc).__name__)
    progress(stop or f'完成：{len(items)}/10条，待人工预览确认')
    items.sort(key=lambda x:x.get('preference_score',0),reverse=True)
    for item in items:
        item['source_mode']=req.get('source_mode','new')
        item['experience_ids']=[r['id'] for r in select_experience(knowledge,item['asset_id'],item['start'],item['end'],req['text']+' '+req.get('need',''))]
    return dict(visual_intent=intent,rejections=rejections,empty_reason=(stop or ('本轮未找到合格片段；请查看逐素材原因，未检查的后续时间段保留到下轮' if rejections else '没有可检查的新素材，或可检查时间段不足')) if not items else '',items=items,model=rule['model'],mode='discover',provider='gpt',source_mode=req.get('source_mode','new'),knowledge_snapshot=knowledge,experience_used=sorted(used_experience),round=req['round'],query=req['text'],gap=10-len(items),checked=checked,examined_assets=examined,scan_cursors=cursors,remaining=max(0,len(queue)-len(examined)),exhausted=len(examined)==len(queue),budget_hit=bool(stop) and not stop.startswith('没有具备'),stop_reason=stop,errors=errors,rules_considered=sorted(used_experience),seconds=round(time.monotonic()-started,2),api_seconds=round(api_seconds,2),cost_estimate_usd=round(cost,6),calls=calls,rule_version=rule['version'],rule_hash=rule['hash'],rules_snapshot=rule,limits='顺序抽帧存在帧间盲区，候选不是人工验收结果；未凑数或自动采用。')


if __name__=='__main__':
    request_path=Path(sys.argv[1]);req=json.loads(request_path.read_text('utf-8'))
    result=discover(req,request_path.parent)
    (request_path.parent/'result.json').write_text(json.dumps(result,ensure_ascii=False),'utf-8')
