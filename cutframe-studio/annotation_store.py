"""独立片段库：仅写 annotation.sqlite3，历史版本和审核事件不可覆盖。"""
import contextlib, sqlite3, json, uuid, math
from pathlib import Path
from datetime import datetime, timezone


def now(): return datetime.now(timezone.utc).isoformat()
def dump(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def uid(): return uuid.uuid4().hex

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS originals(asset_id TEXT PRIMARY KEY, original_id TEXT, annotation_id TEXT, logical_path TEXT, duration REAL, raw TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS segments(id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES originals(asset_id), status TEXT NOT NULL DEFAULT '有效', split_from TEXT REFERENCES segments(id), current_range INTEGER, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ranges(id INTEGER PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segments(id), version INTEGER NOT NULL, start REAL NOT NULL CHECK(start>=0), end REAL NOT NULL CHECK(end>start), duration_unchecked INTEGER NOT NULL, created TEXT NOT NULL, UNIQUE(segment_id,version));
CREATE INDEX IF NOT EXISTS ranges_lookup ON ranges(segment_id,start,end);
CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segments(id), range_id INTEGER NOT NULL REFERENCES ranges(id), version INTEGER NOT NULL, supersedes TEXT REFERENCES annotations(id), dimension TEXT, labels TEXT NOT NULL, negative INTEGER NOT NULL, source TEXT NOT NULL, rule_version TEXT, model_version TEXT, evidence TEXT NOT NULL, review_status TEXT NOT NULL CHECK(review_status IN ('未审','人工确认','人工改正','待确认','不可用')), reviewer TEXT, flags TEXT NOT NULL, raw TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS restrictions(id TEXT PRIMARY KEY, level TEXT NOT NULL CHECK(level IN ('原片','秒段','目录')), asset_id TEXT, start REAL, end REAL, directory TEXT, text TEXT NOT NULL, reviewer TEXT, source TEXT, active INTEGER NOT NULL, raw TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clues(id TEXT PRIMARY KEY, reason TEXT NOT NULL, raw TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, object_type TEXT NOT NULL, object_id TEXT NOT NULL, action TEXT NOT NULL, before_value TEXT, after_value TEXT, reason TEXT NOT NULL, operator TEXT NOT NULL, created TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'审核事件只追加'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'审核事件只追加'); END;
CREATE TRIGGER IF NOT EXISTS ranges_no_update BEFORE UPDATE ON ranges BEGIN SELECT RAISE(ABORT,'区间版本不可修改'); END;
CREATE TRIGGER IF NOT EXISTS ranges_no_delete BEFORE DELETE ON ranges BEGIN SELECT RAISE(ABORT,'区间版本不可删除'); END;
CREATE TRIGGER IF NOT EXISTS annotations_no_update BEFORE UPDATE ON annotations BEGIN SELECT RAISE(ABORT,'标注版本不可修改'); END;
CREATE TRIGGER IF NOT EXISTS annotations_no_delete BEFORE DELETE ON annotations BEGIN SELECT RAISE(ABORT,'标注版本不可删除'); END;
CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, directory TEXT NOT NULL, hashes TEXT NOT NULL, counts TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_records(id INTEGER PRIMARY KEY, source_file TEXT NOT NULL, source_key TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL, destination TEXT NOT NULL, object_id TEXT NOT NULL, raw TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(source_file,source_key,content_hash));
''')
    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path, timeout=30);c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()
    def event(self,c,kind,ident,action,before,after,reason='',operator='本机操作人'):
        c.execute('INSERT INTO events(object_type,object_id,action,before_value,after_value,reason,operator,created) VALUES(?,?,?,?,?,?,?,?)',(kind,str(ident),action,dump(before) if before is not None else None,dump(after) if after is not None else None,reason,operator,now()))
    def original(self,asset_id,original_id=None,annotation_id=None,logical_path='',duration=None,raw=None,c=None):
        if not asset_id: raise ValueError('镜序素材编号必填')
        if duration is not None and (isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0): raise ValueError('原片时长必须为正数')
        if c is None:
            with self.db() as db: return self.original(asset_id,original_id,annotation_id,logical_path,duration,raw,db)
        values=(asset_id,original_id,annotation_id,logical_path,duration,dump(raw or {}))
        old=c.execute('SELECT * FROM originals WHERE asset_id=?',(asset_id,)).fetchone()
        if not old: c.execute('INSERT INTO originals VALUES(?,?,?,?,?,?)',values)
        elif tuple(old)!=values:
            c.execute('UPDATE originals SET original_id=?,annotation_id=?,logical_path=?,duration=?,raw=? WHERE asset_id=?',values[1:]+values[:1]);self.event(c,'original',asset_id,'更新对照',dict(old),dict(zip(old.keys(),values)))
        return asset_id
    def interval(self,c,asset_id,start,end,allow_unknown=False):
        for v in (start,end):
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v): raise ValueError('起止秒必须为有限数字')
        if start<0: raise ValueError('起秒不能为负')
        if end<=start: raise ValueError('止秒必须大于起秒')
        original=c.execute('SELECT * FROM originals WHERE asset_id=?',(asset_id,)).fetchone()
        if not original: raise ValueError('原片未登记')
        duration=original['duration']
        if duration is None and not allow_unknown: raise ValueError('取不到原片时长，拒绝保存')
        if duration is not None and end-duration>0.001+1e-9: raise ValueError('止秒超过原片时长')
        return duration is None
    def create(self,asset_id,start,end,operator='本机操作人',split_from=None,allow_unknown=False,c=None):
        if c is None:
            with self.db() as db: return self.create(asset_id,start,end,operator,split_from,allow_unknown,db)
        unchecked=self.interval(c,asset_id,start,end,allow_unknown)
        existing=c.execute("SELECT s.id FROM segments s JOIN ranges r ON r.id=s.current_range WHERE s.asset_id=? AND r.start=? AND r.end=? AND s.status='有效' AND s.split_from IS ?",(asset_id,start,end,split_from)).fetchone()
        if existing:return existing['id']
        ident=uid();c.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',(ident,asset_id,'有效',split_from,None,now()))
        rid=c.execute('INSERT INTO ranges(segment_id,version,start,end,duration_unchecked,created) VALUES(?,?,?,?,?,?)',(ident,1,start,end,int(unchecked),now())).lastrowid
        c.execute('UPDATE segments SET current_range=? WHERE id=?',(rid,ident));self.event(c,'segment',ident,'新建',None,dict(asset_id=asset_id,start=start,end=end,range_id=rid),operator=operator)
        return ident
    def get(self,ident,c=None):
        if c is None:
            with self.db() as db: return self.get(ident,db)
        row=c.execute('SELECT * FROM segments WHERE id=?',(ident,)).fetchone()
        if not row: raise ValueError('片段不存在')
        result=dict(row)
        result['ranges']=[dict(r) for r in c.execute('SELECT * FROM ranges WHERE segment_id=? ORDER BY version',(ident,))]
        result['annotations']=[dict(r) for r in c.execute('SELECT * FROM annotations WHERE segment_id=? ORDER BY created,rowid',(ident,))]
        return result
    def list(self,asset_id):
        with self.db() as c:return [self.get(r['id'],c) for r in c.execute('SELECT id FROM segments WHERE asset_id=? ORDER BY created,id',(asset_id,)).fetchall()]
    def change_range(self,ident,start,end,reason='',operator='本机操作人'):
        with self.db() as c:
            before=self.get(ident,c)
            if before['status']=='废弃':raise ValueError('已废弃片段不能改秒段')
            unchecked=self.interval(c,before['asset_id'],start,end)
            version=before['ranges'][-1]['version']+1
            rid=c.execute('INSERT INTO ranges(segment_id,version,start,end,duration_unchecked,created) VALUES(?,?,?,?,?,?)',(ident,version,start,end,int(unchecked),now())).lastrowid
            c.execute('UPDATE segments SET current_range=? WHERE id=?',(rid,ident));after=self.get(ident,c);self.event(c,'segment',ident,'改秒段',before,after,reason,operator);return after
    def retire(self,ident,reason='',operator='本机操作人',c=None):
        if c is None:
            with self.db() as db:return self.retire(ident,reason,operator,db)
        before=self.get(ident,c);c.execute("UPDATE segments SET status='废弃' WHERE id=?",(ident,));self.event(c,'segment',ident,'废弃',before,self.get(ident,c),reason,operator)
        return self.get(ident,c)
    def split(self,ident,intervals,reason='',operator='本机操作人'):
        if not isinstance(intervals,list) or len(intervals)<2:raise ValueError('拆段至少需要两个区间')
        with self.db() as c:
            original=self.get(ident,c);active=next(r for r in original['ranges'] if r['id']==original['current_range']);children=[]
            for interval in intervals:
                if not isinstance(interval,dict):raise ValueError('拆段区间格式错误')
                a,b=interval.get('start'),interval.get('end');self.interval(c,original['asset_id'],a,b)
                if a<active['start'] or b>active['end']: raise ValueError('拆段超出来源区间')
                children.append(self.create(original['asset_id'],a,b,operator,ident,c=c))
            if len(set(children))!=len(children):raise ValueError('拆段区间重复')
            self.retire(ident,reason,operator,c);self.event(c,'segment',ident,'拆段',original,children,reason,operator)
            return [self.get(x,c) for x in children]
    def validate_labels(self,dimension,labels,c=None):
        if c is None:
            with self.db() as db:return self.validate_labels(dimension,labels,db)
        if not dimension and not labels:return
        if not isinstance(labels,list) or any(not isinstance(x,str) for x in labels):raise ValueError('标签必须为字符串数组')
        # 分组属性保存在版本内容中；登记表负责稳定编号及所属维度。
        packages=c.execute('SELECT content FROM rule_packages ORDER BY created DESC,rowid DESC').fetchall() if c.execute("SELECT 1 FROM sqlite_master WHERE name='rule_packages'").fetchone() else []
        trees=[json.loads(p[0]).get('label_tree',{}) for p in packages]
        if not trees:trees=[json.loads((Path(__file__).parent/'rules/label-tree-v0.2.json').read_text('utf-8'))]
        dims={d['id'] for t in trees for d in t.get('dimensions',[])+t.get('attributes',[])}
        if dimension not in dims:raise ValueError('维度不存在：'+str(dimension))
        known={}
        for t in reversed(trees):known.update({x['id']:x for x in t.get('labels',[])})
        for label in labels:
            registered=c.execute('SELECT dimension FROM label_registry WHERE id=?',(label,)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='label_registry'").fetchone() else None
            if not registered:raise ValueError('标签未在登记表中存在：'+label)
            if registered['dimension']!=dimension:raise ValueError('标签不属于该维度：'+label)
            if known.get(label,{}).get('group'):raise ValueError('分组不能当标签使用：'+label)
        if not labels:raise ValueError('维度标签不能为空')
    def annotate(self,ident,data,supersedes=None,c=None,import_update=False):
        if c is None:
            with self.db() as db:return self.annotate(ident,data,supersedes,db,import_update)
        segment=self.get(ident,c);rid=data.get('range_id',segment['current_range'])
        if segment['status']=='废弃' and not import_update:raise ValueError('已废弃片段不能加标注或改标注')
        if not any(r['id']==rid for r in segment['ranges']):raise ValueError('区间版本不属于片段')
        old=None
        if supersedes:
            old=c.execute('SELECT * FROM annotations WHERE id=? AND segment_id=?',(supersedes,ident)).fetchone()
            if not old:raise ValueError('旧标注不存在或不属于片段')
        status=data.get('review_status','未审')
        if status not in ('未审','人工确认','人工改正','待确认','不可用'):raise ValueError('审核状态无效')
        source=data.get('source','人工')
        if source not in ('目录','机器','人工'):raise ValueError('标注来源无效')
        labels=data.get('labels',[])
        if not isinstance(labels,list) or any(not isinstance(v,str) for v in labels):raise ValueError('标签必须为字符串数组')
        negative=data.get('negative',False)
        if not isinstance(negative,bool):raise ValueError('反例字段必须为布尔值')
        aid=uid();c.execute('INSERT INTO annotations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,ident,rid,old['version']+1 if old else 1,supersedes,data.get('dimension'),dump(labels),int(negative),source,data.get('rule_version'),data.get('model_version'),dump(data.get('evidence','')),status,data.get('reviewer',''),dump(data.get('flags',[])),dump(data.get('raw',data)),now()))
        # INSERT 字段数保持与独立表一致。
        after=dict(c.execute('SELECT * FROM annotations WHERE id=?',(aid,)).fetchone());self.event(c,'annotation',aid,'改标' if old else '加标注',dict(old) if old else None,after,data.get('reason',''),data.get('reviewer') or '本机操作人');return aid
    def counts(self):
        with self.db() as c:return {r['name']:c.execute('SELECT count(*) FROM "'+r['name']+'"').fetchone()[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
