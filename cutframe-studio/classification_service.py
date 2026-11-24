"""对实看的原片秒段确认一个 B1 类型，沿用现有标注库和版本记录。"""
import json

from flask import jsonify, request

from annotation_store import dump


def register(app, env):
    store = app.extensions['annotation_store']
    tree = json.loads((env['BASE'] / 'rules/label-tree-v0.2.json').read_text('utf-8'))
    types = {item['id']: item['name'] for item in tree['labels']
             if item['dimension'] == '画面类型' and item['enabled'] and not item.get('group')}

    @app.get('/api/classification/types')
    def classification_types():
        return jsonify(items=[dict(id=code, name=name) for code, name in types.items()])

    @app.post('/api/classification/confirm')
    def classification_confirm():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get('watched') is not True:
            raise ValueError('请实看选定秒段后确认')
        for key in ('asset_id', 'type_id', 'reviewer', 'stage', 'note', 'evidence'):
            if not isinstance(data.get(key, ''), str):
                raise ValueError('原片、类型及审核说明须为文本')
        code = data.get('type_id', '')
        reviewer = data.get('reviewer', '').strip()
        if code not in types:
            raise ValueError('请选择一个 B1 画面类型或看不清')
        if not reviewer or len(reviewer) > 80:
            raise ValueError('请填写审核人，最多 80 字')
        stage = data.get('stage', '').strip()
        if stage not in ('', '旧状', '施工中', '完工', '看不清'):
            raise ValueError('阶段请按分类标注文档选择')
        note = data.get('note', '').strip()
        if code == 'V22' and not note:
            raise ValueError('选“其他”时请在备注里写出画面主体')
        evidence = dict(依据来源='本次实看', 画面依据=data.get('evidence', '').strip(),
                        阶段=stage, 备注=note)
        asset_id = data.get('asset_id', '')
        asset = env['get_asset'](asset_id)
        if env['CONFIG']['roots'].get(asset['root'], {}).get('role') != 'raw':
            raise ValueError('请从原片素材库选择原片')
        duration = env['metadata'](asset).get('duration')
        if duration is None:
            raise ValueError('取不到原片时长，无法确认秒段')
        with store.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # 全新标注库可能尚未导入规则包，只登记本次使用的现有词表项。
            conn.execute('INSERT OR IGNORE INTO label_registry(id,name,dimension) VALUES(?,?,?)',
                         (code, types[code], '画面类型'))
            store.validate_labels('画面类型', [code], conn)
            original = conn.execute('SELECT * FROM originals WHERE asset_id=?', (asset_id,)).fetchone()
            if original is None:
                store.original(asset_id, logical_path=asset['rel'], duration=duration, c=conn)
            elif original['duration'] != duration:
                store.original(asset_id, original['original_id'], original['annotation_id'],
                               original['logical_path'], duration, json.loads(original['raw']), conn)
            sid = store.create(asset_id, data.get('start'), data.get('end'), operator=reviewer, c=conn)
            previous = conn.execute("""
                SELECT a.* FROM annotations a JOIN segments s ON s.id=a.segment_id
                WHERE a.segment_id=? AND a.range_id=s.current_range AND a.dimension='画面类型'
                  AND a.source='人工' AND a.negative=0
                  AND NOT EXISTS (SELECT 1 FROM annotations newer WHERE newer.supersedes=a.id)
                ORDER BY a.rowid DESC LIMIT 1""", (sid,)).fetchone()
            unchanged = (previous and previous['labels'] == dump([code])
                         and previous['evidence'] == dump(evidence) and previous['reviewer'] == reviewer
                         and previous['review_status'] == '人工确认')
            if unchanged:
                aid = previous['id']
            else:
                aid = store.annotate(sid, dict(dimension='画面类型', labels=[code], source='人工',
                                     rule_version=tree['label_version'], reviewer=reviewer,
                                     review_status='人工确认', evidence=evidence),
                                     supersedes=previous['id'] if previous else None, c=conn)
        return jsonify(segment_id=sid, annotation_id=aid, review_status='人工确认')
