"""镜序分轮试标库：模型预测独立保存；人工确认后才写正式标签。"""
import json,hashlib,csv
from pathlib import Path
from annotation_store import Store,dump,uid,now

class Pilot:
    def __init__(self,store):
        self.store=store
        gold=Path(__file__).resolve().parent.parent/'参考资料/video-harness-lab-references/素材标注总纲-20261116/试标50段/审核结果.json'
        data=json.loads(gold.read_text('utf-8-sig'))['结果'] if gold.is_file() else []
        self.baseline={r['seg']:r['机器画面类型'] if r['verdict']=='对' else r['fix'] for r in data}
        with store.db() as c:c.executescript('''
CREATE TABLE IF NOT EXISTS pilot_rounds(id TEXT PRIMARY KEY,name TEXT NOT NULL,model TEXT NOT NULL,rule_version TEXT NOT NULL,source_hash TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pilot_items(id TEXT PRIMARY KEY,round_id TEXT NOT NULL REFERENCES pilot_rounds(id),sample_id TEXT NOT NULL,asset_id TEXT NOT NULL,start REAL NOT NULL,end REAL NOT NULL,frame_path TEXT NOT NULL,predicted_code TEXT,prediction TEXT NOT NULL,UNIQUE(round_id,sample_id));
CREATE TABLE IF NOT EXISTS pilot_reviews(id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES pilot_items(id),code TEXT NOT NULL,reviewer TEXT NOT NULL,blind INTEGER NOT NULL,annotation_id TEXT NOT NULL,created TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS pilot_reviews_no_update BEFORE UPDATE ON pilot_reviews BEGIN SELECT RAISE(ABORT,'试标审核只追加'); END;
CREATE TRIGGER IF NOT EXISTS pilot_reviews_no_delete BEFORE DELETE ON pilot_reviews BEGIN SELECT RAISE(ABORT,'试标审核只追加'); END;
''')
    def import_round(self,name,predictions,reference,manifest=None):
        records=[]
        for line in Path(predictions).read_text('utf-8').splitlines():
            row=json.loads(line)
            if row.get('code') and not row.get('error'):records.append(row)
        if not records:raise ValueError('尚无完成的模型预测')
        hashes={(r.get('prompt_sha256'),r.get('max_pixels'),r.get('model')) for r in records}
        if len(hashes)!=1:raise ValueError('同一轮不能混入不同模型或处理配置')
        latest={r['sample_id']:r for r in records};digest=hashlib.sha256(dump(latest).encode()).hexdigest();rid=hashlib.sha256((name+str(hashes)).encode()).hexdigest()[:24]
        facts=[json.loads(x) for x in (Path(reference)/'素材底座项目-20261116/片段库/事实层.jsonl').read_text('utf-8-sig').splitlines() if x.strip()]
        mapping={r['来源条目标识']:r for r in facts if r.get('样例类别')=='试标50段'}
        if manifest:
            mapping={r['sample_id']:dict(r,镜序素材ID=r['asset_id'],起秒=r['start'],止秒=r['end']) for r in (json.loads(x) for x in Path(manifest).read_text('utf-8').splitlines() if x.strip())}
        with self.store.db() as c:
            existing=c.execute('SELECT source_hash FROM pilot_rounds WHERE id=?',(rid,)).fetchone()
            if existing and existing['source_hash']!=digest:raise ValueError('该轮已冻结，请将新增预测作为新轮次导入')
            if existing:return rid
            first=records[0];c.execute('INSERT INTO pilot_rounds VALUES(?,?,?,?,?,?)',(rid,name,first['model'],first['rule_version'],digest,now()))
            for sample,row in sorted(latest.items()):
                source=mapping.get(sample)
                if not source or not source.get('镜序素材ID'):raise ValueError('样本无素材编号对照：'+sample)
                frame=Path(source['frame_path']) if manifest else Path(reference)/'素材标注总纲-20261116/试标50段/frames'/(sample+'.jpg')
                if not frame.is_file():raise ValueError('拼图缺失：'+sample)
                ident=rid+'-'+sample;c.execute('INSERT INTO pilot_items VALUES(?,?,?,?,?,?,?,?,?)',(ident,rid,sample,source['镜序素材ID'],source['起秒'],source['止秒'],str(frame.resolve()),row['code'],dump(dict(row,comparison_enabled=not bool(manifest)))))
            self.store.event(c,'pilot_round',rid,'导入试标轮次',None,dict(name=name,items=len(latest),source_hash=digest),'预测未审，不当成人工结论')
        return rid
    def rounds(self):
        with self.store.db() as c:return [dict(r) for r in c.execute('SELECT p.*,count(i.id) AS count FROM pilot_rounds p LEFT JOIN pilot_items i ON i.round_id=p.id GROUP BY p.id ORDER BY p.created DESC')]
    def item(self,ident,c=None):
        if c is None:
            with self.store.db() as db:return self.item(ident,db)
        r=c.execute('SELECT * FROM pilot_items WHERE id=?',(ident,)).fetchone()
        if not r:raise ValueError('试标片段不存在')
        result=dict(r);review=c.execute('SELECT * FROM pilot_reviews WHERE item_id=? ORDER BY rowid DESC LIMIT 1',(ident,)).fetchone();result['review']=dict(review) if review else None;result['code']=review['code'] if review else r['predicted_code'];result['old_review_code']=self.baseline.get(result['sample_id']) if json.loads(result['prediction']).get('comparison_enabled',True) else None;result['model_mismatch']=result['old_review_code'] is not None and result['predicted_code']!=result['old_review_code'];return result
    def items(self,rid,code='',q='',page=1,mismatches_only=False):
        with self.store.db() as c:
            result=[self.item(r['id'],c) for r in c.execute('SELECT id FROM pilot_items WHERE round_id=? ORDER BY sample_id',(rid,)).fetchall()]
            for row in result:
                original=c.execute('SELECT logical_path,raw FROM originals WHERE asset_id=?',(row['asset_id'],)).fetchone();row['name']=Path(original['logical_path'].replace('\\','/')).name if original else row['sample_id'];row['path']=original['logical_path'] if original else '';row['orientation']=json.loads(original['raw']).get('画幅') if original else None
        counts={}
        for row in result:counts[row['code']]=counts.get(row['code'],0)+1
        filtered=[r for r in result if (not code or r['code']==code) and (not mismatches_only or not any(x['old_review_code'] for x in result) or r['model_mismatch']) and (not q or q.lower() in (r['name']+' '+r['path']+' '+r['sample_id']).lower())];page=max(1,int(page));return dict(total=len(filtered),page=page,items=filtered[(page-1)*60:page*60],types=counts,round_total=len(result),mismatches=sum(r['model_mismatch'] for r in result),has_baseline=any(r['old_review_code'] for r in result),reviewed=sum(bool(r['review']) for r in result))
    def review(self,ident,code,reviewer,blind=False):
        if not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('请填写实际审核人')
        if not isinstance(blind,bool):raise ValueError('盲审标记必须为布尔值')
        label='B1U01' if code=='看不清' else code
        self.store.validate_labels('画面类型',[label])
        with self.store.db() as c:
            row=self.item(ident,c)
            if row['review'] and row['review']['code']==code and row['review']['reviewer']==reviewer:return row['review']['annotation_id']
            sid=self.store.create(row['asset_id'],row['start'],row['end'],operator=reviewer,allow_unknown=True,c=c);segment=self.store.get(sid,c)
            old=c.execute("SELECT a.id FROM annotations a WHERE segment_id=? AND range_id=? AND dimension='画面类型' AND source='人工' AND NOT EXISTS(SELECT 1 FROM annotations n WHERE n.supersedes=a.id) ORDER BY a.rowid DESC LIMIT 1",(sid,segment['current_range'])).fetchone()
            aid=self.store.annotate(sid,dict(dimension='画面类型',labels=[label],source='人工',review_status='人工确认' if code==row['predicted_code'] else '人工改正',reviewer=reviewer,rule_version='v0.2',evidence=dict(pilot_round=row['round_id'],sample_id=row['sample_id'],blind=blind,prediction=row['predicted_code']),raw=dict(pilot_item=ident)),supersedes=old['id'] if old else None,c=c)
            c.execute('INSERT INTO pilot_reviews VALUES(?,?,?,?,?,?,?)',(uid(),ident,code,reviewer,int(blind),aid,now()));self.store.event(c,'pilot_item',ident,'人工核对画面类型',row['review'],dict(code=code,annotation_id=aid,blind=blind),operator=reviewer);return aid

