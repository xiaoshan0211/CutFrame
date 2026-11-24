"""只读本地输入，显式导入片段库；不访问原视频、不调用模型。"""
import argparse,hashlib,json,sqlite3,tempfile,collections,contextlib
from pathlib import Path
from annotation_store import Store,dump,uid,now

def sha(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def jsonl(path):return [json.loads(x) for x in path.read_text('utf-8-sig').splitlines() if x.strip()]
IDENTITIES=['阿文','示例负责人','示例助手','示例监理','示例业主','客户方人物','未确认']
MATERIALS=['微陶泥','液态陶泥','微岩石','微彩陶','微瓷釉','清瓷水漆','磨石地坪','微水泥','墙布墙膜','泛海展厅新材料','其他','未辨明']
def structured(row):
    content=row.get('内容',{});result=[]
    if row.get('样例类别')=='试标50段':
        review=content.get('审核结果',{});verdict=review.get('verdict',row.get('审核结论'))
        code=review.get('fix') if verdict=='错' else review.get('机器画面类型',row.get('机器画面类型')) if verdict=='对' else None
        if isinstance(code,str) and code in {f'V{i:02}' for i in range(1,25)}:result.append(('画面类型',code,False,'人工审核'))
    if row.get('样例类别')=='逐段事实':
        for name in content.get('identities',[]):
            if name in IDENTITIES:result.append(('身份',f'B5I{IDENTITIES.index(name)+1:02}',bool(row.get('是否反例')),'人工确认'))
            elif name in MATERIALS:result.append(('材料类目',f'B7M{MATERIALS.index(name)+1:02}',bool(row.get('是否反例')),'人工确认'))
    return result

def conflict_claims(row):
    content=row.get('内容',{});claims=[]
    for name in content.get('identities',[]):
        if name in IDENTITIES+MATERIALS:claims.append((name,bool(row.get('是否反例'))))
    # 只识别结构化身份字段明确写出的否定，不从自由描述猜标签。
    for field,names in [('person_identity',IDENTITIES),('product_identity',MATERIALS)]:
        text=content.get(field)
        for name in names:
            if text in ('不是'+name,'本片段不是'+name+'（用户确认）'):claims.append((name,True))
    return claims

def import_library(store,source,catalog):
    source=Path(source).resolve();paths={name:source/name for name in ('原片表.jsonl','事实层.jsonl','禁用表.jsonl')};hashes={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in paths.items()};batch=sha(str(source)+dump(hashes))
    with store.db() as c:
        existing=c.execute('SELECT counts FROM imports WHERE id=?',(batch,)).fetchone()
    originals=jsonl(paths['原片表.jsonl']);facts=jsonl(paths['事实层.jsonl']);restrictions=jsonl(paths['禁用表.jsonl'])
    with contextlib.closing(sqlite3.connect(Path(catalog).resolve().as_uri()+'?mode=ro',uri=True)) as c:assets={x[0] for x in c.execute('SELECT id FROM assets')}
    report=dict(input_originals=len(originals),input_facts=len(facts),input_restrictions=len(restrictions),hashes=hashes,source_directory=str(source),original_unregistered=[],original_missing_assets=[],fact_destinations=[],conflicts=[],nonnegative_with_not=[],review_status={},repeated=bool(existing),original_unregistered_reason='镜序未登记')
    candidates=[];statuses=collections.Counter()
    with store.db() as c:
        def remember(row,destination,object_id,old):
            text=dump(row);digest=sha(text);source_file=row.get('来源文件','原片表.jsonl');key=row.get('来源条目标识',row.get('原片ID',row.get('规则ID','')))
            c.execute('INSERT INTO source_records(source_file,source_key,version,content_hash,destination,object_id,raw,created) VALUES(?,?,?,?,?,?,?,?)',(source_file,key,(old['version']+1 if old else 1),digest,destination,str(object_id),text,now()))
            store.event(c,'source_record',source_file+'#'+key,'来源新增版本' if old else '导入',dict(old) if old else None,dict(destination=destination,object_id=object_id,raw=row),operator='导入脚本')
        def prior(row,default):
            file=row.get('来源文件',default);key=row.get('来源条目标识',row.get('原片ID',row.get('规则ID','')))
            rows=c.execute('SELECT * FROM source_records WHERE source_file=? AND source_key=? ORDER BY version DESC',(file,key)).fetchall()
            return (next((r for r in rows if r['content_hash']==sha(dump(row))),None),rows[0] if rows else None)
        for row in originals:
            aid=row.get('镜序素材ID')
            if not aid:
                report['original_unregistered'].append(row['原片ID'])
                same,old=prior(row,'原片表.jsonl')
                if not same:
                    ident=uid();c.execute('INSERT INTO clues VALUES(?,?,?,?)',(ident,'镜序未登记',dump(row),now()));remember(row,'clue',ident,old)
                continue
            if aid not in assets:report['original_missing_assets'].append(dict(asset_id=aid,original_id=row['原片ID']));continue
            same,old=prior(row,'原片表.jsonl')
            if same:continue
            store.original(aid,row.get('原片ID'),row.get('标注库ID'),row.get('逻辑路径',''),row.get('时长'),row,c);remember(row,'original',aid,old)
        for row in facts:
            aid=row.get('镜序素材ID');start,end=row.get('起秒'),row.get('止秒');reason=''
            if not aid:reason='没有镜序素材编号'
            elif aid not in assets:reason='镜序素材编号在assets中不存在'
            elif start is None or end is None:reason='起止秒不完整'
            else:
                if not c.execute('SELECT 1 FROM originals WHERE asset_id=?',(aid,)).fetchone():store.original(aid,row.get('原片ID'),row.get('标注库ID'),row.get('主库相对路径',''),raw={'来源':'事实层补充对照','事实编号':row['事实编号']},c=c)
                try:store.interval(c,aid,start,end,allow_unknown=True)
                except ValueError as e:reason=str(e)
            review='人工确认' if row.get('确认状态')=='已确认' and row.get('确认人') else '待确认'
            flags=[]
            if not row.get('确认人'):flags.append('来源未写确认人')
            if row.get('确认人')=='当前用户':flags.append('确认人身份未核实')
            if row.get('确认状态')=='暂定':flags.append('来源暂定')
            statuses[review]+=1
            if '不是' in row.get('限定语原文','') and not row.get('是否反例'):report['nonnegative_with_not'].append(dict(fact_id=row['事实编号'],text=row['限定语原文']))
            same,old=prior(row,'事实层.jsonl')
            if reason:
                destination='clue';object_id=same['object_id'] if same else uid()
                if not same:c.execute('INSERT INTO clues VALUES(?,?,?,?)',(object_id,reason,dump(row),now()));remember(row,destination,object_id,old)
            else:
                destination='segment'
                previous=c.execute('SELECT segment_id FROM annotations WHERE id=?',(old['object_id'],)).fetchone() if old and old['destination']=='segment' else None
                prior_raw=json.loads(old['raw']) if old else {}
                unchanged_interval=all(prior_raw.get(k)==row.get(k) for k in ('镜序素材ID','起秒','止秒'))
                if same and same['destination']=='segment':
                    object_id=same['object_id'];sid=c.execute('SELECT segment_id FROM annotations WHERE id=?',(object_id,)).fetchone()['segment_id']
                else:
                    sid=previous['segment_id'] if previous and unchanged_interval else store.create(aid,start,end,allow_unknown=True,c=c)
                    if previous and unchanged_interval:flags.append('来源已更新，待人看')
                    # 原始事实独立保存：不把自由文字翻译成标签。
                    object_id=store.annotate(sid,dict(source='人工',negative=bool(row.get('是否反例')),review_status=review,reviewer=row.get('确认人',''),flags=flags,raw=row,evidence=row.get('限定语原文',''),reason='导入事实'),supersedes=old['object_id'] if previous and previous['segment_id']==sid else None,c=c,import_update=True)
                    prior_dimensions={}
                    if previous and previous['segment_id']==sid:
                        for a in c.execute('SELECT * FROM annotations a WHERE segment_id=? AND dimension IS NOT NULL AND NOT EXISTS(SELECT 1 FROM annotations n WHERE n.supersedes=a.id)',(sid,)):
                            r=json.loads(a['raw'])
                            if r.get('来源文件')==row.get('来源文件') and r.get('来源条目标识')==row.get('来源条目标识') and r.get('事实编号')==row.get('事实编号'):prior_dimensions[a['dimension']]=a['id']
                    grouped={}
                    for dim,label,negative,basis in structured(row):
                        d=grouped.setdefault(dim,dict(labels=[],negative=negative,basis=basis));d['labels'].append(label)
                    for dim in set(grouped)|set(prior_dimensions):
                        d=grouped.get(dim,dict(labels=[],negative=False,basis='来源已撤回此维度结论'))
                        store.annotate(sid,dict(dimension=dim,labels=d['labels'],negative=d['negative'],source='人工',review_status=review if d['labels'] else '待确认',reviewer=row.get('确认人',''),flags=flags,raw=row,evidence={'依据':d['basis'],'原文':row.get('限定语原文','')},rule_version=row.get('内容',{}).get('规则版本')),supersedes=prior_dimensions.get(dim),c=c,import_update=True)
                    if same:
                        # 同一原文由线索晋升时只更新去向；历史线索及前后值留在事件中。
                        c.execute('UPDATE source_records SET destination=?,object_id=? WHERE id=?',(destination,object_id,same['id']))
                        store.event(c,'source_record',same['id'],'线索转片段',dict(same),dict(destination=destination,object_id=object_id),operator='导入脚本')
                    else:remember(row,destination,object_id,old)
                candidates.append((row,sid,object_id))
            report['fact_destinations'].append(dict(fact_id=row['事实编号'],destination=destination,object_id=object_id,reason=reason,review_status=review,negative=bool(row.get('是否反例')),flags=flags))
        for i,(a,sid,annotation) in enumerate(candidates):
            for b,bsid,bannotation in candidates[i+1:]:
                if a['镜序素材ID']!=b['镜序素材ID'] or max(a['起秒'],b['起秒'])>=min(a['止秒'],b['止秒']):continue
                opposing={name for name,neg in conflict_claims(a) for other,oneg in conflict_claims(b) if name==other and neg!=oneg}
                if not opposing:continue
                report['conflicts'].append(dict(facts=[a['事实编号'],b['事实编号']],asset_id=a['镜序素材ID'],labels=sorted(opposing),start=max(a['起秒'],b['起秒']),end=min(a['止秒'],b['止秒'])))
                for row,segment_id in [(a,sid),(b,bsid)]:
                    for ann in c.execute('SELECT * FROM annotations WHERE segment_id=?',(segment_id,)).fetchall():
                        if json.loads(ann['raw']).get('事实编号')!=row['事实编号'] or '冲突待确认' in json.loads(ann['flags']):continue
                        if c.execute('SELECT 1 FROM annotations WHERE supersedes=?',(ann['id'],)).fetchone():continue
                        store.annotate(segment_id,dict(range_id=ann['range_id'],dimension=ann['dimension'],labels=json.loads(ann['labels']),negative=bool(ann['negative']),source=ann['source'],review_status='待确认',reviewer=ann['reviewer'],flags=json.loads(ann['flags'])+['冲突待确认'],raw=row,evidence=json.loads(ann['evidence']),reason='重叠区间身份或材料冲突'),supersedes=ann['id'],c=c)
        for row in restrictions:
            same,old=prior(row,'禁用表.jsonl')
            if same:continue
            ident=uid();level='秒段' if row.get('镜序素材ID') and row.get('起秒') is not None and row.get('止秒') is not None else '目录'
            c.execute('INSERT INTO restrictions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ident,level,row.get('镜序素材ID'),row.get('起秒'),row.get('止秒'),row.get('主库相对路径') if level=='目录' else None,row['禁用原文'],row.get('确认人'),row.get('来源文件'),1,dump(row),now())[:12])
            remember(row,'restriction',ident,old)
        report['review_status']=dict(statuses);report['segment_fact_count']=sum(x['destination']=='segment' for x in report['fact_destinations']);report['clue_fact_count']=len(facts)-report['segment_fact_count']
        assert report['segment_fact_count']+report['clue_fact_count']==len(facts)
        report['duration_unchecked']=c.execute('SELECT count(*) FROM ranges WHERE duration_unchecked=1').fetchone()[0]
        report['segment_negative_facts']=sum(x['negative'] and x['destination']=='segment' for x in report['fact_destinations'])
        if not existing:c.execute('INSERT INTO imports VALUES(?,?,?,?,?)',(batch,str(source),dump(hashes),dump(report),now()))
    report['table_counts']=store.counts();return report

def main():
    p=argparse.ArgumentParser(description=__doc__);root=Path(__file__).resolve().parent.parent
    p.add_argument('--source',type=Path,default=root/'参考资料/video-harness-lab-references/素材底座项目-20261116/片段库');p.add_argument('--state',type=Path,default=root/'local/cutframe');p.add_argument('--dry-run',action='store_true');p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    if a.dry_run:
        with tempfile.TemporaryDirectory(prefix='annotation-dry-') as folder:
            target=Path(folder)/'annotation.sqlite3';existing=a.state/'annotation.sqlite3'
            if existing.exists():
                with contextlib.closing(sqlite3.connect(existing.resolve().as_uri()+'?mode=ro',uri=True)) as source,contextlib.closing(sqlite3.connect(target)) as dest:source.backup(dest)
            report=import_library(Store(target),a.source,a.state/'catalog.sqlite3')
    else:report=import_library(Store(a.state/'annotation.sqlite3'),a.source,a.state/'catalog.sqlite3')
    report['dry_run']=a.dry_run;a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k in ('input_facts','segment_fact_count','clue_fact_count','table_counts','repeated')},ensure_ascii=False))
if __name__=='__main__':main()
