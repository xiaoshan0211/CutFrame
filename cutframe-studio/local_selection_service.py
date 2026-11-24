"""本机候选 HTTP 接入，复用 runs、缩略图、评价和采用接口。"""
import contextlib,hashlib,json,sqlite3,subprocess,uuid
from pathlib import Path
from flask import request,jsonify
from annotation_store import Store,now,dump
from annotation_rules import Rules
from threading import Lock
from local_selection import Selection,active_conditions,readonly
from verified_people import blocked_sources
from media import FLAGS
from functools import lru_cache
from copy_viewpoints import Viewpoints, read_rules
import slot_review
import clean_selection
import structured_selection
import review_dictation
import structured_entry
import annotation_channels
from selection_sources import SelectionSource, active_source
from ai_store import connect

def thumbnail(env,candidate):
    cache=env['STATE']/'ai/local-thumbnails';cache.mkdir(parents=True,exist_ok=True)
    try:
        source=env['asset_path'](env['get_asset'](candidate['asset_id']));stat=source.stat()
        key=hashlib.sha256(dump([candidate['asset_id'],candidate['start'],candidate['end'],stat.st_size,stat.st_mtime_ns]).encode()).hexdigest();target=cache/(key+'.jpg')
        if not target.exists():
            subprocess.run([env['CONFIG']['ffmpeg'],'-hide_banner','-loglevel','error','-nostdin','-ss',str((candidate['start']+candidate['end'])/2),'-i',str(source),'-frames:v','1','-vf','scale=384:-2','-q:v','4','-y',str(target)],check=True,capture_output=True,timeout=30,creationflags=FLAGS)
        if not target.is_file() or not target.stat().st_size:raise ValueError('没有抽到帧')
        candidate['image']=str(target.resolve());candidate['thumbnail_status']='已抽取窗口中点'
    except Exception:
        candidate['image']=str((env['BASE']/'static/local-thumbnail-unavailable.svg').resolve());candidate['thumbnail_status']='缩略图取不到';candidate['warnings'].append('缩略图取不到')

