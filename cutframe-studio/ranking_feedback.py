"""从本机有效审核重建训练合同；导出与训练可以分别执行。"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from selection_ranker import DATA, DIRECTORY, INFO, LEGACY, MIN_PAIRS, MODEL, candidate_snapshot, serialize, train, write_bytes

MATCH_CODES = {'动作没发生', '阶段不对', '动作做反了'}
EXCLUDE = {'同条重复', '没看连续画面', '晃动、失焦、拖影', '横屏或清晰度不够',
           '自带字幕、贴纸、水印、界面、二维码、品牌字、手写编号'}


@contextmanager
def build_lock(directory):
    """服务和命令行共用本机锁；进程退出后系统释放锁。"""
    key = hashlib.sha256(str(Path(directory).resolve()).casefold().encode()).hexdigest()
    path = Path(tempfile.gettempdir()) / ('cutframe-rank-' + key + '.lock')
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except PermissionError:
                    time.sleep(0.1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


def contract_rows(run_id, payload, result, reviews):
    latest, gaps = {}, []
    for review in reviews:
        if review['status'] != '已确认':
            continue
        if review.get('slot'):
            latest[review['slot']] = review
        else:
            gaps.append(review)
    need = (payload.get('need') or '').strip()
    text, task = payload['text'], payload['task_id']
    common = {'分组键': '|'.join((task, text, need)), '项目': payload['project_id'],
              '任务': task, '文案': text, '画面要求': need, '来源运行编号': run_id,
              '推荐时模型版本': result.get('rank_version', LEGACY)}
    items = {c['slot']: (c,i) for i,c in enumerate(result['items'], 1)}
    winners = [r for r in latest.values() if r['verdict'] == '采用' and '过渡采用' not in r.get('codes',[])]
    ids = sorted(r['id'] for r in latest.values())
    for gap in reversed(gaps):
        if sorted(gap['members']) == ids:
            yield dict(common, 样本类型='检索缺口', 能否训练=False, 不能训练的原因='检索缺口',
                       缺口原文=gap['missing'], 本批素材编号=[v[0]['asset_id'] for v in items.values()],
                       来源审核编号=[gap['id'], *ids])
            return
    for winner in winners:
        for loser in latest.values():
            if loser['verdict'] != '不合适':
                continue
            codes = loser['codes']
            if EXCLUDE.intersection(codes):
                continue
            reason = ''
            if not need or need == '见原句':
                reason = '画面要求不足'
            elif not MATCH_CODES.intersection(codes):
                reason = '原因码不用于文案匹配'
            yield dict(common, 样本类型='对比', 能否训练=not reason, 不能训练的原因=reason,
                       胜出=candidate_snapshot(*items[winner['slot']]), 落选=candidate_snapshot(*items[loser['slot']]),
                       标签='胜出排在落选前面', 原因码=codes, 人读结论=loser['sentence'],
                       来源审核编号=[winner['id'], loser['id']])


def export(db_path, directory):
    directory = Path(directory)
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    rows = []
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute('BEGIN')
        counts = {t: db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in ('runs','slot_reviews')}
        by_run = defaultdict(list)
        for rid, data in db.execute('SELECT run_id,data FROM slot_reviews ORDER BY rowid'):
            by_run[rid].append(json.loads(data))
        for rid, reviews in by_run.items():
            payload, result = db.execute('SELECT payload,result FROM runs WHERE id=?', (rid,)).fetchone()
            rows.extend(contract_rows(rid, json.loads(payload), json.loads(result), reviews))
    raw = ''.join(serialize(row) + '\n' for row in rows).encode()
    if (directory / INFO).exists():
        # 改判后先停用旧模型，训练失败也不会沿用过期样本。
        info = json.loads((directory / INFO).read_bytes())
        if info.get('训练文件摘要') != hashlib.sha256(raw).hexdigest():
            write_bytes(directory / INFO, (serialize(dict(info, 状态='待重训')) + '\n').encode())
    changed = write_bytes(directory / DATA, raw)
    return dict(counts, 数据库=str(Path(db_path).resolve()), 总行数=len(rows),
                可训练对比=sum(row['能否训练'] for row in rows), 已更新=changed)


def refresh(db_path, directory, force=False):
    with build_lock(directory):
        result = export(db_path, directory)
        info_path = Path(directory) / INFO
        if force or result['已更新'] or not info_path.exists() or json.loads(info_path.read_bytes()).get('状态') == '待重训':
            result['模型'] = train(Path(directory) / DATA)
        else:
            result['模型'] = json.loads(info_path.read_bytes())
        return result


def training_snapshot(directory):
    """一次历史请求共享一份发布快照，仅统计训练合同里的有效对比。"""
    directory = Path(directory)
    by_run, counts = defaultdict(list), Counter()
    with build_lock(directory):
        data_path, info_path = directory / DATA, directory / INFO
        raw = data_path.read_bytes() if data_path.exists() else b''
        info = json.loads(info_path.read_bytes()) if info_path.exists() else {}
        published = (info.get('状态') == '已训练' and (directory / MODEL).is_file()
                     and info.get('训练文件摘要') == hashlib.sha256(raw).hexdigest())
        for line in raw.splitlines():
            row = json.loads(line)
            if row['样本类型']=='对比' and row['能否训练'] is True:
                counts[row['画面要求']] += 1
                by_run[row['来源运行编号']].append(tuple(row['来源审核编号']))
    return by_run, counts, published, info.get('状态','')


def training_receipt(run, snapshot):
    by_run, counts, published, model_state = snapshot
    state = run['review']
    need = (run['payload'].get('need') or '').strip()
    total = counts[need]
    remaining = max(0, MIN_PAIRS-total)
    if not need or need=='见原句':
        progress = '画面要求未填写，本句暂不能积累有效对比。'
    elif remaining:
        progress = f'同一画面要求累计 {total} 条有效对比，还差 {remaining} 条可启用模型排序。'
    elif published:
        progress = f'同一画面要求累计 {total} 条有效对比，新检索已可使用模型排序。'
    else:
        progress = f'同一画面要求累计 {total} 条有效对比，当前模型尚未就绪。'
    reviews = state['records']
    details = []
    if reviews or state['group']:
        for item in run['result']['items']:
            slot = item['slot']
            record = reviews.get(slot)
            if state['group']:
                reason = '未进训练，整批仅记录检索缺口。'
            elif not record:
                reason = '未进训练，尚未单独评价。'
            elif '过渡采用' in record['codes']:
                reason = '未进训练，仅作过渡。'
            elif record['verdict']=='不合适' and (EXCLUDE.intersection(record['codes']) or not MATCH_CODES.intersection(record['codes'])):
                reason = '未进训练，'+'、'.join(record['codes'])+'不用于文案匹配。'
            elif not need or need=='见原句':
                reason = '未进训练，画面要求不足。'
            else:
                opposite = [r for r in reviews.values() if r['verdict']!=record['verdict']
                            and '过渡采用' not in r['codes'] and (r['verdict']=='采用' or
                            MATCH_CODES.intersection(r['codes']) and not EXCLUDE.intersection(r['codes']))]
                pairs = []
                for other in opposite:
                    win,lose = (record,other) if record['verdict']=='采用' else (other,record)
                    if (win['id'],lose['id']) in by_run.get(run['id'],()):
                        pairs.append(f"{win['slot']} 排在 {lose['slot']} 前面（{'、'.join(lose['codes'])}）")
                if pairs:
                    outcome = '已进训练' if published else '已导出，模型尚未训练成功'
                    if not published and model_state=='无有效特征差异':
                        outcome = '已导出，特征相同未生成模型'
                    reason = outcome+'，'+'；'.join(pairs)+'。'
                elif opposite:
                    reason = '尚未进入训练，最新审核与已导出的对比尚未同步。'
                elif record['verdict']=='采用':
                    reason = '未进训练，缺少可比较的明确退回。'
                else:
                    reason = '未进训练，缺少用于文案匹配的采用镜头。'
            details.append(f'{slot} · {reason}')
    return dict(progress=progress, details=details)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['export', 'train', 'refresh'])
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().parent.parent / 'local/cutframe/ai/learning.sqlite3')
    args = parser.parse_args()
    if args.command == 'refresh':
        result = refresh(args.db, args.directory, force=True)
    else:
        with build_lock(args.directory):
            result = train(args.directory / DATA) if args.command == 'train' else export(args.db, args.directory)
    print(json.dumps(result, ensure_ascii=False))