def register(app,env):
    from flask import request,jsonify,send_file
    pilot=Pilot(app.extensions['annotation_store']);app.extensions['pilot']=pilot
    @app.get('/api/pilot/rounds')
    def pilot_rounds():return jsonify(items=pilot.rounds())
    @app.get('/api/pilot/items')
    def pilot_items():return jsonify(pilot.items(request.args.get('round',''),request.args.get('code',''),request.args.get('q',''),request.args.get('page',1),request.args.get('mismatches')=='1'))
    @app.get('/api/pilot/frame/<ident>')
    def pilot_frame(ident):
        path=Path(pilot.item(ident)['frame_path']).resolve();allowed=(env['BASE'].parent/'参考资料/video-harness-lab-references/素材标注总纲-20261116/试标50段/frames').resolve()
        generated=(env['STATE']/'pilot/frames').resolve()
        if not (path.parent==allowed or path.is_relative_to(generated)) or path.suffix.lower()!='.jpg':raise ValueError('拼图不在本次样本范围')
        return send_file(path,conditional=True)
    @app.post('/api/pilot/review/<ident>')
    def pilot_review(ident):
        d=request.get_json(silent=True)
        if not isinstance(d,dict):raise ValueError('请求必须为JSON对象')
        return jsonify(id=pilot.review(ident,d.get('code'),d.get('reviewer'),d.get('blind',False)))
