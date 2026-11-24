"""本机选镜排序。训练入口只接收独立的 JSONL，运行时用模型内的特征表。"""
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / '.packages'))


DATA = '排序训练.jsonl'
MODEL = '排序模型.cbm'
INFO = '排序模型说明.json'
LEGACY = '原排序'
MIN_PAIRS = 2
DIRECTORY = Path(__file__).resolve().parent.parent / '画面类型素材路径库' / '文案画面类型标注'
NUMBERS = ['层级', '当时顺序', '起点秒', '终点秒']
DIMENSIONS = {'画面类型': r'V\d\d', '主动作': r'B6[ACDH]\d\d', '朝向': r'B5O\d\d'}


def serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@contextmanager
def temporary_target(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix='.rank-', suffix='.tmp')
    os.close(fd)
    temp = Path(name)
    try:
        yield temp
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def write_bytes(target, data):
    if target.exists() and target.read_bytes() == data:
        return False
    with temporary_target(target) as temp:
        temp.write_bytes(data)
    return True


def candidate_snapshot(item, position):
    # 旧 runs 的 tags 是推荐时已保存的正向标注，按标签树稳定编号拆分，不回表。
    labels = {dim: sorted({t for t in item.get('tags', []) if re.fullmatch(pattern, t)})
              for dim, pattern in DIMENSIONS.items()}
    return {'槽位': item.get('slot', ''), '素材编号': item['asset_id'],
            '起点秒': item['start'], '终点秒': item['end'],
            '当时顺序': item.get('rank_input_order', position),
            **labels, '层级': item['layer'], '来源': item['local_kind']}


def features(side, names):
    active = {dim + '=' + t for dim in DIMENSIONS for t in side.get(dim, [])}
    active.add('来源=' + side['来源'])
    return [float(side[n]) if n in NUMBERS else int(n in active) for n in names]


def train(path):
    """在全量有效对比上从头拟合。模型和说明分别原子发布，通过版本互相校验。"""
    path = Path(path)
    raw = path.read_bytes()
    groups = defaultdict(list)
    counts = Counter()
    for line in raw.splitlines():
        row = json.loads(line)
        if row['能否训练'] is True and row['样本类型'] == '对比':
            groups[row['分组键']].append(row)
            counts[row['画面要求']] += 1
    names = list(NUMBERS)
    categories = set()
    for rows in groups.values():
        for row in rows:
            for side in (row['胜出'], row['落选']):
                categories.update(dim + '=' + t for dim in DIMENSIONS for t in side.get(dim, []))
                categories.add('来源=' + side['来源'])
    names.extend(sorted(categories))
    samples, group_ids, pairs = [], [], []
    for group, rows in enumerate(groups.values()):
        for row in rows:
            pairs.append((len(samples), len(samples) + 1))
            samples.extend(features(row[key], names) for key in ('胜出', '落选'))
            group_ids.extend([group, group])
    version = 'pairlogit-v1-' + hashlib.sha256(serialize([names, samples, group_ids, counts]).encode()).hexdigest()[:16]
    info = {'模型版本': version, '样本数': len(pairs), '分组数': len(groups), '特征名': names,
            '各画面要求对比数': dict(counts), '训练文件摘要': hashlib.sha256(raw).hexdigest()}
    if not pairs or all(samples[a] == samples[b] for a,b in pairs):
        info.update(模型版本=LEGACY, 状态='无有效特征差异' if pairs else '没有可训练对比')
    else:
        from catboost import CatBoostRanker, Pool, __version__
        info.update(状态='已训练', CatBoost版本=__version__)
        model = CatBoostRanker(loss_function='PairLogit', iterations=100, depth=3, learning_rate=0.12,
                               random_seed=31, random_strength=0, bootstrap_type='No', thread_count=1,
                               verbose=False, allow_writing_files=False, metadata={'rank_version': version})
        data = Pool(samples, label=[v for _ in pairs for v in (1, 0)], group_id=group_ids,
                    pairs=pairs, feature_names=names)
        model.fit(data)
        with temporary_target(path.with_name(MODEL)) as temp:
            model.save_model(str(temp), format='cbm')
    write_bytes(path.with_name(INFO), (serialize(info) + '\n').encode())
    return info


def load_for_need(directory, need):
    """每次新检索检查已发布版本。未达门槛、发布中或文件缺失时保留原顺序。"""
    if not directory or not need or need == '见原句':
        return None
    directory = Path(directory)
    try:
        info = json.loads((directory / INFO).read_bytes())
        if info.get('状态') != '已训练' or info['各画面要求对比数'].get(need, 0) < MIN_PAIRS:
            return None
        if not (directory / MODEL).is_file():
            return None
        from catboost import CatBoostRanker
        model = CatBoostRanker()
        model.load_model(str(directory / MODEL))
        if model.get_metadata().get('rank_version') == info['模型版本'] and model.feature_names_ == info['特征名']:
            return model, info
    except (FileNotFoundError, ImportError):
        return None


def rerank(loaded, items):
    if not loaded or not items:
        return
    model, info = loaded
    values = [features(candidate_snapshot(c, i), info['特征名']) for i,c in enumerate(items, 1)]
    scores = model.predict(values, thread_count=1)
    items[:] = [item for _,item in sorted(zip(scores, items), key=lambda entry: -entry[0])]
