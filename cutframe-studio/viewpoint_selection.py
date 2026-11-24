"""按本地文档查 500 条素材；每句的人工评分保存在该句的 Markdown 记录。"""
import csv
import hashlib
import html
import io
import json
import os
import re
import subprocess
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from flask import abort, jsonify, request, send_file

from local_selection import SIMILARITY_THRESHOLD, similarity
from media import FLAGS


RATINGS = ('合适', '不合适', '勉强')
NEW_PURPOSE = '新增观点'
API = '/api/viewpoint-selection'
TABLE_HEADER = '| 候选编号 | 画面类型 | 可见动作 | 原片路径 | 起秒 | 止秒 | 评分 | 备注 | 依据来源 | 画面依据 |'


def clip_id(path, start, end):
    key = f'{path.casefold()}\0{float(start)!r}\0{float(end)!r}'
    return hashlib.sha256(key.encode()).hexdigest()


def catalog(library):
    with (library / '500条素材路径总表.csv').open(encoding='utf-8-sig', newline='') as source:
        items = {}
        for row in csv.DictReader(source):
            path, start, end = (row[key] for key in ('原片路径', '入点秒', '出点秒'))
            ident = clip_id(path, start, end)
            items[ident] = dict(id=ident, type=row['画面类型'], type_name=row['类型名称'],
                                path=path, start=float(start), end=float(end), source=row['依据来源'],
                                evidence=row['画面依据'], media_url=f'{API}/media/{ident}',
                                media_preview_url=f'{API}/preview/{ident}')
    return items


def cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def purposes(library):
    rows = []
    document = (library / '新素材分类标注_观点或用途.md').read_text('utf-8-sig')
    table = document.split('| 观点或用途 | 对应性质 | 先找的画面类型 | 实看核对 | 不能当主画面 |', 1)[1]
    for line in table.strip().splitlines()[1:]:
        if not line.startswith('|'):
            break
        name, nature, lookup, check, avoid = cells(line)
        codes = list(dict.fromkeys(re.findall(r'V\d{2}', lookup)))
        # 文档中这几个动作没有重复写编号，补的是同表已经指明的类型。
        for literal, code in (('握手沟通', 'V02'), ('搬离', 'V03'), ('拆砸', 'V08'), ('手工批刮', 'V05')):
            if literal in lookup and code not in codes:
                codes.append(code)
        rows.append(dict(name=name, nature=nature, lookup=lookup, check=check, avoid=avoid, types=codes))
    rows.append(dict(name=NEW_PURPOSE, nature='', lookup='', check='', avoid='', types=[]))
    return rows


def required_text(data, key, label, optional=False):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label}应为单行文字')
    value = value.strip()
    if not optional and not value:
        raise ValueError(f'请填写{label}')
    return value


# 文档中肯否相反的成对观点，其余行由原句和选镜意图说明。
OPPOSITES = {
    '不拆不砸、省了拆除': '以前敲砖、传统翻新要砸',
    '不用搬家、边住边改': '还得搬出去、住酒店',
    '不扰民、没有灰尘': '灰尘满天飞、噪音大',
}


def legacy_purposes(sentence):
    # 旧记录没有用途栏时，只归入有明确措辞依据的表行。
    cues = {'不用搬家、边住边改': ('不搬家', '不用搬家', '边住边'),
            '开场、提问、转折、吸引注意': ('刷到',),
            '不拆不砸、省了拆除': ('不拆不砸',)}
    return {name for name, words in cues.items() if any(w in sentence for w in words)}


def selection_fields(data, rules):
    if not isinstance(data, dict):
        raise ValueError('请求必须是 JSON 对象')
    result = {k: required_text(data, k, label) for k, label in
              [('sentence', '原句'), ('intent', '选镜意图'), ('purpose', '观点或用途'), ('polarity', '肯定或否定')]}
    if result['polarity'] not in ('肯定', '否定') or result['purpose'] not in rules:
        raise ValueError('请选择文档中的观点或用途和肯否')
    purpose = result['purpose']
    for negative, positive in OPPOSITES.items():
        if (purpose == negative and result['polarity'] == '肯定') or (purpose == positive and result['polarity'] == '否定'):
            other = positive if purpose == negative else negative
            raise ValueError(f'观点与肯否冲突。保留当前肯否时，请选观点表的「{other}」行；保留「{purpose}」时请更改肯否。')
    return result


