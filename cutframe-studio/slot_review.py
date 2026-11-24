"""字幕候选审核。批次和审核记录都保存在同一个学习库中。"""
import json
import re
import uuid
from contextlib import closing
from flask import Response, jsonify, request
from ai_store import connect, now
from copy_viewpoints import add_rules, publish
from ranking_feedback import refresh

NEGATIVE = ('人物不对','空间不对','阶段不对','动作没发生','动作做反了','正面和反例弄反','顺序反了',
            '证据不够，只是看起来相关','同条重复','横屏或清晰度不够','晃动、失焦、拖影','闪帧、冻帧、重复帧',
            '静图、截图、海报、拍摄屏幕','自带字幕、贴纸、水印、界面、二维码、品牌字、手写编号','没看连续画面','产品营销图、品牌展示图')
POSITIVE = ('动作发生了','空间对上','阶段对上','证据够','过渡采用')
CONFLICT = {'动作做反了','正面和反例弄反','空间不对','阶段不对','人物不对'}


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def records(db, run=None):
    sql = 'SELECT data FROM slot_reviews'
    args = ()
    if run is not None:
        sql += ' WHERE run_id=?'
        args = (run,)
    return [json.loads(r[0]) for r in db.execute(sql+' ORDER BY rowid',args)]


def effective(db):
    latest = {}
    for r in records(db):
        if r['status']=='已确认' and r['slot']:
            latest[r['text'],r['project_id'],r['asset_id'],r['start'],r['end']] = r
    return sorted(latest.values(), key=lambda r:r['confirmed_at'],reverse=True)


def decide(rows, text, project, asset, start, end, tags):
    blocked, warnings = [], []
    exact = next((r for r in rows if r['text']==text and r['asset_id']==asset
                  and max(r['start'],start)<min(r['end'],end)),None)
    for r in rows:
        if r['verdict']!='不合适':
            continue
        duplicate = r['project_id']==project and '同条重复' in r['codes'] and r['asset_id']==asset
        if not duplicate and r['text']!=text:
            continue
        conflict = set(r['conflict_tags']).intersection(tags) and CONFLICT.intersection(r['codes'])
        entry = dict(id=r['id'],asset_id=asset,source_asset_id=r['asset_id'],codes=r['codes'],sentence=r['sentence'])
        if duplicate or exact is r or conflict:
            blocked.append(entry)
        elif any(code not in CONFLICT|{'同条重复'} for code in r['codes']) or not r['conflict_tags']:
            warnings.append(entry)
    return blocked,warnings


def state(db, run, result):
    rows = records(db,run)
    latest = {r['slot']:r for r in rows if r['slot'] and r['status']=='已确认'}
    chosen = [s for s,r in latest.items() if r['verdict']=='采用']
    compared = latest[chosen[0]].get('differences',{}) if result.get('viewpoint_review') and chosen else {}
    missing = [c['slot'] for c in result['items'] if c['slot'] not in latest and not compared.get(c['slot'])]
    ids = sorted(r['id'] for r in latest.values())
    group = next((r for r in reversed(rows) if not r['slot'] and r['members']==ids),None)
    if chosen or group:
        missing=[]
    if group:
        chosen=[]
    complete = not missing and (bool(chosen) or bool(group) or not result['items'])
    return dict(records=latest,missing=missing,chosen=chosen,group=group,complete=complete)


def current_batch(db,data):
    fields=('project_id','task_id','text','need','board_context')
    where=' AND '.join(f"COALESCE(json_extract(payload,'$.{k}'),'')=?" for k in fields)
    # 不同 SQLite 版本从 JSON 读取 1.0400000000000003 时会差一个浮点末位。
    where+=" AND ABS(json_extract(payload,'$.duration')-?)<=0.000001"
    where+=" AND COALESCE(NULLIF(json_extract(payload,'$.scope'),''),'all')=?"
    row=db.execute("SELECT id,payload,result FROM runs WHERE json_extract(result,'$.slot_review')=1 AND "
                   +where+' ORDER BY rowid DESC LIMIT 1',(*[data.get(k,'') for k in fields],data.get('duration'),data.get('scope') or 'all')).fetchone()
    if row:return row[0],json.loads(row[1]),json.loads(row[2])


