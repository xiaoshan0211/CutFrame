"""将分类路径表中的秒段与工作台已登记的原片精确对应。"""
import csv
import hashlib
import math
from functools import lru_cache
from pathlib import PureWindowsPath


@lru_cache(maxsize=48)
def _read(path, version):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def classified_windows(library, assets, roots, types):
    if not types or library is None:
        return []
    paths = {}
    for asset in assets.values():
        config = roots[asset['root']].get('path')
        if not config:
            continue
        full = PureWindowsPath(config) / asset['rel']
        paths[full] = asset['id']
        for alternate in roots[asset['root']].get('path_aliases', []):
            paths[PureWindowsPath(alternate) / asset['rel']] = asset['id']
    if not paths:
        return []
    tables = [library/'500条素材路径总表.csv']
    tables.extend(library.glob('*Z盘1小区_画面归类/分类候选总表.csv'))
    tables.extend(sorted(library.glob('扒扒_画面分类_*/可用/V*.csv')))
    windows = {}
    for table in tables:
        if not table.is_file():
            continue
        stat = table.stat()
        for row in _read(table, (stat.st_mtime_ns, stat.st_size)):
            code = row['画面类型']
            if code not in types or row.get('媒体实质', '视频') != '视频':
                continue
            aid = paths.get(PureWindowsPath(row['原片路径']))
            if not aid or (assets[aid]['root'] == 'baba' and table.parent.name != '可用'):
                continue
            start = float(row.get('入点秒') or row['起秒'])
            end = float(row.get('出点秒') or row['止秒'])
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
                continue
            key = (aid, start, end, code)
            ident = hashlib.sha256(repr(key).encode()).hexdigest()[:24]
            windows[key] = dict(id='表-'+ident, asset_id=aid, start=start, end=end,
                                picture=code, basis=row.get('依据来源') or row.get('分类依据来源'),
                                description=row.get('画面依据') or row.get('可见动作或现有依据',''),
                                classified_table=table.relative_to(library).as_posix())
    return list(windows.values())