def parse_record(text, reason_in_notes=False):
    """同时读取早期八列和新十列候选表，跳过独立的分类依据表。"""
    sentence = ''
    purpose = ''
    is_table = False
    for line in text.splitlines():
        match = re.match(r'^(?:\*\*)?原句(?:\*\*)?[：:]\s*(.+)', line)
        if match:
            sentence = html.unescape(match[1]).strip()
            purpose = ''
        if line.startswith('观点或用途：'):
            purpose = html.unescape(line.split('：', 1)[1])
        if not line.startswith('|'):
            is_table = False
            continue
        row = cells(line)
        if row[:2] == ['候选编号', '画面类型']:
            is_table = row[3:8] == ['原片路径', '起秒', '止秒', '评分', '备注']
            continue
        if is_table and sentence and len(row) >= 8 and row[6] in RATINGS:
            try:
                start, end = float(row[4]), float(row[5])
            except ValueError:
                continue
            note = html.unescape(row[7])
            original_note, separator, metadata = note.partition('〔选片评分〕')
            reason = note if reason_in_notes else ''
            row_purpose = purpose
            if separator:
                saved = json.loads(metadata)
                row_purpose, reason = saved['purpose'], saved['reason']
            yield dict(purpose=row_purpose, sentence=sentence, type=row[1], action=html.unescape(row[2]), path=html.unescape(row[3]), start=start,
                       end=end, rating=row[6], reason=reason,
                       note='' if reason_in_notes else original_note)


def six_sentence_history(library):
    summary = library / '六句文案_已审镜头汇总.md'
    if not summary.is_file():
        return
    sentence = ''
    for line in summary.read_text('utf-8-sig').splitlines():
        if line.startswith('## '):
            sentence = re.sub(r'^## \d+\s+', '', line)
        if not sentence or not line.startswith('| 第'):
            continue
        _, score, description, source = cells(line)
        rating = next((r for r in RATINGS if score.startswith(r)), None)
        if not rating:
            continue
        matches = re.finditer(r'(?:(V\d{2})\s+)?([A-Za-z]:\\.+?)（([\d.]+)–([\d.]+)\s*秒）', source)
        segments = [dict(type=m[1] or '', path=m[2], start=float(m[3]), end=float(m[4])) for m in matches]
        if not segments:
            continue
        reason = re.search(r'用户反馈[：:]([^）]+)', score)
        row = dict(sentence=sentence, rating=rating, reason=reason[1] if reason else '')
        if len(segments) == 1:
            row.update(segments[0])
            code = re.search(r'V\d{2}', description)
            if code:
                row['type'] = code[0]
        else:
            row['segments'] = segments  # 整组的历史分不分摊给任一原片。
        yield row


def previous_reviews(library, sentence, purpose):
    found = {}
    def collect(rows):
        for row in rows:
            previous = row['sentence']
            match = similarity(sentence, previous)
            same = previous == sentence
            same_use = (row.get('purpose') == purpose if row.get('purpose') else purpose in legacy_purposes(previous))
            if same or same_use or match >= SIMILARITY_THRESHOLD:
                key = previous, tuple(clip_id(s['path'], s['start'], s['end']) for s in row.get('segments', [row]))
                found[key] = dict(row, similarity=match, relation="同一句" if same else "同一观点（不同原句）" if same_use else "字面相似")
    collect(six_sentence_history(library))
    records = list(library.glob('*/选片记录.md'))
    # 本入口写出的逐句记录在旧试选记录之后读；同一键只展示最新评分。
    records.sort(key=lambda p: (not bool(re.search(r'_[0-9a-f]{16}$', p.parent.name)), str(p)))
    for path in records:
        current_format = bool(re.search(r'_[0-9a-f]{16}$', path.parent.name))
        collect(parse_record(path.read_text('utf-8-sig'), reason_in_notes=current_format))
    return sorted(found.values(), key=lambda row: -row['similarity'])


