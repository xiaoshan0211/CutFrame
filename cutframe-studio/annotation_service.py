"""逻辑片段接口；沿用 app 的同源与 X-Local-Token 校验。"""
from flask import request,jsonify
from annotation_store import Store

def register(app,env):
    store=Store(env['STATE']/'annotation.sqlite3')
    app.extensions['annotation_store']=store
    def payload():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise ValueError('请求必须为JSON对象')
        return data
    def duration(asset_id):
        asset=env['get_asset'](asset_id)
        with store.db() as c:
            row=c.execute('SELECT duration FROM originals WHERE asset_id=?',(asset_id,)).fetchone()
        if row and row['duration'] is not None:return asset,row['duration']
        try:value=env['metadata'](asset).get('duration')
        except Exception as e:raise ValueError('取不到原片时长，拒绝保存') from e
        if value is None:raise ValueError('取不到原片时长，拒绝保存')
        return asset,value
    @app.get('/api/annotation/segments')
    def annotation_list():return jsonify(items=store.list(request.args.get('asset_id','')))
    @app.get('/api/annotation/segments/<ident>')
    def annotation_get(ident):return jsonify(store.get(ident))
    @app.post('/api/annotation/segments')
    def annotation_create():
        d=payload();asset_id=d.get('asset_id');asset,seconds=duration(asset_id)
        with store.db() as c:
            row=c.execute('SELECT * FROM originals WHERE asset_id=?',(asset_id,)).fetchone()
            store.original(asset_id,row['original_id'] if row else None,row['annotation_id'] if row else None,row['logical_path'] if row else asset['rel'],seconds,__import__('json').loads(row['raw']) if row else {},c)
            ident=store.create(asset_id,d.get('start'),d.get('end'),d.get('operator','本机操作人'),c=c)
        return jsonify(store.get(ident))
    @app.post('/api/annotation/segments/<ident>/range')
    def annotation_range(ident):
        d=payload();return jsonify(store.change_range(ident,d.get('start'),d.get('end'),d.get('reason',''),d.get('operator','本机操作人')))
    @app.post('/api/annotation/segments/<ident>/split')
    def annotation_split(ident):
        d=payload();return jsonify(items=store.split(ident,d.get('intervals'),d.get('reason',''),d.get('operator','本机操作人')))
    @app.post('/api/annotation/segments/<ident>/retire')
    def annotation_retire(ident):
        d=payload();return jsonify(store.retire(ident,d.get('reason',''),d.get('operator','本机操作人')))
    @app.post('/api/annotation/segments/<ident>/annotations')
    def annotation_add(ident):
        d=payload();store.validate_labels(d.get('dimension'),d.get('labels',[]));return jsonify(id=store.annotate(ident,d))
    @app.post('/api/annotation/segments/<ident>/annotations/<aid>')
    def annotation_edit(ident,aid):
        d=payload();store.validate_labels(d.get('dimension'),d.get('labels',[]));return jsonify(id=store.annotate(ident,d,supersedes=aid))