def load_run(db,rid):
    row=db.execute('SELECT payload,result FROM runs WHERE id=?',(rid,)).fetchone()
    if not row or not json.loads(row[1]).get('slot_review'):
        raise ValueError('请选择本机三槽位批次')
    return json.loads(row[0]),json.loads(row[1])


def clean(value, label):
    if not isinstance(value,str) or not value.strip() or len(value)>2000:
        raise ValueError('请填写'+label+'（最多2000字）')
    return value.strip()


def fact_text(value):
    value=clean(value,'看见的事实')
    words=re.sub(r'[\W_]+','',value)
    if len(words)<2 or re.fullmatch(r'(看着|看起来|就是|感觉|画面|素材|很|太|不对劲|不对|不好看|不合适|不符合|说不清|差不多|不知道|不清楚|不好|没看清|了)+',words):
        raise ValueError('请写出实际看见的动作、对象或空间')
    return value


def append(db,r):
    db.execute('INSERT INTO slot_reviews(id,run_id,data) VALUES(?,?,?)',(r['id'],r['run_id'],encode(r)))
    return r


def adopt(db,rid,cid):
    _,result=load_run(db,rid)
    c=next((x for x in result['items'] if x['id']==cid),None)
    if not c:raise ValueError('请选择本轮候选素材')
    s=state(db,rid,result)
    if s['group'] or s['records'].get(c['slot'],{}).get('verdict')=='不合适':
        raise ValueError('这条素材已确认不合适，请选择其他候选')


def save(db,d,simple=False):
    rid=d.get('run_id')
    p,result=load_run(db,rid)
    c=next((c for c in result['items'] if c['id']==d.get('candidate_id')),None)
    if not c:raise ValueError('候选不属于本轮')
    reviewer=clean(d.get('reviewer'),'审核人')
    fact=fact_text(d.get('fact'))
    anchor=clean(d.get('anchor'),'文案落点')
    if anchor not in p['text'] and anchor not in p.get('need',''):
        raise ValueError('请从原句或当前画面要求里取词')
    relation=d.get('relation')
    if relation not in ('做了','没做','做了相反的事','仅作过渡'):raise ValueError('请判断实际动作与文案的关系')
    verdict=d.get('verdict')
    if verdict not in ('采用','不合适'):raise ValueError('请选择审核结论')
    codes=d.get('codes')
    allowed=POSITIVE if verdict=='采用' else NEGATIVE
    if not isinstance(codes,list) or not codes or any(not isinstance(code,str) or code not in allowed for code in codes):
        raise ValueError('请勾选对应原因码')
    transition=verdict=='采用' and codes==['过渡采用']
    if ('过渡采用' in codes and not transition) or (relation=='仅作过渡')!=transition:
        raise ValueError('请核对过渡采用的用途')
    tags=d.get('conflict_tags',[])
    if not isinstance(tags,list) or any(t not in c['tags'] for t in tags) or (tags and not CONFLICT.intersection(codes)):
        raise ValueError('请选择可证明同类冲突的已有标签')
    answers=d.get('answers',{})
    if not isinstance(answers,dict):raise ValueError('旧错核对格式无效')
    known={w['id']:w for w in c['warnings_to_review']}
    for key,answer in answers.items():
        if key not in known or not isinstance(answer,dict) or answer.get('choice') not in ('没有这个错','仍有这个错'):
            raise ValueError('请逐条核对旧错')
        if answer['choice']=='没有这个错':fact_text(answer.get('fact'))
        elif verdict!='不合适' or not set(known[key]['codes']).intersection(codes):
            raise ValueError('仍有旧错，请确认不合适并保留相应原因码')
    title=f"{c['slot']}({c['asset_id']})"
    extra={}
    if result.get('viewpoint_review'):
        view=p['viewpoint']
        extra.update(view_id=view['id'],category=view['category'],polarity=view['polarity'])
    if verdict=='采用':
        if (not transition and relation!='做了') or (not simple and set(answers)!=set(known)):raise ValueError('采用前请确认动作并逐条核对旧错')
        if any(s!=c['slot'] for s in state(db,rid,result)['chosen']):raise ValueError('本轮只能采用一条')
        sentence=f'{title}过渡采用。{fact}。' if transition else f'{title}采用。看见的是{fact}，对上了文案里的「{anchor}」。'
        others=[x for x in result['items'] if x['slot']!=c['slot']]
        if not transition and result.get('viewpoint_review') and others and ('differences' in d or 'extra_fact' in d):
            delta=fact_text(d.get('extra_fact'))
            differences=d.get('differences')
            if not isinstance(differences,dict) or set(differences)!={x['slot'] for x in others}:
                raise ValueError('请分别填写其他候选缺少或做反的点')
            differences={x['slot']:fact_text(differences[x['slot']]) for x in others}
            titles='、'.join(f"{x['slot']}({x['asset_id']})" for x in others)
            why='，'.join(f'{s}是{v}' for s,v in differences.items())
            sentence=f"采用{title}，没采用{titles}。{c['slot']}多了{delta}，{why}。"
            extra.update(extra_fact=delta,differences=differences)
    else:
        sentence=f'{title}不合适这段文案。原因是{fact}，属于{"、".join(codes)}，文案里「{anchor}」没有被这几秒证明。'
        if result.get('viewpoint_review'):
            refs={r['id']:r for r in result['experience_options']}
            selected=d.get('experience_ids',[])
            if not isinstance(selected,list) or any(not isinstance(i,str) or i not in refs for i in selected):
                raise ValueError('请选择本轮有出处的已确认经验')
            extra['experiences']=[refs[i] for i in dict.fromkeys(selected)]
            for r in extra['experiences']:
                sentence+=f"参考「{r['text']}」（{r['source']}）。"
    status=d.get('status','已确认')
    if status not in ('已确认','待补看'):raise ValueError('审核状态无效')
    record={k:p.get(k,'') for k in ('project_id','task_id','text','need')}
    record.update({k:c[k] for k in ('slot','asset_id','rel','start','end')})
    record.update(id=uuid.uuid4().hex,run_id=rid,round=result['round'],reviewer=reviewer,confirmed_at=now(),
                  status=status,verdict=verdict,fact=fact,anchor=anchor,codes=codes,relation=relation,
                  conflict_tags=tags,answers=answers,sentence=sentence)
    record.update(extra)
    previous=next((r for r in reversed(records(db,rid)) if r['slot']==c['slot']),None)
    if previous and all(previous.get(k)==v for k,v in record.items() if k not in ('id','confirmed_at')):
        return previous
    return append(db,record)