@contextmanager
def review_lock(library):
    """跨线程和进程串行化逐句文件的创建和替换，其他文档继续只读。"""
    name = hashlib.sha256(os.path.normcase(str(library.resolve())).encode()).hexdigest()
    with (Path(tempfile.gettempdir()) / f'jingxu-selection-{name}.lock').open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield  # 关闭文件时释放本次锁。


def escape_cell(value):
    return html.escape(str(value), quote=False).replace('|', '&#124;')


def save_review(library, fields, item, rating, reason, action):
    sentence = fields['sentence']
    name = re.sub(r'[^\w\u4e00-\u9fff-]', '_', sentence)[:20]
    suffix = hashlib.sha256(sentence.encode()).hexdigest()[:16]
    row = [item['id'], item['type'], action, item['path'], item['start'], item['end'],
           rating, reason, item['source'], item['evidence']]
    with review_lock(library):
        heading = re.compile(r'^(?:\*\*)?原句(?:\*\*)?[：:]\s*(.+)')
        matches = []
        existing_sentence = False
        for file in library.glob('*/选片记录.md'):
            lines = file.read_bytes().decode('utf8').splitlines(keepends=True)
            for index, line in enumerate(lines):
                m = heading.match(line)
                if not m or html.unescape(m[1]).strip() != sentence:
                    continue
                existing_sentence = True
                stop = next((j for j in range(index+1,len(lines)) if heading.match(lines[j]) or lines[j].startswith('## ')), len(lines))
                for j in range(index+1,stop):
                    if not lines[j].startswith('| 候选编号 | 画面类型 |'):
                        continue
                    end = j+2
                    while end < stop and lines[end].startswith('|'):
                        end += 1
                    hit = next((k for k in range(j+2,end) if clip_id(html.unescape(cells(lines[k])[3]),*cells(lines[k])[4:6]) == item['id']), None)
                    matches.append((bool(re.search(r'_[0-9a-f]{16}$',file.parent.name)), hit is None,str(file),file,lines,j,end,hit))
        if matches:
            _,_,_,record,lines,j,end,hit = min(matches,key=lambda m:m[:3])
        else:
            if existing_sentence:
                raise ValueError('找到了该原句的旧记录，但缺少可写的单镜头候选表，请核对原记录。')
            folder = library / f'{date.today().isoformat()}_{name}'
            if folder.exists():
                folder = folder.with_name(folder.name + '_' + suffix)
            folder.mkdir(exist_ok=False)
            record = folder / '选片记录.md'
            lines = [f'# {escape_cell(sentence)}\n\n',f'原句：{escape_cell(sentence)}\n',f'观点或用途：{escape_cell(fields["purpose"])}\n',f'肯定或否定：{fields["polarity"]}\n',f'选镜意图：{escape_cell(fields["intent"])}\n\n',TABLE_HEADER+'\n','|---|---|---|---|---:|---:|---|---|---|---|\n']
            j,end,hit = len(lines)-2,len(lines),None
        newline = '\r\n' if lines[j].endswith('\r\n') else '\n'
        values = cells(lines[hit]) if hit is not None else list(map(escape_cell,row[:len(cells(lines[j]))]))
        old_note = values[7].partition('〔选片评分〕')[0] if hit is not None else ''
        values[6:8] = [rating, old_note + '〔选片评分〕' + escape_cell(json.dumps(dict(purpose=fields['purpose'],reason=reason),ensure_ascii=False))]
        updated = '| ' + ' | '.join(values) + ' |' + newline
        if hit is None:
            lines.insert(end,updated)
            if len(values)==8:
                basis = next((k for k in range(end+1,len(lines)) if lines[k].startswith('| 候选编号 | 依据来源 |')),None)
                if basis is not None and not any(heading.match(x) for x in lines[end+1:basis]):
                    lines.insert(basis+2,'| '+' | '.join(map(escape_cell,[item['id'],item['source'],item['evidence']]))+' |'+newline)
        else:
            lines[hit] = updated
        temp = record.with_suffix('.tmp')
        temp.write_bytes(''.join(lines).encode('utf8'))
        location = str(record)
        os.replace(temp, record)
        return location


