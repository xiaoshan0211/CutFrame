"""标签库本机查询：独立于 Flask、云端预算及工作进程。"""
import collections,contextlib,hashlib,json,math,re,sqlite3,time,unicodedata
from pathlib import Path
from annotation_store import dump
from copy_viewpoints import matches_fact
from slot_review import effective, decide, NEGATIVE, POSITIVE
import structured_selection
import clean_selection
import cloud_segments
from itertools import chain
from classified_windows import classified_windows
from selection_ranker import LEGACY, load_for_need, rerank

# 字符二元组 Dice 重合度；暂未用人工样本校准。
SIMILARITY_THRESHOLD=0.65
HUMAN={'人工确认','人工改正'}
def normalize(text):return ''.join(c for c in str(text) if not c.isspace() and not unicodedata.category(c).startswith('P'))
def similarity(a,b):
    a,b=normalize(a),normalize(b)
    if not a or not b:return 0.
    if a==b:return 1.
    aa={a[i:i+2] for i in range(len(a)-1)};bb={b[i:i+2] for i in range(len(b)-1)}
    return 2*len(aa&bb)/(len(aa)+len(bb)) if aa and bb else 0.
@contextlib.contextmanager
def readonly(path):
    c=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    try:yield c
    finally:c.close()
def overlap(a,b,c,d):return max(a,c)<min(b,d)
def active_conditions(data):
    result={}
    for group in ('must','prefer','forbid'):
        rows=data.get(group,[])
        if not isinstance(rows,list):raise ValueError('条件组必须是数组')
        result[group]=[]
        for row in rows:
            if not isinstance(row,dict):raise ValueError('条件行必须是对象')
            if row.get('explanation_only') or row.get('structure_status')=='只作说明，不参与判断':continue
            if not isinstance(row.get('dimension'),str) or not isinstance(row.get('tags'),list) or not row['tags'] or any(not isinstance(t,str) for t in row['tags']):raise ValueError('每行必须提供维度和非空标签数组')
            result[group].append(dict(dimension=row['dimension'],tags=list(dict.fromkeys(row['tags'])),raw=row.get('raw','')))
    return result

