"""离线读取融合工作簿，用原句、同义动作和可见证据检索。"""
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


def book_path(root):
    if Path(root).suffix=='.xlsx':return Path(root)
    return Path(root)/'修订产出/20261120_GitHub融合/文案结构化标注.xlsx'

AUTO_STATUS='自动初标，待核对'

# 把口语动作映射到现场可能看见的对象和动作；政策用词只用于匹配文案。
WORDS = {
 '量房':'量房|量尺|测量|测距|卷尺|激光尺|测尺寸|量尺寸|丈量|尺子',
 '上门':'上门|到家服务|到您家|到你家|入户|登门',
 '免费':'免费|不收费|不收钱|零费用|免单',
 '方案':'出方案|设计方案|做方案|给方案|图纸|设计图',
 '保护':'保护膜|铺膜|遮蔽|成品保护','搬家':'搬家|搬离|搬出去',
 '批刮':'批刮|刮板|批刀|刮涂','滚涂':'滚涂|滚刷|滚筒',
 '拆砸':'敲砖|砸砖|拆砸|拆除|敲瓷砖|砸掉瓷砖|敲掉瓷砖|敲碎瓷砖','清洁':'清洁|擦洗|擦拭|清扫',
 '沟通':'沟通|交谈|握手|交流','安装':'安装|装上|接线',
 '渗水':'渗漏|渗水|漏水','旧房':'旧房|老房|老屋','完工':'完工|竣工|改造后',
 '厨房':'厨房|厨间','卫浴':'卫生间|卫浴|洗手间|厕所'}
PAT={k:re.compile(v) for k,v in WORDS.items()}
def concepts(s):return {k for k,p in PAT.items() if p.search(s)}
def grams(s):return {s[i:i+2] for i in range(len(s)-1)}
def codes(s):return list(dict.fromkeys(re.findall(r'V\d\d',s)))
def norm(s):return re.sub(r'[\W_]+','',s)
def negative(s):return bool(re.search('不(?!仅|但|光|收费|收钱)|无需|免拆|别拆|没必要',s))
def sim(a,b):return len(a&b)/max(1,len(a|b))