def register(app, library, ffmpeg):
    library = Path(library)
    preview_slots = threading.BoundedSemaphore(2)

    @app.get(API + '/options')
    def viewpoint_options():
        items = list(catalog(library).values())
        counts = Counter((item['type'], item['type_name']) for item in items)
        return jsonify(purposes=purposes(library),
                       types=[dict(code=k, name=n, count=count) for (k, n), count in counts.items()])

    @app.post(API + '/search')
    def viewpoint_search():
        data = request.get_json(silent=True)
        rules = {r['name']: r for r in purposes(library)}
        fields = selection_fields(data, rules)
        types = data.get('types', rules[fields['purpose']]['types'])
        items = list(catalog(library).values())
        known = {i['type'] for i in items}
        if not isinstance(types, list) or any(not isinstance(c, str) or c not in known for c in types):
            raise ValueError('画面类型必须选自总表')
        if fields['purpose'] != NEW_PURPOSE:
            types = [t for t in rules[fields['purpose']]['types'] if t in types]
        items = [i for i in items if i['type'] in types]
        # 按类型分组；同类先给人工已审、再给抽帧核对和未人工复审。
        items.sort(key=lambda i: (i['source'].startswith('既有'),
                                  i['source'] == '本轮抽帧核对', types.index(i['type'])))
        offset = data.get('offset', 0)
        if type(offset) is not int or offset < 0:
            raise ValueError('无效批次')
        return jsonify(items=items[offset:offset+6], total=len(items), types=types,
                       history=previous_reviews(library, fields['sentence'], fields['purpose']))

    def media_item(ident):
        item = catalog(library).get(ident)
        if item is None:
            abort(404)
        media_path = Path(item['path'])
        if not media_path.is_absolute():
            examples = (library.parent / 'examples').resolve()
            media_path = (library.parent / media_path).resolve()
            if not media_path.is_relative_to(examples):
                abort(404)
        if not media_path.is_file():
            abort(404, description='原片暂不可读，请检查共享盘连接')
        return {**item, 'path': str(media_path)}

    @app.get(API + '/media/<ident>')
    def viewpoint_media(ident):
        return send_file(media_item(ident)['path'], conditional=True)

    @app.get(API + '/preview/<ident>')
    def viewpoint_preview(ident):
        item = media_item(ident)
        if not preview_slots.acquire(blocking=False):
            abort(503, description='本机预览正在使用中，请稍后重试')
        try:
            command = [str(ffmpeg), '-nostdin', '-v', 'error', '-ss', str(item['start']),
                       '-i', item['path'], '-t', str(item['end'] - item['start']),
                       '-map', '0:v:0', '-map', '0:a:0?', '-vf',
                       'scale=960:960:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1',
                       '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8',
                       '-b:v', '1800k', '-pix_fmt', 'yuv420p', '-c:a', 'libopus', '-f', 'webm', 'pipe:1']
            result = subprocess.run(command, capture_output=True, timeout=90, creationflags=FLAGS)
            if result.returncode or not result.stdout:
                raise ValueError('无法生成此秒段的兼容预览')
            return send_file(io.BytesIO(result.stdout), mimetype='video/webm', conditional=True)
        finally:
            preview_slots.release()

    @app.post(API + '/rating')
    def viewpoint_rating():
        data = request.get_json(silent=True)
        rules = {r['name']: r for r in purposes(library)}
        fields = selection_fields(data, rules)
        rating = required_text(data, 'rating', '评分')
        if rating not in RATINGS:
            raise ValueError('评分只允许合适、不合适或勉强')
        item = catalog(library).get(required_text(data, 'id', '候选编号'))
        if not item:
            raise ValueError('该候选不在素材路径总表中')
        path = save_review(library, fields, item, rating, required_text(data, 'reason', '评分理由'),
                    required_text(data, 'action', '可见动作', optional=True))
        return jsonify(saved=True, path=path)
