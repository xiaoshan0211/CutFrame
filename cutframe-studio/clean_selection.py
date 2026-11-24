"""第四步清洗表准入。只读取原片清单和带起止秒的画面标签。"""
import hashlib
import math
import re
from functools import lru_cache
from pathlib import PureWindowsPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def version(path):
    try:
        st = path.stat()
    except OSError as exc:
        raise ValueError('清洗 Excel 无法读取，请检查文件后重新检索') from exc
    return f'{st.st_mtime_ns}-{st.st_size}'


def _rows(book, target, strings):
    header = {}
    with book.open(target) as stream:
        for _, row in ET.iterparse(stream, events=('end',)):
            if not row.tag.endswith('}row'):
                continue
            values = {}
            for cell in row:
                col = cell.get('r', '').rstrip('0123456789')
                val = cell.findtext('{*}v', '')
                if cell.get('t') == 's':
                    val = strings[int(val)]
                elif cell.get('t') == 'inlineStr':
                    val = ''.join(t.text or '' for t in cell.iter('{*}t'))
                values[col] = val
            if header:
                yield {field:values.get(col,'') for col,field in header.items()}
            else:
                header = values
            row.clear()


@lru_cache(maxsize=2)
def tag_rows(path, stamp):
    result = []
    with ZipFile(path) as book:
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            strings = [''.join(t.text or '' for t in si.iter('{*}t')) for si in ET.fromstring(book.read('xl/sharedStrings.xml'))]
        rel = {r.get('Id'):r.get('Target') for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        sheets = {}
        for s in ET.fromstring(book.read('xl/workbook.xml')).findall('.//{*}sheet'):
            target = rel[next(v for k,v in s.attrib.items() if k.endswith('}id'))]
            sheets[s.get('name')] = target.lstrip('/') if target.startswith('/') else 'xl/'+target
        allowed = {}
        for r in _rows(book,sheets['全目录清单'],strings):
            p = PureWindowsPath(r['原片路径'])
            valid = r['结论']=='有分类待抽查' and r['媒体']=='视频' and 0<float(r['显示宽'] or 0)<float(r['显示高'] or 0)
            allowed[p] = r['镜序素材ID'] if valid and p not in allowed else None
        for sheet in ('已核标签','候选标签'):
            for r in _rows(book,sheets[sheet],strings):
                p = PureWindowsPath(r['原片路径'])
                code = (r['修正标签'] or r['标签']).strip()
                if allowed.get(p) is None or not code:
                    continue
                if r['核验状态'] not in ('已有核验依据','候选待看片'):
                    continue
                start,end = float(r['起秒']),float(r['止秒'])
                if not (0<=start<end and math.isfinite(end)):
                    continue
                fact = r.get('可见事实（原片抽帧）', r.get('可见事实或旧标注依据', ''))
                result.append((p,allowed[p],code,start,end,sheet,fact,r['标签维度'],r['标签名称']))
    return result


def load(path, stamp, categories=False):
    dimension='素材类别' if categories else '画面类型'
    return [row[:7] for row in tag_rows(path,stamp) if row[7]==dimension]


@lru_cache(maxsize=4)
def label_tree(path,stamp):
    from structured_selection import read_tables
    names={(r['维度'],r['标签']):r['名称'] for r in read_tables(path,stamp,'标签字典')['标签字典']}
    labels={}
    for _,_,code,_,_,_,_,dim,name in tag_rows(path,stamp):
        labels[dim,code]=dict(id=code,name=names.get((dim,code),name or code),dimension=dim,enabled=True)
    return dict(dimensions=[dict(id=d,name=d) for d in sorted({d for d,_ in labels})],labels=list(labels.values()))


def windows(path, stamp, assets, roots, types, categories=(), selectors=(), keywords=()):
    lookup = {}
    for aid,a in assets.items():
        if not a.get('available') or not roots[a['root']].get('path'):
            continue
        full = PureWindowsPath(roots[a['root']]['path']) / a['rel']
        lookup[full] = aid
        for alternate in roots[a['root']].get('path_aliases', []):
            lookup[PureWindowsPath(alternate) / a['rel']] = aid
    groups={}
    for p,ident,code,start,end,sheet,desc,dim,_ in tag_rows(path,stamp):
        aid=lookup.get(p)
        if not aid or (ident and ident!=aid):continue
        tags,descriptions=groups.setdefault((aid,start,end),([],[]))
        tags.append((dim,code,sheet))
        if desc and desc not in descriptions:descriptions.append(desc)
    wanted=set(selectors)|{('画面类型',t) for t in types}|{('素材类别',t) for t in categories}
    for (aid,start,end),(tags,descriptions) in groups.items():
        description='；'.join(descriptions)
        hit=any(k in description for k in keywords)
        if not hit and not any((d,t) in wanted for d,t,_ in tags):continue
        key=hashlib.sha256(repr((aid,start,end)).encode()).hexdigest()[:24]
        primary=next((x for x in tags if x[0]=='画面类型'),None)
        sheet=(primary or tags[0])[2]
        yield dict(id='清洗-'+key,asset_id=aid,start=start,end=end,picture=primary[1] if primary else '',
                   extra_tags=[x for x in tags if x!=primary],basis=sheet,description=description,
                   keyword_hit=hit,classified_table=path.name+' / '+sheet)
