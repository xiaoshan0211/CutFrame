"""人工知识：事实仅限源时间段；团队标准和个人偏好可用于新源。"""
import hashlib
import json
import math
from pathlib import Path
from ai_store import connect,now


def import_confirmed(folder, dbpath):
    """只导入正式确认文件，不读before/discovery；幂等且不复活被停用的记录。"""
    added=[]
    with connect(dbpath) as db:
        for pattern in ('person-[0-9][0-9].json','product-[0-9][0-9].json'):
            for p in sorted(Path(folder).glob(pattern)):
                for r in json.loads(p.read_text('utf-8')).get('rows',[]):
                    if not r.get('confirmed_by') or not r.get('confirmation_evidence'):continue
                    s=r['source'];start,end=float(s['start']),float(s['end'])
                    if not math.isfinite(start+end) or start<0 or end<=start:raise ValueError('历史标注时间无效：'+r['sample_id'])
                    ids=[]
                    if r.get('person_identity')=='阿文' or any(t.get('identity')=='阿文' for t in r.get('person_targets',[])):ids.append('阿文')
                    product=r.get('product_identity','')
                    if product.startswith('微陶泥（用户确认') or r.get('project_product_confirmed') is True:ids.append('微陶泥')
                    payload=dict(kind='fact',scope='similar',project_id='',text='',asset_id=s['id'],start=start,end=end,identities=ids,confirmed_by=r['confirmed_by'],evidence=r['confirmation_evidence'],sample_id=r['sample_id'],person_targets=r.get('person_targets',[]),person_identity=r.get('person_identity'),product_identity=product,confirmed_action=r.get('confirmed_action'),action_segments=r.get('action_segments',[]),description=r.get('confirmed_label') or '',reason=r.get('label_note',''),reason_code='confirmed',source_record=str(p.resolve()),source_record_hash=hashlib.sha256(p.read_bytes()).hexdigest(),apply_to_directory=False,usable=r.get('eligible_for_current_video',True),context=r.get('visible_product_application',''))
                    rid='confirmed-'+r['sample_id']
                    if db.execute('SELECT 1 FROM rules WHERE id=?',(rid,)).fetchone():continue
                    raw=json.dumps(payload,ensure_ascii=False)
                    db.execute('INSERT INTO rules VALUES(?,?,?,?,?,?)',(rid,now(),'historical:'+r['sample_id'],'approved',r['confirmed_by'],raw))
                    db.execute('INSERT INTO rule_events VALUES(?,?,?,?,?,?,?)',(rid+'-import',now(),rid,'approved',r['confirmed_by'],'{}',raw))
                    added.append(rid)
    return added


def snapshot(db,project,reviewer,enabled=True):
    facts=[];general=[]
    for row in db.execute("SELECT * FROM rules WHERE status='approved' ORDER BY id"):
        p=json.loads(row['payload']);kind=p.get('kind','fact')
        if p.get('scope')=='project' and p.get('project_id')!=project:continue
        item=dict(p,id=row['id'],kind=kind,reviewed_by=row['reviewer'])
        if kind=='fact':facts.append(item)
        elif enabled and (kind=='team' or kind=='personal' and p.get('owner')==reviewer):general.append(item)
    data=dict(facts=facts,general=general,reviewer=reviewer,enabled=enabled)
    data['hash']=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return data


def select_experience(knowledge,asset_id,start,end,text):
    facts=[r for r in knowledge.get('facts',[]) if r.get('asset_id')==asset_id and r.get('start',float('inf'))<=start and r.get('end',-1)>=end]
    general=[r for r in knowledge.get('general',[]) if not r.get('keywords') or any(k in text for k in r['keywords'])]
    # 不发送路径、原文件名；保留事实里的多人位置描述和动作边界。
    fields=('id','kind','description','reason','reason_code','identities','person_targets','person_identity','product_identity','confirmed_action','action_segments','evidence','start','end','usable','context')
    return [{k:r[k] for k in fields if k in r} for r in facts+general]


def validate_draft(data,project):
    kind=data.get('kind');description=str(data.get('description','')).strip()
    if kind not in ('team','personal') or not 1<=len(description)<=1500:raise ValueError('请选择团队标准或个人偏好并填写具体规则')
    owner=str(data.get('owner','')).strip()
    if kind=='personal' and not owner:raise ValueError('个人偏好需要指定评价人')
    scope=data.get('scope','project')
    if scope not in ('project','similar') or scope=='project' and not project:raise ValueError('请选择适用工程或所有工程')
    keywords=data.get('keywords',[])
    if not isinstance(keywords,list) or len(keywords)>20 or any(not isinstance(k,str) or not k.strip() or len(k)>40 for k in keywords):raise ValueError('适用关键词格式无效')
    return dict(kind=kind,description=description,owner=owner if kind=='personal' else '',scope=scope,project_id=project if scope=='project' else '',keywords=keywords,text='',reason='',reason_code='manual',context='')
