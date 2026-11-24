"""规则包草稿、逐行校验、内容哈希确认、不可变发布及任务版本绑定。"""
import json,hashlib,math,re,copy,csv,argparse
from pathlib import Path
from annotation_store import Store,dump,uid,now

def content_hash(content):return hashlib.sha256(dump(content).encode('utf-8')).hexdigest()
GROUPS=('must','prefer','forbid')
QUALIFIED='机器拆解，带限定语，待人核对'
EXPLANATION='只作说明，不参与判断'

def validate(content):
    issues=[]
    def issue(rule,group,line,message):issues.append(dict(rule_id=rule,group=group,line=line,message=message))
    if not isinstance(content,dict):return [dict(rule_id='',group='package',line=0,message='规则包必须是对象')]
    tree=content.get('label_tree');rules=content.get('rules')
    if not isinstance(tree,dict):issue('','label_tree',0,'标签树必须是对象');tree={}
    dimensions=tree.get('dimensions',[]);attributes=tree.get('attributes',[]);labels=tree.get('labels',[])
    if not isinstance(dimensions,list):issue('','label_tree',0,'维度必须是数组');dimensions=[]
    if not isinstance(attributes,list):issue('','label_tree',0,'属性必须是数组');attributes=[]
    if not isinstance(labels,list):issue('','label_tree',0,'标签必须是数组');labels=[]
    dims={d.get('id') for d in dimensions+attributes if isinstance(d,dict) and isinstance(d.get('id'),str)};byid={}
    for i,label in enumerate(labels,1):
        if not isinstance(label,dict):issue('','label_tree',i,'标签必须是对象');continue
        ident=label.get('id')
        if not isinstance(ident,str) or not ident:issue('','label_tree',i,'标签编号必填');continue
        if ident in byid:issue('','label_tree',i,'标签编号重复')
        byid[ident]=label
        if not isinstance(label.get('dimension'),str) or label.get('dimension') not in dims:issue('','label_tree',i,'标签维度不存在')
        if not isinstance(label.get('name'),str) or not label['name'].strip():issue('','label_tree',i,'标签名称必填')
        if not isinstance(label.get('enabled'),bool):issue('','label_tree',i,'标签启用字段必须为布尔值')
        if label.get('vocabulary_layer') not in ('行业通用','品类专有','企业专有','待定'):issue('','label_tree',i,'词表层无效')
    for i,label in enumerate(labels,1):
        if not isinstance(label,dict):continue
        parent=label.get('parent')
        if parent is not None:
            if not isinstance(parent,str) or parent not in byid or byid[parent].get('dimension')!=label.get('dimension'):issue('','label_tree',i,'父标签不存在或维度不一致')
            seen={label.get('id')};cursor=parent
            while isinstance(cursor,str) and cursor in byid:
                if cursor in seen:issue('','label_tree',i,'标签父级循环');break
                seen.add(cursor);cursor=byid[cursor].get('parent')
    if not isinstance(rules,list):issue('','rules',0,'句子规则必须为数组');return issues
    if not rules:issue('','rules',0,'规则包至少需要一条句子规则')
    ruleids=set()
    for index,rule in enumerate(rules,1):
        if not isinstance(rule,dict):issue(str(index),'rule',0,'规则必须是对象');continue
        rid=rule.get('id') if isinstance(rule.get('id'),str) else str(index)
        for key in ('id','suite','text'):
            if not isinstance(rule.get(key),str) or not rule[key].strip():issue(rid,'rule',0,key+'必填且必须为字符串')
        if rid in ruleids:issue(rid,'rule',0,'规则编号重复')
        ruleids.add(rid)
        duration=rule.get('target_duration')
        if duration is not None and (isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0):issue(rid,'rule',0,'目标时长必须为空或正数')
        if not isinstance(rule.get('illustration_only'),bool):issue(rid,'rule',0,'画面只能示意必须为布尔值')
        for key in ('unprovable','notes'):
            if not isinstance(rule.get(key),str):issue(rid,'rule',0,key+'必须为字符串')
        references={g:{} for g in GROUPS}
        for group in GROUPS:
            rows=rule.get(group)
            if not isinstance(rows,list):issue(rid,group,0,'条件组必须为数组');continue
            for line,row in enumerate(rows,1):
                if not isinstance(row,dict):issue(rid,group,line,'条件行必须是对象');continue
                if not isinstance(row.get('raw'),str):issue(rid,group,line,'行原文必须为字符串')
                dim=row.get('dimension')
                state=row.get('structure_status')
                if state==EXPLANATION or (state=='人工编辑' and row.get('explanation_only') is True):continue
                if not isinstance(dim,str) or dim not in dims:issue(rid,group,line,'条件维度不存在')
                if state not in ('机器拆解，未经人核对','未结构化','人工编辑',QUALIFIED):issue(rid,group,line,'结构化状态无效')
                if state=='未结构化' and group in ('must','forbid'):issue(rid,group,line,'必须或禁止组有未结构化行')
                if state==QUALIFIED and group in ('must','forbid'):issue(rid,group,line,'必须或禁止组有限定语，待人核对')
                tags=row.get('tags')
                if not isinstance(tags,list) or any(not isinstance(t,str) for t in tags):issue(rid,group,line,'标签必须为字符串数组');continue
                if not tags and state!='未结构化':issue(rid,group,line,'结构化行标签不能为空')
                for tag in tags:
                    if tag not in byid:issue(rid,group,line,'引用的标签不存在：'+tag)
                    elif byid[tag].get('dimension')!=dim:issue(rid,group,line,'标签不属于本行维度：'+tag)
                    elif byid[tag].get('group'):issue(rid,group,line,'分组不能作为条件标签：'+tag)
                    elif not byid[tag].get('enabled'):issue(rid,group,line,'标签已停用：'+tag)
                    references[group][(dim,tag)]=line
        for key,line in references['must'].items():
            if key in references['forbid']:issue(rid,'must',line,'与禁止组第'+str(references['forbid'][key])+'行矛盾：'+str(key[1]));issue(rid,'forbid',references['forbid'][key],'与必须组矛盾：'+str(key[1]))
    return issues