class Selection:
    def __init__(self,annotation,catalog,learning,roots,metadata,blocked=(),library=None,rank_directory=None,clean_book=None,cloud_book=None,other_learning=None):
        self.annotation=Path(annotation);self.catalog=Path(catalog);self.learning=Path(learning);self.roots=roots;self.metadata=metadata;self.blocked=set(blocked)
        self.clean_book=clean_book
        self.cloud_book=cloud_book
        self.other_learning=other_learning
        self.library=library
        self.rank_directory=rank_directory
    def suggest(self,text):
        with readonly(self.annotation) as c:
            p=c.execute('SELECT * FROM rule_packages ORDER BY created DESC,rowid DESC LIMIT 1').fetchone()
        if not p:return None
        content=json.loads(p['content']);scored=[(similarity(text,r['text']),r) for r in content.get('rules',[])]
        scored.sort(key=lambda x:(-x[0],x[1]['id']))
        if not scored or scored[0][0]<SIMILARITY_THRESHOLD:return None
        score,r=scored[0]
        return dict(package_id=p['id'],package_status=p['status'],rule_id=r['id'],text=r['text'],similarity=score,conditions={g:r.get(g,[]) for g in ('must','prefer','forbid')},notice='草稿，机器拆解，未经人核对' if p['status']=='草稿' else '已发布规则；各行状态见原文')
    def previous(self,project,task,text=None):
        with readonly(self.learning) as c:
            for r in c.execute('SELECT payload FROM runs ORDER BY rowid DESC'):
                p=json.loads(r[0])
                if p.get('provider')=='local' and p.get('project_id')==project and p.get('task_id')==task and (text is None or p.get('text')==text):return dict(conditions=p.get('conditions',{}),keywords=p.get('keywords',[]),type_selection=p.get('type_selection'))
        return None
    def query(self,data):
        started=time.monotonic();text=str(data.get('text','')).strip();duration=data.get('duration')
        if isinstance(duration,bool):raise ValueError('字幕时长无效')
        try:duration=float(duration)
        except (TypeError,ValueError):raise ValueError('字幕时长无效')
        if not text or len(text)>500 or not math.isfinite(duration) or not .03<=duration<=60:raise ValueError('请提供有效字幕及片段时长')
        conditions=active_conditions(data.get('conditions',{}));keywords=data.get('keywords',[])
        if not isinstance(keywords,list) or len(keywords)>30 or any(not isinstance(k,str) or len(k)>100 for k in keywords):raise ValueError('关键词必须为字符串数组，最多30个')
        keywords=list(dict.fromkeys(k.strip() for k in keywords if k.strip()));project=str(data.get('project_id',''));task=str(data.get('task_id',''))
        if not project or project=='unsaved' or not task:raise ValueError('请保存工程并选择字幕任务')
        scope=data.get('scope','all');allowed={k for k,v in self.roots.items() if v.get('role')=='raw'}
        if scope!='all':
            if scope not in allowed:raise ValueError('只能在已授权原始素材库检索')
            allowed={scope}
        else:
            allowed={k for k in allowed if self.roots[k].get('origin')!='cloud'}
        with readonly(self.catalog) as c:
            assets={r['id']:dict(r) for r in c.execute('SELECT * FROM assets') if r['root'] in allowed}
            saved=c.execute('SELECT data FROM projects WHERE id=?',(project,)).fetchone()
        if not saved:raise ValueError('工程不存在，请先保存')
        project_used={s['asset_id'] for s in json.loads(saved[0]).get('shots',[]) if s.get('asset_id')}
        with readonly(self.annotation) as c:
            segments=[dict(r) for r in c.execute("SELECT s.id,s.asset_id,r.start,r.end,o.raw original_raw,o.logical_path FROM segments s JOIN ranges r ON r.id=s.current_range JOIN originals o ON o.asset_id=s.asset_id WHERE s.status='有效'")]
            anns=collections.defaultdict(list);conflicted=collections.defaultdict(list)
            for r in c.execute("SELECT a.*,s.asset_id,r.start,r.end FROM annotations a JOIN segments s ON s.id=a.segment_id JOIN ranges r ON r.id=a.range_id WHERE s.status='有效' AND a.range_id=s.current_range AND NOT EXISTS(SELECT 1 FROM annotations newer WHERE newer.supersedes=a.id)"):
                a=dict(r);a['labels']=json.loads(a['labels']);a['flags']=json.loads(a['flags'])
                if '冲突待确认' not in a['flags']:anns[a['asset_id']].append(a)
                elif a['dimension']=='画面类型':conflicted[a['asset_id']].append(a)
            originals={r['asset_id']:dict(r) for r in c.execute('SELECT * FROM originals')}
            restrictions=[dict(r) for r in c.execute('SELECT * FROM restrictions WHERE active=1')]
            descriptions=collections.defaultdict(list);keyword_segments=set()
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='machine_descriptions'").fetchone():
                for r in c.execute('SELECT * FROM machine_descriptions d WHERE NOT EXISTS(SELECT 1 FROM machine_descriptions n WHERE n.supersedes=d.id)'):
                    descriptions[r['segment_id']].append(r['text'])
                if keywords:
                    clauses=' OR '.join("text LIKE ? ESCAPE '\\'" for _ in keywords)
                    escaped=['%'+k.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%' for k in keywords]
                    keyword_segments={r[0] for r in c.execute('SELECT segment_id FROM machine_descriptions d WHERE NOT EXISTS(SELECT 1 FROM machine_descriptions n WHERE n.supersedes=d.id) AND ('+clauses+')',escaped)}
        with readonly(self.learning) as c:
            runs={r['id']:(json.loads(r['payload']),json.loads(r['result'])) for r in c.execute('SELECT * FROM runs ORDER BY rowid')}
            latest={}
            for r in c.execute('SELECT * FROM adoptions ORDER BY rowid'):latest[(r['run_id'],r['candidate_id'])]=dict(r)
            training=effective(c)
            preferences=[]
            if data.get('use_experience'):
                for rule in c.execute("SELECT id,payload FROM rules WHERE status='approved'"):
                    pref=json.loads(rule['payload'])
                    if pref.get('action') not in ('prefer','avoid') or not pref.get('asset_id'):continue
                    if pref.get('scope')=='project' and pref.get('project_id')!=project:continue
                    if similarity(text,pref.get('text',''))>=SIMILARITY_THRESHOLD:
                        preferences.append((rule['id'],pref))
        seen=set();rounds=1
        for p,r in runs.values():
            if p.get('project_id') != project:continue
            seen.update(item['asset_id'] for item in r.get('items',[]) if item.get('asset_id'))
            if p.get('provider')=='local' and p.get('project_id')==project and p.get('task_id')==task:
                if data.get('trigger') and p.get('text')!=text:continue
                rounds+=1
        adopted_count=collections.Counter();history=[]
        for adoption in latest.values():
            if adoption['action']=='removed':continue
            run=runs.get(adoption['run_id'])
            if not run:continue
            oldp,oldr=run;cand=next((x for x in oldr.get('items',[]) if x['id']==adoption['candidate_id']),None)
            shot=json.loads(adoption['payload']);aid=shot.get('asset_id') or (cand or {}).get('asset_id')
            if adoption['project_id']!=project:adopted_count[aid]+=1
            if similarity(text,oldp.get('text',''))<SIMILARITY_THRESHOLD:continue
            merged=dict(cand or {},**shot)
            if aid and all(k in merged for k in ('start','end')):history.append(dict(id='',asset_id=aid,start=merged['start'],end=merged['end'],history_text=oldp.get('text',''),history_run_id=adoption['run_id'],history_candidate_id=adoption['candidate_id']))
        blocked=[];filters=collections.Counter();pool=[];metadata_cache={};requested=set(data.get('exclude_assets',[]))
        requested_types={t for row in conditions['must'] if row['dimension']=='画面类型' for t in row['tags']}
        view=data.get('viewpoint') or {}
        manual=data.get('manual_browse') is True and data.get('type_source')=='manual'
        structured=bool(view.get('structured') and self.library and not manual)
        diagnostics={t:collections.Counter() for t in sorted(requested_types)}
        skipped_seen=set()
        if self.cloud_book and self.cloud_book.is_file():
            aliases=cloud_segments.index(self.cloud_book)[2]
            if aliases and self.other_learning and self.other_learning.is_file():
                with readonly(self.other_learning) as other:
                    for run in other.execute("SELECT result FROM runs WHERE json_extract(payload, '$.project_id')=?", (project,)):
                        for item in json.loads(run[0]).get('items',[]):
                            seen.update(aliases.get(item.get('asset_id'),()))
            for excluded in (project_used,requested,self.blocked):
                excluded.update(alias for aid in tuple(excluded) for alias in aliases.get(aid,()))
        def count(types,reason):
            for t in types:diagnostics[t][reason]+=1
        def row_status(row,positive):
            matches=[a for a in positive if a['dimension']==row['dimension'] and set(a['labels'])&set(row['tags'])]
            human=[a for a in matches if a['review_status'] in HUMAN]
            machine=[a for a in matches if a['source']=='机器' and a['review_status']=='未审']
            classified=any(a.get('classified') for a in matches)
            return dict(**row,status='人确认' if human else '机器标注·未审' if machine else '分类表·待核对' if classified else '没有标注',annotation_ids=[a['id'] for a in human or machine if not a.get('classified')])
        label_types={t for rows in conditions.values() for row in rows if row['dimension']=='画面类型' for t in row['tags']}
        label_types.update(t for r in training for t in r.get('conflict_tags',[]) if re.fullmatch(r'V\d\d',t))
        categories={t for row in conditions['must'] if row['dimension']=='素材类别' for t in row['tags']}
        wanted={(r['dimension'],t) for r in conditions['must'] for t in r['tags']}
        catalog_windows=[];catalog_labels=collections.defaultdict(list)
        cloud_scope=self.roots.get(scope,{}).get('origin')=='cloud'
        if cloud_scope:
            windows=cloud_segments.windows(self.cloud_book,assets,label_types,keywords,categories,wanted) if self.cloud_book else ()
        elif self.clean_book:
            stamp=clean_selection.version(self.clean_book)
            windows=clean_selection.windows(self.clean_book,stamp,assets,self.roots,label_types,categories,wanted,keywords)
        else:
            extra=structured_selection.workbook_windows(self.library.parent,assets,label_types) if structured else ()
            windows=chain(classified_windows(self.library,assets,self.roots,label_types),extra)
        for window in windows:
            if keywords and self.clean_book and not window.get('keyword_hit'):continue
            code=window['picture']
            entries=list(window.get('extra_tags',()))
            if code:entries.append(('画面类型',code,window['basis']))
            for dim,tag,sheet in entries:
                catalog_labels[window['asset_id']].append(dict(id=window['id'],dimension=dim,labels=[tag],negative=False,
                    start=window['start'],end=window['end'],source='分类表',review_status='人工确认' if sheet=='已核标签' or sheet.startswith('示例审核人已审') else '待核对',classified=True))
            if window.get('keyword_hit'):keyword_segments.add(window['id'])
            if any((dim,tag) in wanted for dim,tag,_ in entries) or window.get('keyword_hit') or any(dim=='画面类型' and tag in requested_types for dim,tag,_ in entries):
                catalog_windows.append(window)
        source_windows=catalog_windows if self.clean_book else (segments if conditions['must'] or keywords else [])+history+catalog_windows

        for s in source_windows:
            aid=s['asset_id'];a=assets.get(aid)
            if not a:filters['范围外或素材不存在']+=1;continue
            reason=''
            if aid in self.blocked:reason='禁用来源'
            elif not a.get('available',1):reason='素材不可用'
            elif aid in requested:reason='请求排除'
            elif aid in project_used:reason='本工程已用'
            if reason:filters[reason]+=1;continue
            start=float(s['start']);limit=float(s['end'])
            annotations=anns[aid]
            if self.clean_book:
                annotations=[ann for ann in annotations if ann['dimension']!='画面类型' or ann['negative'] or ann['review_status'] in HUMAN]
            if 'picture' in s:
                stop=min(limit,start+duration)
                corrections=[a for a in annotations if a['dimension']=='画面类型' and a['review_status']=='人工改正'
                             and overlap(start,stop,a['start'],a['end'])]
                own=[label for label in catalog_labels[aid] if label['id']==s['id']]
                if corrections:
                    own=[label for label in own if label['dimension']!='画面类型' or
                         all(set(label['labels']).intersection(a['labels']) for a in corrections)]
                if any(overlap(start,stop,a['start'],a['end']) for a in conflicted[aid]) or (
                        corrections and not any(label['dimension']=='画面类型' for label in own)):
                    filters['分类与现有标注冲突']+=1
                    continue
                annotations=annotations+own
            window_types={t for ann in annotations if ann['dimension']=='画面类型' and not ann['negative']
                          and (ann['review_status'] in HUMAN or ann['source']=='机器' and ann['review_status']=='未审' or ann.get('classified'))
                          and ann['start']<=start+1e-9 and ann['end']>=min(limit,start+duration)-1e-9 for t in ann['labels']} & requested_types
            if requested_types and not window_types:
                filters['必须条件未全部满足']+=1
                continue
            if limit-start+1e-9<duration:
                filters['片段长度不足']+=1
                count(window_types,'时长不足')
                continue
            end=start+duration
            original=originals.get(aid,{});raw=json.loads(original.get('raw','{}'))
            if raw.get('可用状态','可用')!='可用':filters['可用状态不是可用']+=1;continue
            warnings=[]
            for restriction in restrictions:
                if restriction['level']=='目录':
                    directory=(restriction['directory'] or '').replace('\\','/').rstrip('/')
                    logical=(original.get('logical_path') or a['rel']).replace('\\','/')
                    if directory and (logical==directory or logical.startswith(directory+'/') or a['rel'].replace('\\','/').startswith(directory+'/')):warnings.append(restriction['text'])
                elif restriction['asset_id']==aid and (restriction['level']=='原片' or overlap(start,end,restriction['start'],restriction['end'])):reason='原片限制' if restriction['level']=='原片' else '秒段限制';break
            if reason:filters[reason]+=1;continue
            near=[x for x in annotations if overlap(start,end,x['start'],x['end'])]
            # 同一窗口还可能有另一种已分类动作；套用禁止条件和旧错时也要看见这些标签。
            other_labels=[x for x in catalog_labels[aid] if x['id']!=s['id'] and overlap(start,end,x['start'],x['end'])]
            for label in other_labels:
                if not any(a['dimension']=='画面类型' and a['review_status'] in HUMAN and
                           ((a['negative'] and set(a['labels'])&set(label['labels'])) or
                            (a['review_status']=='人工改正' and not set(a['labels'])&set(label['labels']))) for a in near):
                    near.append(label)
            positive=[x for x in near if (not self.clean_book or x.get('classified') and x['id']==s['id']) and not x['negative'] and x['start']<=start+1e-9 and x['end']>=end-1e-9]
            negative=[x for x in near if x['negative'] and x['review_status'] in HUMAN]
            if any(x['dimension']==r['dimension'] and set(x['labels'])&set(r['tags']) for x in negative for r in conditions['must']):filters['人工反例命中必须条件']+=1;continue
            forbidden=[x for x in near if (not self.clean_book or x.get('classified') and x['id']==s['id']) and not x['negative'] and (x['review_status'] in HUMAN or x['source']=='机器' and x['review_status']=='未审' or x.get('classified')) and any(x['dimension']==r['dimension'] and set(x['labels'])&set(r['tags']) for r in conditions['forbid'])]
            if forbidden:
                if any(x['review_status'] in HUMAN for x in forbidden):filters['禁止条件命中人工']+=1
                if any(x['source']=='机器' and x['review_status']=='未审' for x in forbidden):filters['禁止条件命中机器']+=1
                if any(x.get('classified') and x['review_status'] not in HUMAN for x in forbidden):filters['禁止条件命中分类表']+=1
                continue
            rows=[dict(group=g,**row_status(r,positive)) for g in ('must','prefer','forbid') for r in conditions[g]]
            must=[r for r in rows if r['group']=='must'];satisfied=sum(r['status']!='没有标注' for r in must);preferred=sum(r['status']!='没有标注' for r in rows if r['group']=='prefer')
            if satisfied!=len(must):
                filters['必须条件未全部满足']+=1
                continue
            tags=sorted({tag for annotation in positive for tag in annotation['labels']})
            stops,checks=decide(training,text,project,aid,start,end,tags)
            if stops:
                blocked.extend(stops)
                filters['已确认训练记录']+=1
                continue
            if aid in seen:
                skipped_seen.add(aid)
                continue
            historical='history_text' in s
            if historical:layer=1;kind='历史采用'
            elif a['root']=='baba' and 'picture' not in s:filters['扒扒仅允许历史采用']+=1;continue
            elif must and all(r['status']=='人确认' for r in must):layer=1;kind='人确认'
            elif must and satisfied:layer=2;kind='分类表·待核对' if 'picture' in s else '机器标签·未审'
            elif s['id'] in keyword_segments:layer=3;kind='机器描述·未审'
            else:continue
            matches=[(rid,p) for rid,p in preferences if p['asset_id']==aid and overlap(start,end,p.get('start',0),p.get('end',0))]
            preference=sum(1 if p['action']=='prefer' else -1 for _,p in matches)
            pool.append(dict(tags=tags,warnings_to_review=checks,asset_id=aid,name=a['name'],root=a['root'],rel=a['rel'],duration=limit,start=start,end=end,segment_id=s['id'],layer=layer,local_kind=kind,condition_rows=rows,annotation_ids=sorted({i for r in rows for i in r['annotation_ids']}),machine_annotation_ids=[x['id'] for x in positive if x['source']=='机器' and x['dimension']=='画面类型'],machine_description='\n'.join(descriptions.get(s['id'],[])),warnings=warnings,history_text=s.get('history_text',''),history_run_id=s.get('history_run_id'),reason=kind+'；请预览候选窗口后人工决定',rule_ids=[rid for rid,_ in matches],fallback=False,_satisfied=satisfied,_prefer=preferred+preference,_adoptions=adopted_count[aid]))
            if 'picture' in s:
                pool[-1].update(classified_table=s['classified_table'],classification_basis=s['basis'],classification_description=s['description'])
        for item in pool:
            facts=[r.get('extra_fact') or r['fact'] for r in training if r['asset_id']==item['asset_id'] and r['start']<=item['start'] and r['end']>=item['end']]
            evidence=[item['machine_description'],item.get('classification_description',''),*facts]
            item['view_rules']=[rule['id'] for rule in data.get('view_rules',[]) if any(matches_fact(rule,s) for s in evidence)]
            if structured:
                match=structured_selection.assess(view,item,evidence)
                if match:item['semantic_score'],item['matched_view']=match

        pool.sort(key=lambda x:(-x.get('semantic_score',0),-len(x['view_rules']),x['layer'],bool(x['warnings']),-x['_satisfied'],-x['_prefer'],x['_adoptions'],x['asset_id'],x['start'],x['end'],x['segment_id'],x.get('history_run_id') or ''))
        ranking=load_for_need(self.rank_directory,(data.get('need') or '').strip())
        items=[];used=set();unchecked=set();from media import is_portrait_916
        for c in pool:
            if not ranking and c['asset_id'] in used:continue
            aid=c['asset_id']
            if aid not in metadata_cache:
                # 手机 MOV 的编码宽高可能是横的，原片旋转后的显示比例才决定能否入选。
                # 本轮三条，再预核下一批三条；其余按去重原片计入待核验。
                if not ranking and len(items)>=10:
                    unchecked.add(aid)
                    continue
                try:metadata_cache[aid]=self.metadata(assets[aid])
                except Exception:metadata_cache[aid]=None
            meta=metadata_cache[aid]
            if not meta:filters['竖屏复核取不到原片']+=1;continue
            if not is_portrait_916(meta):
                count(requested_types.intersection(c['tags']),'非竖屏')
                filters['非原生9比16']+=1
                continue
            if float(meta.get('duration',0))+0.001<c['end']:
                count(requested_types.intersection(c['tags']),'时长不足')
                filters['真实时长不足']+=1
                continue
            count(requested_types.intersection(c['tags']),'可用竖屏')
            c['duration']=meta['duration'];c['id']=hashlib.sha256(dump([aid,c['start'],c['end'],c['segment_id'],c['local_kind']]).encode()).hexdigest()[:24]
            for k in ('_satisfied','_prefer','_adoptions'):c.pop(k)
            items.append(c);used.add(aid)
        for order,item in enumerate(items,1):
            item['rank_input_order']=order
        rerank(ranking,items)
        if structured and ranking:items.sort(key=lambda c:-c.get('semantic_score',0))
        if ranking:
            unique={}
            for item in items:
                unique.setdefault(item['asset_id'],item)
            items=list(unique.values())
        remaining=max(0,len(items)-5);items=items[:5]
        for slot,item in zip("ABCDE",items):item["slot"]=slot
        counts={str(i):sum(c['layer']==i for c in items) for i in (1,2,3)}
        if skipped_seen:
            filters['历史检索已展示的原片']=len(skipped_seen)
        return dict(rank_version=ranking[1]['模型版本'] if ranking else LEGACY,type_counts=diagnostics,slot_review=True,reason_codes=NEGATIVE,positive_codes=POSITIVE,remaining=remaining,unchecked_sources=len(unchecked),blocked=list({(b['id'],b['asset_id']):b for b in blocked}.values()),provider='local',mode='local',items=items,layer_counts=counts,filters=dict(filters),message='本机查询，未调用云端，费用 0',notice='' if conditions['must'] or keywords else '请选条件或填关键词',round=rounds,cost_estimate_usd=0,duration=duration,query=text,capacity=5,gap=5-len(items),seconds=round(time.monotonic()-started,3),similarity_threshold=SIMILARITY_THRESHOLD,similarity_calibrated=False,limits='候选窗口从片段起点取；标签仅在原区间内生效；未审内容需人工核对。')
