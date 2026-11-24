"""团队云端的离线秒段。关联依靠素材 ID 和秒段，不按文件名猜测。"""
from collections import defaultdict
from functools import lru_cache
import math

from clean_selection import version
from structured_selection import read_tables


@lru_cache(maxsize=1)
def _index(path, stamp):
    tables = read_tables(path, stamp)
    segments = defaultdict(list)
    labels = defaultdict(list)
    assets = {}
    aliases = defaultdict(set)
    seen_segments = set()
    for row in tables['全目录清单']:
        aid = row['镜序素材ID']
        alias = row.get('本地同源素材ID')
        if alias and row.get('SHA-256'):
            aliases[aid].add(alias)
            aliases[alias].add(aid)
        assets[row['云端素材编号']] = row
    for row in tables['云端秒段']:
        asset = assets.get(row['云端素材编号'])
        if not asset or asset['镜序素材ID'] != row['镜序素材ID']:
            continue
        start, end = float(row['起秒']), float(row['止秒'])
        if not (0 <= start < end and math.isfinite(end)):
            continue
        aid = row['镜序素材ID']
        # 一段可以有多条标签行，播放器和检索只登记一次该段。
        key = (aid, row['段序'], start, end)
        if key in seen_segments:
            continue
        seen_segments.add(key)
        segments[aid].append(dict(start=start, end=end, text=row.get('定稿画面描述', row.get('镜头内容 · 云端原文', '')),
            evidence=row.get('定稿画面描述', row.get('本轮抽帧依据', '')), labels=row.get('已列画面类型', '') if '定稿画面描述' in row else row.get('云端维度与标签原文', ''), ordinal=row['段序']))
    for sheet in ('已核标签', '候选标签'):
        for row in tables[sheet]:
            asset = assets.get(row['云端素材编号'])
            if not asset or asset['结论'] != '有分类待抽查' or asset['媒体'] != '视频':
                continue
            if row['核验状态'] not in ('已有核验依据', '候选待看片'):
                continue
            key = (asset['镜序素材ID'], float(row['起秒']), float(row['止秒']))
            labels[key].append((row['标签维度'], row['修正标签'] or row['标签'], sheet))
    for rows in segments.values():
        rows.sort(key=lambda r: r['start'])
    return segments, labels, aliases


def index(path):
    return _index(path, version(path))


def windows(path, assets, types, keywords, categories=(), selectors=()):
    segments, labels, _ = index(path)
    for aid in assets.keys() & segments.keys():
        for row in segments[aid]:
            start, end = row['start'], row['end']
            tags = labels.get((aid, start, end), ())
            pictures = [t for t in tags if t[0] == '画面类型']
            matched = [t for t in pictures if t[1] in types]
            description = row['evidence'] or row['text']
            hit = any(k in description for k in keywords) and description != '暂无描述'
            if not (matched or hit or any((d,t) in selectors for d,t,_ in tags) or any(dim=='素材类别' and tag in categories for dim,tag,_ in tags)):
                continue
            # 分类依据逐标签保存，检索窗口按同一个原片秒段生成一次。
            primary = (matched or pictures or [('画面类型', '', '候选标签')])[0]
            _, code, sheet = primary
            yield dict(id=f"云端-{aid}-{row['ordinal']}", asset_id=aid, start=start, end=end,
                       picture=code, basis=sheet, description=description, keyword_hit=hit,
                       extra_tags=[t for t in tags if t != primary],
                       classified_table=path.name+' / '+sheet)