class Rules:
    def __init__(self,store):
        self.store=store
        with store.db() as c:c.executescript('''
CREATE TABLE IF NOT EXISTS rule_packages(id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('草稿','已发布')), content TEXT NOT NULL, content_hash TEXT NOT NULL, parent_id TEXT REFERENCES rule_packages(id), confirmed_by TEXT, confirmed_at TEXT, confirmed_hash TEXT, published_at TEXT, version INTEGER UNIQUE, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS published_no_update BEFORE UPDATE ON rule_packages WHEN OLD.status='已发布' BEGIN SELECT RAISE(ABORT,'已发布规则不可修改'); END;
CREATE TRIGGER IF NOT EXISTS published_no_delete BEFORE DELETE ON rule_packages WHEN OLD.status='已发布' BEGIN SELECT RAISE(ABORT,'已发布规则不可删除'); END;
CREATE TABLE IF NOT EXISTS rule_bindings(task_id TEXT PRIMARY KEY, package_id TEXT NOT NULL REFERENCES rule_packages(id), content_hash TEXT NOT NULL, created TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS bindings_no_update BEFORE UPDATE ON rule_bindings BEGIN SELECT RAISE(ABORT,'版本绑定不可修改'); END;
CREATE TRIGGER IF NOT EXISTS bindings_no_delete BEFORE DELETE ON rule_bindings BEGIN SELECT RAISE(ABORT,'版本绑定不可删除'); END;
CREATE TABLE IF NOT EXISTS label_registry(id TEXT PRIMARY KEY, name TEXT NOT NULL, dimension TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS label_references(label_id TEXT PRIMARY KEY REFERENCES label_registry(id));
CREATE TRIGGER IF NOT EXISTS referenced_labels_no_delete BEFORE DELETE ON label_registry WHEN EXISTS(SELECT 1 FROM label_references WHERE label_id=OLD.id) BEGIN SELECT RAISE(ABORT,'被引用标签只能停用'); END;
''')
    def row(self,c,ident):
        r=c.execute('SELECT * FROM rule_packages WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('规则包不存在')
        return dict(r)
    def get(self,ident):
        with self.store.db() as c:r=self.row(c,ident)
        r['content']=json.loads(r['content']);return r
    def list(self):
        with self.store.db() as c:return [dict(r) for r in c.execute('SELECT id,name,status,content_hash,confirmed_by,confirmed_at,version,published_at,parent_id FROM rule_packages ORDER BY created DESC,id')]
    def references(self,c,content):
        tree=content.get('label_tree',{})
        labels=tree.get('labels',[]) if isinstance(tree,dict) else []
        byid={t['id']:t for t in labels if isinstance(t,dict) and isinstance(t.get('id'),str) and isinstance(t.get('name'),str) and isinstance(t.get('dimension'),str)} if isinstance(labels,list) else {}
        # 被任何历史规则或标注引用的标签不能从新版本中删掉。
        used={r[0] for r in c.execute('SELECT label_id FROM label_references')}
        for row in c.execute('SELECT labels FROM annotations'):
            used.update(json.loads(row[0]))
        missing=used-set(byid)
        if missing:raise ValueError('被引用标签不能删除，只能停用：'+','.join(sorted(missing)))
        for ident,label in byid.items():
            old=c.execute('SELECT * FROM label_registry WHERE id=?',(ident,)).fetchone()
            if old and old['dimension']!=label['dimension']:raise ValueError('稳定标签编号不能换维度：'+ident)
            c.execute('INSERT OR IGNORE INTO label_registry VALUES(?,?,?)',(ident,label['name'],label['dimension']))
        rules=content.get('rules',[])
        if isinstance(rules,list):
            for rule in rules:
                if not isinstance(rule,dict):continue
                for group in GROUPS:
                    rows=rule.get(group,[])
                    if not isinstance(rows,list):continue
                    for row in rows:
                        if isinstance(row,dict) and isinstance(row.get('tags'),list):
                            for ident in row['tags']:
                                if isinstance(ident,str) and ident in byid:c.execute('INSERT OR IGNORE INTO label_references VALUES(?)',(ident,))
    def create(self,content,name='新草稿',parent_id=None):
        if not isinstance(content,dict):raise ValueError('规则包必须为JSON对象')
        if not isinstance(name,str) or not name.strip():raise ValueError('草稿名称必填')
        ident=uid();digest=content_hash(content)
        with self.store.db() as c:
            if parent_id:self.row(c,parent_id)
            self.references(c,content)
            c.execute('INSERT INTO rule_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(ident,name,'草稿',dump(content),digest,parent_id,None,None,None,None,None,now(),now()));self.store.event(c,'rule_package',ident,'新建草稿',None,dict(content_hash=digest,parent_id=parent_id))
        return self.get(ident)
    def save(self,ident,content,expected_hash=None,bulk_event=None):
        if not isinstance(content,dict):raise ValueError('规则包必须为对象')
        digest=content_hash(content)
        with self.store.db() as c:
            old=self.row(c,ident)
            if old['status']!='草稿':raise ValueError('已发布版本只读，请另起草稿')
            if expected_hash is not None and expected_hash!=old['content_hash']:raise ValueError('草稿已变化，请刷新后再编辑')
            self.references(c,content)
            if digest!=old['content_hash']:
                c.execute('UPDATE rule_packages SET content=?,content_hash=?,confirmed_by=NULL,confirmed_at=NULL,confirmed_hash=NULL,updated=? WHERE id=?',(dump(content),digest,now(),ident));self.store.event(c,'rule_package',ident,'保存草稿',old,self.row(c,ident),'内容变化，业务确认失效')
            if bulk_event:self.store.event(c,'rule_package',ident,'按相同原文套用',None,bulk_event,'原文及条件组完全相同')
        return self.get(ident)
    def pending(self,ident):
        content=self.get(ident)['content'];groups={}
        for rule in content['rules']:
            for group in GROUPS:
                for index,row in enumerate(rule[group]):
                    if row.get('structure_status') not in ('未结构化',QUALIFIED):continue
                    key=row['raw'];item=groups.setdefault(key,dict(raw=row['raw'],count=0,group_counts={},locations=[]))
                    item['count']+=1;item['group_counts'][group]=item['group_counts'].get(group,0)+1;item['locations'].append(dict(rule_id=rule['id'],group=group,index=index,text=rule['text']))
        return sorted(groups.values(),key=lambda x:(-x['count'],x['raw']))
    def apply_same(self,ident,rule_id,group,index,include_manual=False,expected_hash=None):
        if group not in GROUPS or not isinstance(index,int) or isinstance(index,bool):raise ValueError('来源行位置无效')
        p=self.get(ident)
        if expected_hash is None or expected_hash!=p['content_hash']:raise ValueError('草稿已变化，请刷新后再套用')
        source_rule=next((r for r in p['content']['rules'] if r['id']==rule_id),None)
        if not source_rule or index<0 or index>=len(source_rule[group]):raise ValueError('来源行不存在')
        source=source_rule[group][index]
        if source.get('structure_status')!='人工编辑':raise ValueError('请先人工处理来源行并保存')
        locations=[]
        for rule in p['content']['rules']:
            for i,row in enumerate(rule[group]):
                if rule['id']==rule_id and i==index:continue
                if row['raw']!=source['raw'] or (row.get('structure_status')=='人工编辑' and not include_manual):continue
                for key in ('dimension','tags','notes','explanation_only'):row[key]=copy.deepcopy(source.get(key,False if key=='explanation_only' else '' if key=='notes' else []))
                row['structure_status']='人工编辑';locations.append(dict(rule_id=rule['id'],group=group,index=i))
        event=dict(source=dict(rule_id=rule_id,group=group,index=index),count=len(locations),locations=locations,include_manual=include_manual)
        result=self.save(ident,p['content'],expected_hash,bulk_event=event);return dict(package=result,applied=len(locations))
    def confirm(self,ident,reviewer,expected_hash=None):
        if not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('确认人必填')
        with self.store.db() as c:
            old=self.row(c,ident)
            if old['status']!='草稿':raise ValueError('仅草稿可确认')
            if expected_hash is not None and expected_hash!=old['content_hash']:raise ValueError('确认内容已变化，请刷新')
            c.execute('UPDATE rule_packages SET confirmed_by=?,confirmed_at=?,confirmed_hash=?,updated=? WHERE id=?',(reviewer,now(),old['content_hash'],now(),ident));self.store.event(c,'rule_package',ident,'业务确认',old,self.row(c,ident),operator=reviewer)
        return self.get(ident)
    def publish(self,ident):
        with self.store.db() as c:
            old=self.row(c,ident)
            if old['status']!='草稿':raise ValueError('仅草稿可发布')
            issues=validate(json.loads(old['content']))
            if issues:raise ValueError('校验未通过，问题数：'+str(len(issues)))
            if not old['confirmed_by'] or old['confirmed_hash']!=old['content_hash']:raise ValueError('当前内容没有有效业务确认')
            version=c.execute('SELECT COALESCE(MAX(version),0)+1 FROM rule_packages').fetchone()[0]
            c.execute("UPDATE rule_packages SET status='已发布',version=?,published_at=?,updated=? WHERE id=?",(version,now(),now(),ident));self.store.event(c,'rule_package',ident,'发布',old,self.row(c,ident),operator=old['confirmed_by'])
        return self.get(ident)
    def bind(self,task_id,ident):
        if not isinstance(task_id,str) or not task_id.strip():raise ValueError('任务编号必填')
        with self.store.db() as c:
            package=self.row(c,ident)
            if package['status']!='已发布':raise ValueError('任务只能绑定已发布版本')
            old=c.execute('SELECT * FROM rule_bindings WHERE task_id=?',(task_id,)).fetchone()
            if old:
                if old['package_id']!=ident:raise ValueError('任务已有固定版本，不可改绑')
            else:
                c.execute('INSERT INTO rule_bindings VALUES(?,?,?,?)',(task_id,ident,package['content_hash'],now()));self.store.event(c,'rule_binding',task_id,'绑定版本',None,dict(package_id=ident,content_hash=package['content_hash']))
        return self.bound(task_id)
    def bound(self,task_id):
        with self.store.db() as c:
            row=c.execute('SELECT * FROM rule_bindings WHERE task_id=?',(task_id,)).fetchone()
            if not row:raise ValueError('任务未绑定规则版本')
            result=dict(row);package=self.row(c,row['package_id'])
        if result['content_hash']!=package['content_hash']:raise ValueError('绑定版本哈希不一致')
        result['content']=json.loads(package['content']);result['version']=package['version'];return result

ALIASES={'主动作':'主动作','材料依据等级':'材料依据等级','他方品牌包装入镜':'画质瑕疵','身份来源':'身份来源','爆款实际配的画面':'可配句意','爆款实际配的画面（几条片子加在一起的镜头个数）':'可配句意'}
def parse_line(raw,tree):
    match=re.match(r'^\s*-\s*([^：:]+)[：:](.*)$',raw);dimension='';tags=[]
    if match:
        name,value=match.groups();dimension=ALIASES.get(name,name);value=re.split(r'（词表[：:]|\(词表[：:]',value,1)[0].strip()
        known={x['id']:x for x in tree['labels'] if not x.get('group')}
        codes=re.findall(r'(?<![A-Za-z0-9])V\d{2}(?!\d)',value)
        if codes:tags=list(dict.fromkeys(codes))
        else:
            matches=[x['id'] for x in known.values() if x['dimension']==dimension and x['name']==value]
            if matches:tags=matches
        # “包装入镜：无”不是“画质瑕疵：无”，不合并成无瑕疵。
        if name=='他方品牌包装入镜':tags=[]
        if any(t not in known or known[t]['dimension']!=dimension for t in tags):tags=[]
        # “不要弄混”表达比较提醒，不能误编译为禁止两个标签。
        if re.search(r'弄混|混淆|混为',value):tags=[]
    qualified=bool(re.search(r'不|无|仅|只|若|须|需|必须|除|否则|前提|条件|才|但|应|优先|避免|确认|证明|同户',re.split(r'（词表[：:]|\(词表[：:]',raw,1)[0]))
    return dict(raw=raw,dimension=dimension,tags=tags,notes='',structure_status=(QUALIFIED if qualified else '机器拆解，未经人核对') if tags else '未结构化')

def recheck_content(content):
    result=copy.deepcopy(content)
    for rule in result['rules']:
        for group in GROUPS:
            for i,row in enumerate(rule[group]):
                if row.get('structure_status') in ('人工编辑',EXPLANATION):continue
                new=parse_line(row['raw'],result['label_tree']);new['notes']=row.get('notes','');rule[group][i]=new
    return result

def t07_package(tsv,tree):
    with Path(tsv).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f,delimiter='\t'))
    result=[]
    dims={d['id'] for d in tree['dimensions']+tree.get('attributes',[])}
    for row in rows:
        rule=dict(id=row['记录ID'],suite=row['套'],text=row['文案原句'],target_duration=float(row['秒数中位']) if row['秒数中位'].strip() else None,illustration_only=row['示意']=='是',unprovable=row['画面证明不了的部分'],notes=row['上报备注'],source_row=row,source_lines={})
        for source,group in [('必须','must'),('优先','prefer'),('禁止','forbid')]:
            original=row[source].splitlines();rule['source_lines'][group]=original;rule[group]=[parse_line(raw,tree) for raw in original]
            for line in rule[group]:
                if line['dimension'] and line['dimension'] not in dims:raise ValueError('停止：T07维度在总纲找不到对应：'+line['dimension']+'，规则'+row['记录ID'])
        result.append(rule)
    return dict(schema_version=1,label_tree=tree,rules=result,source=dict(path=str(tsv),sha256=hashlib.sha256(Path(tsv).read_bytes()).hexdigest()))