def register(app,path,rule_dir=None,plan=None,rank_dir=None):
    def locations():
        if 'selection_sources' in app.extensions:
            from selection_sources import active_source
            src=active_source()
            return src.learning,src.rules,src.plan,src.ranking
        return path,rule_dir,plan,rank_dir
    def refresh_after_save():
        path,_,_,rank_dir=locations()
        if rank_dir:
            try:
                refresh(path,rank_dir)
            except Exception:
                app.logger.exception('审核已提交，排序文件更新失败')
                return '审核已保存，排序文件更新失败，请重新导出并训练。'
        return ''

    @app.post('/api/local/ranking-refresh')
    def ranking_refresh():
        path,_,_,rank_dir=locations()
        return jsonify(refresh(path,rank_dir,force=True))

    @app.post('/api/local/slot-batch')
    def slot_batch():
        d=request.get_json() or {}
        rid=d.get('run_id')
        reviewer=clean(d.get('reviewer'),'审核人')
        with closing(connect(locations()[0])) as db, db:
            db.execute('BEGIN IMMEDIATE')
            payload,result=load_run(db,rid)
            current=state(db,rid,result)
            ids=sorted(r['id'] for r in current['records'].values())
            revision=ids+([current['group']['id']] if current['group'] else [])
            batch=current_batch(db,payload)
            if revision!=d.get('previous') or not batch or batch[0]!=rid:
                raise ValueError('审核或批次已更新，请刷新后重新核对')
            changes=d.get('reviews')
            if not isinstance(changes,list) or not changes:raise ValueError('请先点选候选')
            slots={c['slot']:c for c in result['items']}
            selected=set()
            projected={k:r['verdict'] for k,r in current['records'].items()}
            for item in changes:
                slot=item['slot']
                if slot not in slots or slot in selected:raise ValueError('无效或重复槽位')
                selected.add(slot)
                projected[slot]=item['verdict']
                allowed=POSITIVE if item['verdict']=='采用' else NEGATIVE
                if item['verdict'] not in ('采用','不合适') or item.get('code') not in allowed:
                    raise ValueError('请选择有效原因')
            all_rejected=all(projected.get(k)=='不合适' for k in slots)
            if all_rejected:
                missing=fact_text(d.get('missing'))
                label='ABC均不采用' if len(slots)==3 else '本轮候选均不采用'
                # 整批缺口只记一行，不编造三个逐条可见事实。
                append(db,dict(id=uuid.uuid4().hex,run_id=rid,round=result['round'],slot=None,
                               project_id=payload['project_id'],task_id=payload['task_id'],text=payload['text'],
                               need=payload.get('need',''),reviewer=reviewer,confirmed_at=now(),status='已确认',
                               members=ids,verdict=label,missing=missing,sentence=label+'，'+missing+'。'))
            else:
                for item in sorted(changes,key=lambda x:x['verdict']=='采用'):
                    accepted=item['verdict']=='采用'
                    code=item['code'] if not accepted or item['code']=='过渡采用' else '动作发生了'
                    relation='仅作过渡' if code=='过渡采用' else '做了' if accepted else '做了相反的事' if code=='动作做反了' else '没做'
                    save(db,dict(run_id=rid,candidate_id=slots[item['slot']]['id'],reviewer=reviewer,
                                 verdict=item['verdict'],fact=item.get('fact'),anchor=item.get('anchor'),
                                 codes=[code],relation=relation),simple=True)
        return jsonify(saved=True,warning=refresh_after_save())
    def perform(fn):
        d=request.get_json() or {}
        with closing(connect(locations()[0])) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return jsonify(fn(db,d))
    @app.post('/api/local/slot-review')
    def slot_review():
        _,rule_dir,plan,_=locations()
        d=request.get_json() or {}
        with closing(connect(locations()[0])) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                record=save(db,d)
                _,result=load_run(db,record['run_id'])
                if result.get('viewpoint_review'):
                    add_rules(db,record['run_id'],result,state(db,record['run_id'],result))
            if rule_dir is not None:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    publish(db,rule_dir,plan)
        warning=refresh_after_save()
        return jsonify(dict(record,warning=warning) if warning else record)
    @app.post('/api/local/slot-adopt')
    def slot_adopt():
        return perform(lambda db,d:adopt(db,d.get('run_id'),d.get('candidate_id')) or {'ok':True})
    @app.post('/api/local/slot-finish')
    def slot_finish():
        def finish(db,d):
            rid=d.get('run_id')
            p,res=load_run(db,rid)
            s=state(db,rid,res)
            if s['missing']:raise ValueError('尚缺已确认结论：'+'、'.join(s['missing']))
            if s['chosen'] or s['group']:return s
            if not res['items']:raise ValueError('本轮没有可审核素材')
            missing=fact_text(d.get('missing'))
            label='ABC均不采用' if len(res['items'])==3 else '本轮候选均不采用'
            return append(db,dict(id=uuid.uuid4().hex,run_id=rid,round=res['round'],slot=None,
                            project_id=p['project_id'],task_id=p['task_id'],text=p['text'],need=p.get('need',''),
                            reviewer=clean(d.get('reviewer'),'审核人'),confirmed_at=now(),status='已确认',
                            members=sorted(r['id'] for r in s['records'].values()),verdict=label,missing=missing,
                            sentence=label+'，'+missing+'。'))
        response=perform(finish)
        warning=refresh_after_save()
        return jsonify(dict(response.get_json(),warning=warning)) if warning else response
    @app.get('/api/local/slot-export')
    def slot_export():
        with closing(connect(locations()[0])) as db:
            lines=[r[0]+'\n' for r in db.execute('SELECT data FROM slot_reviews ORDER BY rowid')]
        return Response(lines,mimetype='application/x-ndjson',headers={'Content-Disposition':'attachment; filename="slot-reviews.jsonl"'})