@lru_cache(maxsize=2)
def read_tables(path,stamp,only=None):
    with ZipFile(path) as z:
        strings=[''.join(n.text or '' for n in x.findall('.//{*}t')) for x in ET.fromstring(z.read('xl/sharedStrings.xml'))] if 'xl/sharedStrings.xml' in z.namelist() else []
        root=ET.fromstring(z.read('xl/workbook.xml'))
        rel={r.get('Id'):r.get('Target').lstrip('/') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        tables={}
        for sheet in root.findall('.//{*}sheet'):
            name=sheet.get('name')
            if name=='使用说明' or (only and name!=only):continue
            target=rel[next(v for k,v in sheet.attrib.items() if k.endswith('}id'))]
            xml=ET.fromstring(z.read(target if target.startswith('xl/') else 'xl/'+target))
            headers={};rows=[]
            for row in xml.findall('.//{*}row'):
                cells={}
                for c in row.findall('{*}c'):
                    v=c.findtext('{*}v','')
                    cells[re.match('[A-Z]+',c.get('r'))[0]]=strings[int(v)] if c.get('t')=='s' else ''.join(n.text or '' for n in c.findall('.//{*}t')) if c.get('t')=='inlineStr' else v
                if not headers:headers=cells
                else:rows.append({h:cells.get(k,'') for k,h in headers.items()})
            tables[name]=rows
    return tables

@lru_cache(maxsize=1)
def read(path,stamp):
    tables=read_tables(path,stamp)
    cats={r['类别条件编号']:r for r in tables['类别条件']}
    lines={r['记录ID']:r for r in tables['逐句条件']}
    index={}
    for source in tables['逐条标注']:
        r=dict(source)
        s=norm(r['代表句']);r['类别规则']=cats[r['类别条件编号']] if r['类别条件编号'] else {}
        r['逐句规则']=[lines[i] for i in r['同原句条件编号'].split('、') if i]
        index[r['观点ID']]=(r,s,concepts(s),grams(s))
    return index,tables['粗标秒段']

def dataset(root):
    path=book_path(root);return read(path,path.stat().st_mtime_ns)

def resolve(root,text,view):
    index,_=dataset(root);q=norm(view.get('joined') or text);words=concepts(q);pairs=grams(q)
    # 只归并这句已核对的旧工法表述，保留“不砸”“不会砸”等相反含义。
    aliases={'传统翻新只会砸掉瓷砖':'传统翻新要砸掉瓷砖'}
    for neighbor in view.get('neighbors',[]):
        sentence=norm(neighbor.get('text',''))
        known=index.get(neighbor.get('id'))
        if not known and sentence:
            rows=[entry for entry in index.values() if entry[1]==aliases.get(sentence,sentence)]
            known=rows[0] if len(rows)==1 else None
        if known:
            r=known[0]
            neighbor.update(id=r['观点ID'],primary=codes(r['主画面类型']),polarity=r['肯否'],status=r['标注状态'])
    literal=norm(text)
    target=aliases.get(literal,literal)
    direct=[r for r,s,_,_ in index.values() if s==target]
    if len(direct)==1 and (not view['id'] or not view.get('joined') or direct[0]['标注状态']=='人工确认'):
        row=direct[0]
        view.update(id=row['观点ID'],title=row['代表句'],category=row['素材类别'],action=row['必须看见的动作'],
                    polarity=row['肯否'],forbidden=row['禁用与限制'],alternatives_by_id=[],joined=text if target!=literal else '',
                    equivalent=target!=literal)
        q=literal;words=concepts(q);pairs=grams(q)
    anchor=index.get(view['id'])
    view['entry_id']=anchor[0]['观点ID'] if anchor else ''
    if view['alternatives_by_id']:return view
    if anchor and not anchor[0]['主画面类型']:
        view.update(primary=[],defaults=[],inherited='',alternatives=[],status=anchor[0]['标注状态'])
        return view
    ranked=[]
    for ident,(r,s,w,g) in index.items():
        if not r['主画面类型'] or r['标注状态']=='待人定类型':continue
        exact=ident==view['id']
        if not exact and r['标注状态']==AUTO_STATUS:continue
        if not exact and (negative(q)!=negative(s) or re.findall(r'\d+',q)!=re.findall(r'\d+',s)):continue
        overlap=words&w;lex=sim(pairs,g)
        if not exact and not (lex>=.43 or len(overlap)>=2 or (overlap-{'免费','上门','旧房','厨房','卫浴'} and lex>=.18)):continue
        score=3*exact+sim(words,w)+lex
        ranked.append((score,ident,r))
    ranked.sort(key=lambda x:(-x[0],x[1]))
    if not ranked:return view
    if not anchor and len(ranked)>1 and ranked[0][0]-ranked[1][0]<.12 and ranked[0][2]['素材类别']!=ranked[1][2]['素材类别']:return view
    top=ranked[0][2];matches=[r for score,i,r in ranked[:6]]
    # 保留一个“同一服务、不同动作”的参照，如量房与上门出方案。
    related=next((r for _,_,r in ranked if r['素材类别']!=top['素材类别'] and len(words&concepts(r['代表句']))>=2),None)
    if {'上门','量房'}<=words:
        related=next((r for _,_,r in ranked if '方案' in concepts(r['代表句']) and '量房' not in concepts(r['代表句']) and r['素材类别']=='方案设计与样品'),related)
    if related and related not in matches:matches=matches[:5]+[related]
    main=codes(top['主画面类型']);alts=codes(' '.join(r['主画面类型']+' '+r['备选画面类型'] for r in matches))
    banned=codes(top['禁用与限制'].split('；')[0]) if re.match(r'^V\d\d',top['禁用与限制']) else []
    view.update(id=top['观点ID'],title=top['代表句'],category=top['素材类别'],action=top['必须看见的动作'],status=top['标注状态'],polarity=top['肯否'],primary=main,defaults=main,source_id=top['观点ID'],forbidden=top['禁用与限制'],alternatives=[t for t in alts if t not in main+banned],structured=matches,structured_version=book_path(root).stat().st_mtime_ns,scene_words=sorted(words),blocked_types=banned)
    return view

def workbook_windows(root,assets,types):
    for r in dataset(root)[1]:
        aid=r['镜序素材ID'];code=r['画面类型']
        if aid not in assets or code not in types:continue
        yield dict(id='融合-'+r['粗标编号']+'-'+code,asset_id=aid,start=float(r['起秒']),end=float(r['止秒']),picture=code,basis=r['依据'],description=r['粗标描述'],classified_table='粗标秒段 '+r['粗标编号'])

def assess(view,item,evidence):
    rows=view['structured'];top=rows[0];tags=set(item['tags']);desc=' '.join(evidence)
    rules=[top['类别规则'],*top['逐句规则']]
    forbidden=' '.join(r.get('禁止','') for r in rules)+' '+top['禁用与限制']
    if tags.intersection(view['blocked_types']):return None
    if '扒扒' in forbidden and item['root']=='baba' and '防水' not in top['素材类别']:return None
    if '他方品牌' in forbidden and re.search('嘉贝乐|他方品牌包装入镜',desc):return None
    if '微陶泥' in top['代表句'] and re.search('微岩石|水洗石',desc):return None
    found=concepts(desc);query=set(view['scene_words'])
    if '量房' in query and not negative(top['代表句']) and ('量房' not in found or re.search(r'未见.{0,4}测量|没有.{0,4}测量|未测量',desc)):return None
    visible=query-{'免费','旧房','厨房','卫浴','上门'}
    if top['对应性质']=='直接展示' and visible and not negative(top['代表句']) and not visible.intersection(found):return None
    scores=[]
    for r in rows:
        if not tags.intersection(codes(r['主画面类型']+' '+r['备选画面类型'])):continue
        rules=[*r['逐句规则'],r['类别规则']]
        actions=concepts(r['必须看见的动作'])
        prefer=concepts(' '.join(x.get('优先','') for x in rules))
        must=concepts(' '.join(x.get('必须','') for x in rules))
        score=8*len(found&query)+3*len(found&actions)+len(found&prefer)+len(found&must)+4*bool(tags.intersection(view['primary']))+2*bool(tags.intersection(codes(r['主画面类型'])))+int(r is top)
        scores.append((score,r['观点ID']))
    return max(scores,default=(0,'手动类型'))