def stats(content):
    issues=validate(content);invalid={x['rule_id'] for x in issues}
    rules=content.get('rules',[]) if isinstance(content,dict) else []
    rules=[r for r in rules if isinstance(r,dict)] if isinstance(rules,list) else []
    lines=[line for rule in rules for g in GROUPS if isinstance(rule.get(g),list) for line in rule[g] if isinstance(line,dict)]
    return dict(rule_count=len(rules),structured_lines=sum(x.get('structure_status')!='未结构化' for x in lines),unstructured_lines=sum(x.get('structure_status')=='未结构化' for x in lines),valid_rules=sum(r.get('id') not in invalid and '' not in invalid for r in rules if isinstance(r.get('id'),str)),issues=issues,missing_duration=[r['id'] for r in rules if r.get('target_duration') is None])

def main():
    root=Path(__file__).resolve().parent.parent;p=argparse.ArgumentParser();p.add_argument('--state',type=Path,default=root/'local/cutframe');p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    tree=json.loads((root/'cutframe-studio/rules/label-tree-v0.2.json').read_text('utf-8'));tsv=root/'参考资料/video-harness-lab-references/素材底座项目-20261116/工位产出/T07/20261117_01/第一条线_逐句对照表.tsv';content=t07_package(tsv,tree)
    rules=Rules(Store(a.state/'annotation.sqlite3'));existing=next((x for x in rules.list() if x['content_hash']==content_hash(content)),None);draft=rules.get(existing['id']) if existing else rules.create(content,'T07第一条线99句·导入草稿')
    report=stats(content);report['package_id']=draft['id'];report['content_hash']=draft['content_hash'];report['dimensions']={d['id']:sum(x['dimension']==d['id'] and not x.get('group') for x in tree['labels']) for d in tree['dimensions']};report['unclear_options']=[dict(dimension=d['id'],has_unclear=any(x['name']=='看不清' and x['dimension']==d['id'] for x in tree['labels']),similar=[x['name'] for x in tree['labels'] if x['dimension']==d['id'] and x['name'] in ('未确认','未知','未辨明','无','无人','无动作（空镜）','看不见头脸','看不清','无（主体是人或整个空间）','其他')]) for d in tree['dimensions']]
    a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k in ('rule_count','structured_lines','unstructured_lines','valid_rules')},ensure_ascii=False))
if __name__=='__main__':main()
