"""离线导入机器粗标，仅写独立片段库；不访问原片或模型。"""
import argparse,collections,contextlib,hashlib,json,re,sqlite3,tempfile
from pathlib import Path
from annotation_store import Store,dump,now

def ensure_schema(store):
    with store.db() as c:c.executescript('''
CREATE TABLE IF NOT EXISTS machine_descriptions(id INTEGER PRIMARY KEY,segment_id TEXT NOT NULL REFERENCES segments(id),text TEXT NOT NULL,record_kind TEXT NOT NULL,source_file TEXT NOT NULL,source_key TEXT NOT NULL,content_hash TEXT NOT NULL,source_jsonl TEXT NOT NULL,line_number INTEGER NOT NULL,version INTEGER NOT NULL,supersedes INTEGER REFERENCES machine_descriptions(id),created TEXT NOT NULL,UNIQUE(source_file,source_key,content_hash));
CREATE INDEX IF NOT EXISTS machine_description_segment ON machine_descriptions(segment_id);
CREATE INDEX IF NOT EXISTS machine_description_supersedes ON machine_descriptions(supersedes);
CREATE INDEX IF NOT EXISTS segments_asset ON segments(asset_id);
CREATE INDEX IF NOT EXISTS annotation_segment ON annotations(segment_id);
CREATE INDEX IF NOT EXISTS annotation_supersedes ON annotations(supersedes);
''')

def text_value(value):
    if value is None:return ''
    if isinstance(value,str):return value
    if isinstance(value,(list,dict)):return json.dumps(value,ensure_ascii=False)
    return str(value)

def description(row):
    raw=row.get('原字段') or {};kind=row.get('记录种类')
    keys=['description'] if kind=='分时段' else ['画面','镜头精确描述','工序','工序复核','材料类目'] if kind=='施工镜头' else ['category','action'] if kind=='用途片段' else []
    return '\n'.join(text_value(raw.get(k,row.get(k))).strip() for k in keys if text_value(raw.get(k,row.get(k))).strip())

def import_machine(store,source,catalog):
    ensure_schema(store);source=Path(source).resolve();skips=collections.Counter();kinds=collections.Counter();scopes=collections.Counter();directories=collections.Counter();report=dict(input_rows=0,imported_rows=0,unchanged_rows=0,type_annotations=0,material_annotations=0)
    with contextlib.closing(sqlite3.connect(Path(catalog).resolve().as_uri()+'?mode=ro',uri=True)) as c:assets={r[0] for r in c.execute('SELECT id FROM assets')}
    with store.db() as c,source.open(encoding='utf-8-sig') as f:
        for lineno,line in enumerate(f,1):
            if not line.strip():continue
            row=json.loads(line);report['input_rows']+=1;scopes[row.get('范围')]+=1;directories[row.get('目录')]+=1
            reason='';aid=row.get('镜序素材ID');start,end=row.get('起秒'),row.get('止秒')
            if row.get('范围')!='范围内':reason='范围外，本单不导'
            elif not aid:reason='没有镜序素材编号'
            elif aid not in assets:reason='镜序素材编号在assets中不存在'
            elif start is None or end is None:reason='起止秒不完整'
            else:
                try:store.interval(c,aid,start,end)
                except ValueError as e:reason=str(e)
            if reason:skips[reason]+=1;continue
            report['imported_rows']+=1;kinds[row.get('记录种类')]+=1
            source_file=row.get('来源文件') or source.name
            # 上游“来源条目标识”并非逐行唯一，粗标编号用于区分同一条目的多条投影。
            key=(str(row['粗标编号'])+'#' if row.get('粗标编号') else '')+str(row.get('来源条目标识') or lineno)
            digest=hashlib.sha256(dump(row).encode('utf-8')).hexdigest()
            old=c.execute('SELECT * FROM machine_descriptions WHERE source_file=? AND source_key=? ORDER BY version DESC LIMIT 1',(source_file,key)).fetchone()
            if old and old['content_hash']==digest:report['unchanged_rows']+=1;continue
            sid=store.create(aid,start,end,c=c);text=description(row)
            mid=c.execute('INSERT INTO machine_descriptions(segment_id,text,record_kind,source_file,source_key,content_hash,source_jsonl,line_number,version,supersedes,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sid,text,row.get('记录种类',''),source_file,key,digest,str(source),lineno,old['version']+1 if old else 1,old['id'] if old else None,now())).lastrowid
            labels={};codes=set(re.findall(r'(?<![A-Za-z0-9])V\d{2}(?!\d)',text_value(row.get('对应总纲标签'))))
            if len(codes)==1 and next(iter(codes)) in {f'V{i:02}' for i in range(1,25)}:labels['画面类型']=sorted(codes)
            if (row.get('原字段') or {}).get('可按微陶泥选用') is True:labels['材料类目']=['B7M01']
            previous={}
            if old:
                for a in c.execute("SELECT * FROM annotations a WHERE segment_id=? AND source='机器' AND NOT EXISTS(SELECT 1 FROM annotations n WHERE n.supersedes=a.id)",(sid,)):
                    ref=json.loads(a['raw'])
                    if ref.get('source_file')==source_file and ref.get('source_key')==key:previous[a['dimension']]=a['id']
            for dim in set(labels)|set(previous):
                store.annotate(sid,dict(dimension=dim,labels=labels.get(dim,[]),source='机器',review_status='未审',model_version=source.name,evidence=dict(description_id=mid,source_file=source_file,source_key=key,content_hash=digest),raw=dict(source_file=source_file,source_key=key,description_id=mid)),supersedes=previous.get(dim),c=c)
                if dim=='画面类型' and labels.get(dim):report['type_annotations']+=1
                if dim=='材料类目' and labels.get(dim):report['material_annotations']+=1
        store.event(c,'machine_import',source.name,'粗标导入',None,dict(report,skipped=dict(skips)),operator='粗标导入脚本') if report['imported_rows']>report['unchanged_rows'] else None
    report.update(skipped=dict(skips),scopes=dict(scopes),directories=dict(directories),record_kinds=dict(kinds),table_counts=store.counts(),source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    return report

def main():
    root=Path(__file__).resolve().parent.parent;p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=root/'参考资料/video-harness-lab-references/素材底座项目-20261116/片段库/粗标层.jsonl');p.add_argument('--state',type=Path,default=root/'local/cutframe');p.add_argument('--dry-run',action='store_true');p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    if a.dry_run:
        with tempfile.TemporaryDirectory(prefix='machine-dry-') as folder:
            target=Path(folder)/'annotation.sqlite3'
            if (a.state/'annotation.sqlite3').exists():
                with contextlib.closing(sqlite3.connect((a.state/'annotation.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as s,contextlib.closing(sqlite3.connect(target)) as d:s.backup(d)
            report=import_machine(Store(target),a.source,a.state/'catalog.sqlite3')
    else:report=import_machine(Store(a.state/'annotation.sqlite3'),a.source,a.state/'catalog.sqlite3')
    report['dry_run']=a.dry_run;a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
