"""第四步文案入表、代表句标签修订及批次版本校验。"""
import hashlib
import json
from contextlib import closing

from flask import jsonify

import structured_entry
import structured_selection
from ai_store import connect
from selection_sources import active_source


def annotate_view(root, view, text):
    index, _ = structured_selection.dataset(root)
    ambiguous = view.get('alternatives_by_id') or []
    if ambiguous:
        ids = [item['id'] for item in ambiguous]
    elif view.get('entry_id'):
        ids = [view['entry_id']]
    else:
        ids = [row['观点ID'] for row in view.get('structured', [])]
        if view.get('id'):
            ids.insert(0, view['id'])
    view['annotation_targets'] = [
        {'id': ident, 'title': index[ident][0]['代表句']}
        for ident in dict.fromkeys(ids) if ident in index
    ]
    view['annotation_pending'] = not view['annotation_targets'] and structured_entry.pending_contains(root, text)
    # 相关代表句也参与检索。只在人工行的实际标签变化时刷新相应批次。
    related = dict.fromkeys(ids + [row['观点ID'] for row in view.get('structured', [])])
    fields = ('素材类别', '对应性质', '肯否', '主画面类型', '备选画面类型',
              '必须看见的动作', '禁用与限制', '标注状态', '类别条件编号')
    revisions = [(key, *[index[key][0].get(f, '') for f in fields])
                 for key in related if key in index and index[key][0]['标注状态'].startswith('人工')]
    view['annotation_revision'] = hashlib.sha256(json.dumps(revisions, ensure_ascii=False).encode()).hexdigest() if revisions else ''
    return view


def register(app, root, learning, lookup, body):
    def target(d, view):
        ident = d.get('id')
        if not ident or not any(row['id'] == ident for row in view['annotation_targets']):
            raise ValueError('代表句与当前字幕不对应，请重新对照后选择')
        return ident

    def reviewer(d):
        name = d.get('reviewer')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError('请填写审核人姓名或昵称（最多80字）')
        return name.strip()

    @app.post('/api/local/annotation-pending')
    def local_annotation_pending():
        d = body()
        with closing(connect(learning)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if lookup(d)['annotation_targets']:
                raise ValueError('已找到表内代表句，请走人工修订入口')
            created = structured_entry.enqueue_pending(root, d.get('text'), reviewer(d))
        return jsonify(created=created, message='已加入文案表「待标注」' if created else '这句已在文案表「待标注」中')

    @app.post('/api/local/annotation-edit')
    def local_annotation_edit():
        d = body()
        return jsonify(structured_entry.edit_draft(root, target(d, lookup(d))))

    @app.post('/api/local/annotation-revise')
    def local_annotation_revise():
        d = body()
        with closing(connect(learning)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            ident = target(d, lookup(d))
            structured_entry.revise(root, ident, d.get('version'), d.get('form'), reviewer(d),
                                    clean_book=active_source().clean_book)
            view = lookup(d)
        return jsonify(id=ident, view=view, message='已保存 '+ident+' 的人工修订')
