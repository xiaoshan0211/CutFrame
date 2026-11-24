"""规则管理HTTP接口，写操作统一由主应用本地令牌保护。"""
import json
from flask import request,jsonify,Response
from annotation_rules import Rules,validate,stats

def register(app,env):
    store=app.extensions['annotation_store'];rules=Rules(store);app.extensions['annotation_rules']=rules
    def body():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise ValueError('请求必须为JSON对象')
        return data
    @app.get('/api/annotation/overview')
    def annotation_overview():
        with store.db() as c:
            batches=[dict(r) for r in c.execute('SELECT id,directory,hashes,counts,created FROM imports ORDER BY created DESC')]
            statuses={}
            for segment in c.execute('SELECT id FROM segments'):
                rows=[r[0] for r in c.execute('SELECT review_status FROM annotations a WHERE segment_id=? AND NOT EXISTS(SELECT 1 FROM annotations newer WHERE newer.supersedes=a.id)',(segment['id'],))]
                status=next((s for s in ('不可用','待确认','未审','人工改正','人工确认') if s in rows),'未审');statuses[status]=statuses.get(status,0)+1
        return jsonify(counts=store.counts(),segment_status=statuses,batches=batches)
    @app.get('/api/annotation/rules')
    def annotation_rules_list():return jsonify(items=rules.list())
    @app.post('/api/annotation/rules')
    def annotation_rules_import():
        d=body();return jsonify(rules.create(d.get('content'),d.get('name','导入草稿'),d.get('parent_id')))
    @app.get('/api/annotation/rules/<ident>')
    def annotation_rules_get(ident):return jsonify(rules.get(ident))
    @app.put('/api/annotation/rules/<ident>')
    def annotation_rules_save(ident):
        d=body();return jsonify(rules.save(ident,d.get('content'),d.get('expected_hash')))
    @app.get('/api/annotation/rules/<ident>/pending')
    def annotation_rules_pending(ident):return jsonify(items=rules.pending(ident))
    @app.post('/api/annotation/rules/<ident>/apply-same')
    def annotation_rules_apply_same(ident):
        d=body()
        if not isinstance(d.get('include_manual',False),bool):raise ValueError('覆盖人工行必须明确勾选')
        return jsonify(rules.apply_same(ident,d.get('rule_id'),d.get('group'),d.get('index'),d.get('include_manual',False),d.get('expected_hash')))
    @app.post('/api/annotation/rules/<ident>/validate')
    def annotation_rules_validate(ident):
        package=rules.get(ident);return jsonify(stats(package['content']))
    @app.post('/api/annotation/rules/<ident>/confirm')
    def annotation_rules_confirm(ident):
        d=body();return jsonify(rules.confirm(ident,d.get('reviewer'),d.get('expected_hash')))
    @app.post('/api/annotation/rules/<ident>/publish')
    def annotation_rules_publish(ident):
        package=rules.get(ident);issues=validate(package['content'])
        if issues:return jsonify(error='校验未通过',issues=issues),400
        return jsonify(rules.publish(ident))
    @app.get('/api/annotation/rules/<ident>/export')
    def annotation_rules_export(ident):
        package=rules.get(ident);return Response(json.dumps(package['content'],ensure_ascii=False,indent=2),mimetype='application/json',headers={'Content-Disposition':'attachment; filename="annotation-rules-'+ident+'.json"'})
    @app.post('/api/annotation/bindings')
    def annotation_bind():
        d=body();return jsonify(rules.bind(d.get('task_id'),d.get('package_id')))
    @app.get('/api/annotation/bindings/<path:task_id>')
    def annotation_bound(task_id):return jsonify(rules.bound(task_id))
