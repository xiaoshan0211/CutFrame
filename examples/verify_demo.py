"""用镜序读取合成样例，在同一素材、同一起止秒上检查组合条件。"""
import argparse
import hashlib
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'cutframe-studio'))

import clean_selection
import cloud_segments
import structured_selection
from copy_viewpoints import Viewpoints


FILENAME = 'synthetic-scene-01.mp4'
ASSET_ID = hashlib.sha256(('demo/' + FILENAME).encode()).hexdigest()[:32]
CASES = (
    ('镜头中抹板在墙面移动并留下色带。', 'V05', '覆盖批刮工艺', [(1.25, 5.25)]),
    ('把保护胶带铺到地面边缘。', 'V09', '地面服务', [(5.25, 8.75)]),
    ('镜头中抹板在墙面移动并留下色带。', 'V05', '地面服务', []),
)


def register_video():
    import init_local
    init_local.initialize(init_local.default_state())
    import app
    demo = app.CONFIG['roots'].get('demo', {})
    if Path(demo.get('path', '')).resolve() != HERE or 'examples' not in demo.get('path_aliases', []):
        raise SystemExit('请按 examples/README.md 将演示库 demo 配置为本仓库的 examples 目录。')
    app.CONFIG['roots'] = {'demo': demo}
    app.initialize()
    app.scan()
    if app.SCAN['error']:
        raise SystemExit(app.SCAN['error'])
    if not app.get_asset(ASSET_ID)['available']:
        raise SystemExit('示例视频尚未登记。')
    print('演示视频已登记到当前本机素材索引。')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--index', action='store_true', help='同时登记演示视频，供桌面工作台调取')
    args = cli.parse_args()
    if not (HERE / FILENAME).is_file():
        raise SystemExit('缺少随仓库提供的演示视频。')
    if args.index:
        register_video()
    assets = {ASSET_ID: {'available': True, 'root': 'demo', 'rel': FILENAME}}
    roots = {'demo': {'path': str(HERE), 'path_aliases': ['examples']}}
    local = ROOT / '修订产出' / '镜序素材清洗与分类_可见事实修订.xlsx'
    cloud = ROOT / '修订产出' / '团队云端' / '镜序素材清洗与分类_云端.xlsx'
    views = Viewpoints(ROOT)
    print('素材 ID', ASSET_ID)
    for sentence, code, category, expected in CASES:
        view = structured_selection.resolve(ROOT, sentence, views.lookup(sentence))
        if view['primary'] != [code]:
            raise SystemExit(f'{sentence} 的类型为 {view["primary"]}，预期 {code}')
        sources = (
            ('本地', clean_selection.windows(local, clean_selection.version(local), assets, roots, [code])),
            ('云端表', cloud_segments.windows(cloud, assets, [code], [])),
        )
        for label, rows in sources:
            hits = [(r['start'], r['end']) for r in rows if r['asset_id'] == ASSET_ID and r['picture'] == code
                    and any(dim == '素材类别' and value == category for dim, value, _ in r['extra_tags'])]
            if hits != expected:
                raise SystemExit(f'{label} {code} + {category} 得到 {hits}，预期 {expected}')
            print(f'{label} | {code} + {category} | {hits}')


if __name__ == '__main__':
    main()