def register(app,env):
    review_dictation.register(app,env)
    store=app.extensions['annotation_store'];learning=env['STATE']/'ai/learning.sqlite3'
    root=env['BASE'].parent
    @lru_cache(maxsize=1)
    def cached_viewpoints(version):return Viewpoints(root)
    def viewpoints():
        directory=root/'画面类型素材路径库/文案画面类型标注'
        stamp=tuple((directory/name).stat().st_mtime_ns for name in ('观点画面类型.xlsx','原文定位索引.jsonl'))
        return cached_viewpoints(stamp)
    rule_dir=env.get('VIEWPOINT_RULE_DIR',root/'画面类型素材路径库/文案画面类型标注')
    plan=env.get('VIEWPOINT_PLAN',root/'镜序_文案到镜头选片方案.md')
    rank_dir=env.get('VIEWPOINT_RULE_DIR', rule_dir if env['STATE'].resolve()==(root/'local/cutframe').resolve()
                     else env['STATE']/'文案画面类型标注')
    app.extensions['selection_rank_directory']=rank_dir
    directory=Path(env.get('CLOUD_DATA_DIR',root/'修订产出/团队云端' if env['STATE'].resolve()==(root/'local/cutframe').resolve() else env['STATE']/'团队云端'))
    cloud=SelectionSource(env['STATE']/'ai/团队云端/learning.sqlite3',directory/'镜序素材清洗与分类_云端.xlsx',
                          directory,directory/'选片方案_云端.md',directory,'cloud-')
    cloud.learning.parent.mkdir(parents=True,exist_ok=True)
    with contextlib.closing(connect(cloud.learning)):pass
    cloud_store=Store(cloud.learning.parent/'annotation.sqlite3')
    Rules(cloud_store)
    with cloud_store.db() as db:
        labels=json.loads((env['BASE']/'rules/label-tree-v0.2.json').read_text('utf-8'))['labels']
        db.executemany('INSERT OR IGNORE INTO label_registry VALUES(?,?,?)',[(r['id'],r['name'],r['dimension']) for r in labels])
    def selected_store():
        return cloud_store if active_source()==cloud else store
    discovery_lock=Lock()
    app.extensions['selection_sources']=(SelectionSource(learning,structured_entry.default_clean_book(root),rule_dir,plan,rank_dir),cloud)
    slot_review.register(app,learning,rule_dir,plan,rank_dir)
    def lookup(data):
        leading,trailing=data.get('leading'),data.get('trailing')
        for side in (leading,trailing):
            if side is not None and (not isinstance(side,list) or len(side)>128 or
                    any(not isinstance(s,str) for s in side)):
                raise ValueError('相邻字幕格式无效')
        view=viewpoints().lookup(data.get('text',''),data.get('before',''),data.get('after',''),leading,trailing)
        view=structured_selection.resolve(root,data.get('text',''),view)
        if not view['primary'] and not view['defaults'] and not view['alternatives_by_id'] and not (view.get('entry_id') and view.get('status','').startswith('人工')):
            view.update(defaults=['V01','V02','V05'],fallback_types=True)
        if view.get("entry_id"):view["primary_version"]=str(structured_selection.book_path(root).stat().st_mtime_ns)
        return annotation_channels.annotate_view(root,view,data.get('text',''))
    annotation_channels.register(app,root,learning,lookup,lambda: body())
    @app.route('/api/local/viewpoint',methods=['GET','POST'])
    def local_viewpoint():return jsonify(lookup(body() if request.method=='POST' else request.args))
    @app.post('/api/local/annotation-draft')
    def local_annotation_draft():
        d=body()
        return jsonify(structured_entry.draft(root,d.get('text'),lookup(d),d.get('trailing') or []))
    @app.post('/api/local/annotation-auto')
    def local_annotation_auto():
        d=body()
        text=d.get('text')
        if not isinstance(text,str) or not text.strip() or len(text)>2000 or any(ord(c)<32 and c not in '\r\n\t' for c in text):
            raise ValueError('字幕原句无效')
        # 兼容仍在使用旧页面的成员；选中字幕仅做对照。
        return jsonify(lookup(d))
    @app.post('/api/local/annotation-primary')
    def local_annotation_primary():
        d=body()
        with contextlib.closing(connect(learning)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            view=lookup(d)
            ident=view.get('entry_id')
            if not ident or ident!=view.get('id') or ident!=d.get('id') or view['alternatives_by_id']:
                raise ValueError('请选择能唯一定位到原行的代表句')
            structured_entry.update_primary(root,ident,d.get('version'),d.get('primary'),clean_book=active_source().clean_book)
            return jsonify(lookup(d))
    @app.post('/api/local/annotation-confirm')
    def local_annotation_confirm():
        d=body()
        with contextlib.closing(connect(learning)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            view=lookup(d)
            if not view.get('entry_id') or view['entry_id']!=d.get('id'):
                raise ValueError('请先将未匹配字幕送入待标注')
            entry=structured_entry.draft(root,d.get('text'),view,d.get('trailing') or [])
            if (entry['version'],entry['id'])!=(d.get('version'),d.get('id')):
                raise ValueError('标注表已变化，请重新打开草稿')
            ident=structured_entry.save(root,entry,d.get('form'),d.get('reviewer'),clean_book=active_source().clean_book)
        return jsonify(id=ident)
    def selector():
        source=active_source()
        return Selection(selected_store().path,env['STATE']/'catalog.sqlite3',source.learning,env['CONFIG']['roots'],env['metadata'],blocked_sources(root/'local/action-annotation'),root/'画面类型素材路径库',source.ranking,source.clean_book,cloud.clean_book,learning if source==cloud else cloud.learning)
    def body():
        d=request.get_json(silent=True)
        if not isinstance(d,dict):raise ValueError('请求必须为JSON对象')
        return d
    @app.get('/api/local/status')
    def local_status():
        roots={k:v.get('label',k) for k,v in env['CONFIG']['roots'].items() if v.get('role')=='raw'}
        source=active_source()
        scope=request.args.get('scope') or request.headers.get('X-Material-Scope') or 'all'
        allowed=[k for k in roots if (env['CONFIG']['roots'][k].get('origin')=='cloud')==(source==cloud) and scope in ('all',k)]
        with readonly(env['STATE']/'catalog.sqlite3') as c:
            total=c.execute('SELECT count(*) FROM assets WHERE available=1 AND root IN ('+','.join('?' for _ in allowed)+')',allowed).fetchone()[0]
        return jsonify(message='本机查询，未调用云端，费用 0',roots=roots,catalog_total=total,classification_book=source.clean_book.name,
                       clean_version=clean_selection.version(source.clean_book),semantic_book=structured_selection.book_path(root).name)
    @app.post('/api/local/discover')
    def local_discover():
        with discovery_lock:
            return discover()
    def discover():
        d=body()
        d.setdefault('scope',request.headers.get('X-Material-Scope') or 'all')
        conditions=active_conditions(d.get('conditions',{}))
        path=active_source().clean_book
        tree=clean_selection.label_tree(path,clean_selection.version(path))
        allowed={(t['dimension'],t['id']) for t in tree['labels']}
        for rows in conditions.values():
            for r in rows:
                if any((r['dimension'],t) not in allowed for t in r['tags']) and d.get('trigger')!='auto':
                    raise ValueError('当前素材表没有这项标签，请刷新检索条件')
        if len(str(d.get('context','')))>1500:raise ValueError('上下文过长')
        types=list(dict.fromkeys(t for row in conditions['must'] if row['dimension']=='画面类型' for t in row['tags']))
        if any(t not in {f'V{i:02}' for i in range(1,25)} for t in types):
            raise ValueError('必须的画面类型限于 V01 至 V24')
        has_category=bool(conditions['must'])
        if not types and not has_category and not any(isinstance(k,str) and k.strip() for k in (d.get('keywords') or [])):
            raise ValueError('请先勾选画面类型或填写描述关键词')
        view=lookup(d)
        if view['id'] and not (d.get('need') or '').strip():
            d['need']=view['action']
        trigger=d.get('trigger','')
        if trigger not in ('','auto','changed','retry','next'):raise ValueError('检索来源无效')
        if trigger=='auto':
            if (not view['defaults'] or types!=view['defaults'] or len(conditions['must'])!=1
                    or conditions['prefer'] or conditions['forbid'] or d.get('keywords')):
                raise ValueError('本句没有对应的自动检索条件，请重新核对标注表')
        
        changes=d.get('type_changes',[])
        if not isinstance(changes,list) or len(changes)>500 or any(not isinstance(x,dict) or x.get('action') not in ('追加','取消') or x.get('type') not in {f'V{i:02}' for i in range(1,25)} for x in changes):
            raise ValueError('画面类型勾选记录无效')
        clean_version=clean_selection.version(active_source().clean_book)
        def same_view(prior):
            previous=prior.get('viewpoint') or {}
            return previous.get('structured_version')==view.get('structured_version') and previous.get('id')==view['id'] and previous.get('joined','')==view['joined']
        def stale_zero(result):
            return not result['items'] and (not result.get('classified_pool') or result.get('filters',{}).get('非竖屏预筛',0)>0)
        def same_query(prior):
            return (active_conditions(prior.get('conditions',{}))==conditions
                    and (prior.get('keywords') or [])==(d.get('keywords') or [])
                    and (prior.get('scope') or 'all')==(d.get('scope') or 'all')
                    and bool(prior.get('use_experience'))==bool(d.get('use_experience'))
                    and bool(prior.get('manual_browse'))==bool(d.get('manual_browse'))
                    and bool(prior.get('manual_revisit'))==bool(d.get('manual_revisit')))
        def gate(batch):
            if trigger=='retry' and not batch:raise ValueError('请先选择本句当前的空批次')
            if not batch:return
            rid,prior,stored=batch
            if (prior.get('viewpoint') or {}).get('annotation_revision','')!=view.get('annotation_revision',''):return
            if stored.get('clean_version')!=clean_version or stored.get('capacity')!=5:return
            if trigger=='next' and d.get('previous_run') and d['previous_run']!=rid:
                if prior.get('previous_run')==d['previous_run']:return stored
                raise ValueError('当前批次已更新，请返回本句最新一轮')
            old_types=prior.get('type_selection',{}).get('selected',[])
            if trigger=='auto':
                if not same_view(prior) or stale_zero(stored):return
                if prior.get('type_source')=='manual' or prior.get('trigger')=='changed':return stored
                if old_types==types and prior.get('viewpoint',{}).get('inherited','')==view['inherited']:return stored
                return
            if trigger=='changed':return stored if same_view(prior) and same_query(prior) and not stale_zero(stored) else None
            if trigger=='retry':
                if prior.get('retry_of')==d.get('retry_of') and d.get('retry_of') and same_query(prior):return stored
                if rid!=d.get('retry_of') or stored['items'] or not same_view(prior) or not same_query(prior):
                    raise ValueError('本轮已变化，请按当前条件重新检索')
                return
        def revision(db,batch):
            return db.execute('SELECT MAX(rowid) FROM slot_reviews').fetchone()[0],batch[0] if batch else ''
        with readonly(active_source().learning) as db:
            checked_rowid=db.execute('SELECT COALESCE(MAX(rowid),0) FROM runs').fetchone()[0]
            batch=slot_review.current_batch(db,d)
            before=revision(db,batch)
            existing=gate(batch)
            if existing:return jsonify(existing)
            restore_manual=(trigger=='auto' and batch and same_view(batch[1]) and stale_zero(batch[2])
                            and (batch[1].get('type_source')=='manual' or batch[1].get('trigger')=='changed'))
            if restore_manual:
                # 上次手动选择可能比标注表默认类型多。修复旧空批次时原样重跑用户的条件。
                prior=batch[1]
                conditions=active_conditions(prior['conditions'])
                types=prior['type_selection']['selected']
                d=dict(d,scope=prior.get('scope') or 'all',keywords=prior.get('keywords') or [],
                       use_experience=prior.get('use_experience',False))
            if trigger=='retry' or restore_manual:
                changes=batch[1].get('type_selection',{}).get('changes',[])
            rules=[r for r in read_rules(db) if view['category'] in r['categories']]
            refs=viewpoints().references(view,d.get('text',''),slot_review.effective(db),include_local_examples=active_source()!=cloud)
        payload={k:d.get(k,'') for k in ('text','need','context','scope','project_id','task_id','board_context','reviewer')}
        payload.update(manual_browse=bool(d.get('manual_browse')),manual_revisit=bool(d.get('manual_revisit')),provider='local',conditions=conditions,keywords=d.get('keywords',[]),use_experience=bool(d.get("use_experience")),source_mode='local')
        source='fallback' if view.get('fallback_types') and types==view['defaults'] else 'table'
        if trigger=='changed' or restore_manual:source='manual'
        if trigger in ('retry','next') and batch:source=batch[1].get('type_source','manual' if types!=view['defaults'] else 'table')
        if trigger=='retry':payload['retry_of']=d['retry_of']
        if trigger=='next' and batch:payload['previous_run']=batch[0]
        payload.update(trigger=trigger,type_source=source,viewpoint=view,type_selection=dict(defaults=view['defaults'],selected=types,
                       added=[t for t in types if t not in view['defaults']],removed=[t for t in view['defaults'] if t not in types],changes=changes))
        while True:
            result=selector().query(dict(d,conditions=conditions,view_rules=rules,viewpoint=view,type_source=source))
            rid=active_source().prefix+uuid.uuid4().hex
            if clean_selection.version(active_source().clean_book)!=clean_version:raise ValueError('清洗表已更新，请重新检索')
            result.update(clean_version=clean_version,run_id=rid,task_id=payload['task_id'],viewpoint_review=True,experience_options=refs,classified_pool=True)
            offered={item['asset_id'] for item in result['items']}
            payload.update(duration=result['duration'],rules=sorted({rule for item in result['items'] for rule in item['rule_ids']}))
            for candidate in result['items']:
                candidate['inherited']=view['inherited'] if source=='table' and types==view['defaults'] else ''
                thumbnail(env,candidate)
            with contextlib.closing(connect(active_source().learning)) as c,c:
                c.execute('BEGIN IMMEDIATE')
                latest=slot_review.current_batch(c,d)
                if revision(c,latest)!=before:
                    existing=gate(latest)
                    if existing:return jsonify(existing)
                    raise ValueError('检索期间批次或审核记录已更新，请重新检索')
                # 同一工程可能在抽帧期间先拿到同一原片。提交前核对新增批次，有重叠就用最新候选池重选。
                concurrent=c.execute("SELECT rowid,result FROM runs WHERE rowid>? AND json_extract(payload, '$.project_id')=? ORDER BY rowid",(checked_rowid,d['project_id']))
                collision=False
                for row in concurrent:
                    checked_rowid=row['rowid']
                    if any(item.get('asset_id') in offered for item in json.loads(row['result']).get('items',[])):
                        collision=True
                if collision:continue
                if (trigger=='retry' and batch[2].get('clean_version')==clean_version and not result['items'] and not stale_zero(batch[2])
                        and all(result.get(k)==batch[2].get(k) for k in ('filters','type_counts','blocked'))):
                    return jsonify(batch[2])
                c.execute('INSERT INTO runs VALUES(?,?,?,?)',(rid,now(),dump(payload),dump(result)))
            return jsonify(result)
    @app.post('/api/local/reserve')
    def local_reserve():
        d=body()
        with readonly(active_source().learning) as db:
            prior,_=slot_review.load_run(db,d.get('run_id'))
            latest=slot_review.current_batch(db,prior)
            if not latest or latest[0]!=d.get('run_id'):raise ValueError('只能核对当前批次的剩余素材')
        result=selector().query(dict(prior,trigger='next',exclude_assets=d.get('exclude_assets',[])))
        return jsonify(remaining=len(result['items'])+result['remaining'],unchecked_sources=result['unchecked_sources'])
    @app.get('/api/local/suggestion')
    def local_suggestion():return jsonify(suggestion=selector().suggest(request.args.get('text','')))
    @app.get('/api/local/previous')
    def local_previous():return jsonify(previous=selector().previous(request.args.get('project_id',''),request.args.get('task_id',''),request.args.get('text')))
    def manual_categories():
        path=active_source().clean_book
        if not path.is_file():return []
        return sorted({row[2] for row in clean_selection.load(path,clean_selection.version(path),True) if row[2]})

    @app.get('/api/local/manual-categories')
    def list_manual_categories():return jsonify(manual_categories())

    @app.get('/api/local/labels')
    def local_labels():
        path=active_source().clean_book
        return jsonify(clean_selection.label_tree(path,clean_selection.version(path)))
    @app.post('/api/local/review-type')
    def local_review_type():
        store=selected_store()
        d=body();reviewer=str(d.get('reviewer','')).strip();code=d.get('tag');verdict=d.get('verdict')
        if not reviewer or len(reviewer)>80:raise ValueError('评价人必填，最多80字')
        if verdict not in ('confirm','correct','label'):raise ValueError('画面类型核对动作无效')
        store.validate_labels('画面类型',[code])
        with readonly(active_source().learning) as c:r=c.execute('SELECT * FROM runs WHERE id=?',(d.get('run_id'),)).fetchone()
        if not r:raise ValueError('批次不存在')
        payload=json.loads(r['payload']);result=json.loads(r['result'])
        if payload.get('provider')!='local':raise ValueError('仅支持本机候选')
        candidate=next((x for x in result['items'] if x['id']==d.get('candidate_id')),None)
        if not candidate:raise ValueError('候选不属于该批次')
        with store.db() as c:
            if store is cloud_store and not c.execute('SELECT 1 FROM originals WHERE asset_id=?',(candidate['asset_id'],)).fetchone():
                store.original(candidate['asset_id'],logical_path=candidate['rel'],duration=candidate['duration'],c=c)
            machine_ids=[]
            for ident in candidate.get('machine_annotation_ids',[]):
                a=c.execute("SELECT * FROM annotations WHERE id=? AND source='机器' AND dimension='画面类型'",(ident,)).fetchone()
                if a:machine_ids.append(ident)
            if verdict=='confirm':
                if not any(code in json.loads(c.execute('SELECT labels FROM annotations WHERE id=?',(ident,)).fetchone()[0]) for ident in machine_ids):raise ValueError('确认类型必须与候选机器标签一致；改正请用改正动作')
            sid=store.create(candidate['asset_id'],candidate['start'],candidate['end'],operator=reviewer,allow_unknown=True,c=c)
            previous=c.execute("SELECT * FROM annotations a WHERE segment_id=? AND dimension='画面类型' AND source='人工' AND NOT EXISTS(SELECT 1 FROM annotations n WHERE n.supersedes=a.id) ORDER BY rowid DESC LIMIT 1",(sid,)).fetchone()
            ann=store.annotate(sid,dict(dimension='画面类型',labels=[code],source='人工',review_status='人工改正' if verdict=='correct' else '人工确认',reviewer=reviewer,evidence=dict(run_id=r['id'],candidate_id=candidate['id'],machine_annotation_ids=machine_ids),raw=dict(run_id=r['id'],candidate_id=candidate['id'],machine_annotation_ids=machine_ids),reason='人工只核对候选窗口'),supersedes=previous['id'] if previous else None,c=c)
        return jsonify(segment_id=sid,annotation_id=ann,message='只对候选窗口生效；原机器片段及机器标注保持未审')
