"""第四步使用的本地观点索引、可引用的已审经验和选择差规律。"""
import hashlib
import json
import os
import posixpath
import re
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from short_subtitles import PARTICLES, ShortSubtitleIndex, meaning_key


def key(text):
    value=unicodedata.normalize('NFKC',str(text or '')).strip().casefold()
    # 价格、工期、百分比和数值区间是原句事实，匹配时保留参与数值的标点。
    return re.sub(r'[\s，,。！？!?、“”「」]+|(?<!\d)\.|\.(?!\d)', '', value)


def lines(path):
    return [json.loads(s) for s in path.read_text('utf-8-sig').splitlines() if s.strip()]


def workbook_rows(path):
    """只读指定工作表，兼容 Excel 的共享字符串、内联字符串和省略的空单元格。"""
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    rel_ns = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    def content(node):
        return ''.join(t.text or '' for t in node.iter(ns+'t'))
    def types(value):
        codes = list(dict.fromkeys(re.split(r'[、，,;；\s/]+', value.strip()))) if value.strip() else []
        return codes if all(re.fullmatch(r'V(?:0[1-9]|1\d|2[0-4])', c) for c in codes) else []
    with ZipFile(path) as book:
        sheets = ET.fromstring(book.read('xl/workbook.xml')).iter(ns+'sheet')
        sheet = next((s for s in sheets if s.get('name')=='观点画面类型'), None)
        if sheet is None:raise ValueError('标注表缺少「观点画面类型」工作表')
        links = ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))
        paths = {r.get('Id'):posixpath.normpath(posixpath.join('xl',r.get('Target'))).lstrip('/') for r in links}
        strings = []
        for rel in links:
            if rel.get('Type','').endswith('/sharedStrings'):
                strings = [content(s) for s in ET.fromstring(book.read(paths[rel.get('Id')]))]
        sheet_xml = ET.fromstring(book.read(paths[sheet.get(rel_ns+'id')]))
        headers = {}
        for row in sheet_xml.iter(ns+'row'):
            cells = {}
            for cell in row.findall(ns+'c'):
                col = re.match('[A-Z]+',cell.get('r')).group()
                value = cell.findtext(ns+'v','')
                if cell.get('t')=='s':value=strings[int(value)]
                if cell.get('t')=='inlineStr':value=content(cell)
                cells[col] = value.strip()
            if not headers:
                if '观点 ID' in cells.values():headers=cells
                continue
            data = {name:cells.get(col,'') for col,name in headers.items()}
            if not data['观点 ID']:continue
            for name in ('主画面类型','备选画面类型'):
                data[name]=types(data[name])
            yield data


def section_five(text):
    if re.search(r'(?:你|您|要是|如果|刚好|刚刚|恰好|今天|正好)?刷到(?:这条|这个|了这条|了这个)视频', text) and not re.search('没人|没有|没刷到',text):
        return 1, ['V01']
    if re.search(r'等一下|帮个忙',text):
        return 2, ['V01']
    if re.search(r'边住边(?:施|改|装)|边装边住|施工期间.{0,5}(?:在家|居住)|住在家里.{0,5}(?:装|改)',text):
        return 0, ['V15','V17']
    return None, []


class Viewpoints:
    def __init__(self, root, cloud_directory=None):
        self.root = Path(root)
        self.library = self.root / '画面类型素材路径库'
        self.directory = cloud_directory or self.library / '文案画面类型标注'
        self.plan = self.root / '镜序_文案到镜头选片方案.md'
        self.rows = {r['观点 ID']:r for r in workbook_rows(self.directory/'观点画面类型.xlsx')}
        self.matches = defaultdict(set)
        self.positions = defaultdict(list)
        for ident,source,original,before,after,status in lines(self.directory/'原文定位索引.jsonl'):
            if ident not in self.rows:continue
            self.matches[key(original)].add(ident)
            if '禁用' not in status:
                self.positions[ident].append((original,before,after))
        for ident,r in self.rows.items():
            self.matches[key(r['代表句'])].add(ident)
        self.short_subtitles=ShortSubtitleIndex(self.matches)
        equivalents=defaultdict(set)
        for sentence,owners in self.matches.items():
            equivalents[meaning_key(sentence)].update(owners)
        self.expressions=ShortSubtitleIndex(equivalents)
        self.examples = []
        if cloud_directory:
            self.confirmed=[]
            return
        summary = self.library/'观点清单十句_第一轮/首轮审核汇总.md'
        title = ''
        for line in summary.read_text('utf-8-sig').splitlines():
            if line.startswith('## '):
                title = re.sub(r'^## \d+[. ]*','',line)
            elif title and line.startswith('- V'):
                for entry in line.split('：',1)[1].split('；'):
                    if entry.startswith(('合适：','不合适：','勉强：')):
                        self.examples.append((title, entry, '观点清单十句_第一轮/首轮审核汇总.md · '+title))
        summary = self.library/'六句文案_已审镜头汇总.md'
        for line in summary.read_text('utf-8-sig').splitlines():
            if line.startswith('## '):
                title = re.sub(r'^## \d+\s+','',line)
            elif title and line.startswith('| 第'):
                label,score,description,_ = [s.strip() for s in line.strip('|').split('|')]
                if score.startswith(('合适','不合适','勉强')):
                    self.examples.append((title, score+' · '+description, summary.name+' · '+label))
        section = self.plan.read_text('utf-8-sig').split('## 五、',1)[1].split('## 六、',1)[0]
        self.confirmed = [next(line for line in section.splitlines() if line.startswith(prefix))
                          for prefix in ('表达“施工期间','“刷到这条视频”','配“等一下')]

    def match(self, text):
        ids=self.matches.get(key(text),())
        return self.rows[next(iter(ids))] if len(ids)==1 else None

    def lookup(self, text, before='', after='', leading=None, trailing=None):
        if leading is not None:before=leading[-1] if leading else ''
        if trailing is not None:after=trailing[0] if trailing else ''
        current=key(text)
        single_ids=self.matches.get(current,()) if current not in PARTICLES else ()
        joined=False
        equivalent=False
        owners={ident:(0,0) for ident in single_ids}
        if not owners and current not in PARTICLES:
            left=leading if leading is not None else ([before] if before else [])
            right=trailing if trailing is not None else ([after] if after else [])
            owners=self.short_subtitles.find(current,[key(s) for s in left],[key(s) for s in right])
            if not owners and len(current)>=4:
                owners=self.expressions.find(meaning_key(current),[meaning_key(key(s)) for s in left],
                                             [meaning_key(key(s)) for s in right])
                equivalent=bool(owners)
            joined=bool(owners)
        row=self.rows[next(iter(owners))] if len(owners)==1 else None
        primary=row['主画面类型'] if row else []
        ident=row['观点 ID'] if row else ''
        view=dict(id=ident,title=row['代表句'] if row else '新增观点',primary=primary,
                  defaults=[],inherited='',source_id='',neighbors=[],alternatives=[],category='',polarity='',
                  action='',forbidden='',status='')
        view['alternatives_by_id']=[dict(id=i,title=self.rows[i]['代表句'],primary=self.rows[i]['主画面类型'])
                                    for i in sorted(owners)] if len(owners)>1 else []
        view['joined']=''
        view['equivalent']=equivalent
        if row and joined:
            first,last=owners[ident]
            view['joined']=''.join(left[len(left)+first:]+[text]+right[:last])
        if row:
            view.update(alternatives=row['备选画面类型'],category=row['素材类别'],polarity=row['肯否'],
                        action=row['必须看见的动作'],forbidden=row['禁止当作正面证明的画面'],status=row['状态'])
            if 1<=len(primary)<=3 and row['状态']!='待人定类型':
                view.update(defaults=primary,source_id=ident)
                return view

        # 有当前文案时只看紧邻字幕；单独查询一句时仅使用能唯一定位的原稿邻句。
        if not before and not after and row and not joined:
            positions=self.positions[ident]
            exact=[p for p in positions if key(p[0])==key(text)]
            pairs={(p[1],p[2]) for p in exact or positions}
            if len(pairs)==1:before,after=pairs.pop()
        for label,sentence in [('上一句',before),('下一句',after)]:
            neighbor=self.match(sentence) if sentence else None
            view['neighbors'].append(dict(label=label,text=sentence,id=neighbor['观点 ID'] if neighbor else '',
                     primary=neighbor['主画面类型'] if neighbor else [],polarity=neighbor['肯否'] if neighbor else '',
                     status=neighbor['状态'] if neighbor else ''))
        if not row or joined or primary or row['肯否']!='需上下文':return view
        # 已经明确否定某个动作的句子有自己的观点，不能把邻句说的拆砸等正向工序当作自己的证明。
        negative=r'不(?!仅|但|光|得不)|没(?!想到|错)|无(?:需|须)|免拆|别(?:拆|砸|敲)'
        if re.search(negative,text) or re.search(negative,row['代表句']):return view
        affirmative=re.search(r'必须|一定要|应该|需要|要先|得先',text)
        for neighbor in reversed(view['neighbors']):
            if affirmative and neighbor['polarity']=='否定':continue
            types=neighbor['primary']
            if (neighbor['id'] and neighbor['id']!=ident and 1<=len(types)<=3
                and neighbor['status']!='待人定类型' and neighbor['polarity'] in ('肯定','否定')):
                view.update(defaults=types,inherited=neighbor['text'],source_id=neighbor['id'])
                break
        return view

    def references(self, view, text, records, *, include_local_examples=True):
        options = {}
        def add(source, example):
            ident = hashlib.sha256((source+'\n'+example).encode()).hexdigest()[:20]
            options[ident] = dict(id=ident,source=source,text=example)
        number,_ = section_five(text)
        if include_local_examples and view['id'] and number is not None and self.confirmed:
            add('镜序_文案到镜头选片方案.md · 第五节',self.confirmed[number])
        def related(previous):
            if key(previous)==key(text):return True
            prior=self.lookup(previous)
            return bool(view['id'] and prior['id']==view['id'] and prior['polarity']==view['polarity'])
        if include_local_examples:
            for previous, example, source in self.examples:
                if related(previous): add(source,example)
        for r in records:
            if related(r['text']): add('slot_reviews/'+r['id'],r['verdict']+' · '+r['fact'])
        return list(options.values())


# 只合并能核对动作和对象的同义表述。其他措辞保留整段，靠相同事实累计。
FACTS = {
    '举尺测量尺寸':r'(?:举尺|用卷尺|用尺|拉尺|用激光尺|拿卷尺).{0,5}(?:测量|量出|读数|测距)',
    '两人合力搬动家具':r'(?:两人|两名工人|二人).{0,6}(?:搬|挪|抬).{0,4}(?:家具|床垫|大件)',
    '擦拭台面':r'(?:擦拭|擦洗|擦净|擦).{0,3}(?:厨房台面|台面)',
    '面向镜头抬手招呼':r'(?:面对镜头|面向镜头|正对镜头).{0,4}(?:抬手|挥手)',
}

def fact_key(text):
    clean=key(text)
    # 相同的泛评（如“效果不错”）不能累计为可见事实。没有稳定动作/对象词时留在单次审核里。
    visible=r'搬|抬|挪|举尺|测量|量尺|读数|卷尺|安装|接线|拆|砸|敲|铲|清扫|擦|洗|卷起|铺|贴|批刮|滚涂|刷|挥手|抬手|招手|握手|开桶|揭膜|搅拌|泼水|弯折|刮擦|家具|床垫|台面|柜门|瓷砖|踢脚线|水槽|龙头|地板|门框|浴柜|油渍|砖缝|霉斑|围挡|保护膜|管线|工具箱|工作服|样板|桶盖|激光尺'
    if not re.search(visible,clean) or re.search('没[有做看]|未|不|缺少',clean):return ''
    matches=[name for name,pattern in FACTS.items() if re.search(pattern,clean)]
    if re.search('搬出|搬离|抬出|挪出|往外|出门|入户|搬入|搬进',clean):
        return clean
    return matches[0] if len(matches)==1 else clean


def matches_fact(rule, text):
    if not text:return False
    # 逐个分句核对，含否定的文字不当正面命中。
    for part in re.split('[，。；、,;\n]',text):
        if re.search('没|未|不|缺少|缺乏',part):continue
        if rule['fact_key'] in key(part) or fact_key(part)==rule['fact_key']:return True
    return False


def add_rules(db, run, result, state):
    if not state['complete'] or len(result['items'])!=3 or len(state['chosen'])!=1:return
    current=state['records'][state['chosen'][0]]
    if not current.get('extra_fact') or not current.get('view_id'):return
    action=fact_key(current['extra_fact'])
    if not action:return
    db.execute('CREATE TABLE IF NOT EXISTS viewpoint_rules (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    from slot_review import state as review_state
    eligible=[]
    for other,payload,raw in db.execute('SELECT id,payload,result FROM runs ORDER BY rowid'):
        view=json.loads(payload).get('viewpoint') or {}
        if not view.get('id'):continue
        batch=json.loads(raw)
        if len(batch.get('items',[]))!=3 or not batch.get('viewpoint_review'):continue
        s=state if other==run else review_state(db,other,batch)
        if not s['complete'] or len(s['chosen'])!=1:continue
        r=s['records'][s['chosen'][0]]
        if r.get('extra_fact') and fact_key(r['extra_fact'])==action:
            eligible.append((view,r))
    # 相同事实、相同主张只发布一次；两个记录须确实勾过同一个原因码。
    existing=next((r for r in read_rules(db) if r['fact_key']==action and r['code'] in current['codes']),None)
    for code in ([existing['code']] if existing else sorted(current['codes'])):
        evidence={}
        for view,r in eligible:
            if code in r['codes']:
                evidence.setdefault(view['id'],dict(view=view['id'],category=view['category'],review=r['id'],fact=r['extra_fact']))
        if len(evidence)<2:continue
        rid=hashlib.sha256((code+'\0'+action).encode()).hexdigest()[:24]
        facts=list(evidence.values())
        rule=dict(id=rid,code=code,fact_key=action,example=facts[0]['fact'],categories=sorted({f['category'] for f in facts}),evidence=facts)
        db.execute('INSERT OR REPLACE INTO viewpoint_rules VALUES(?,?)',(rid,json.dumps(rule,ensure_ascii=False)))
        return


def read_rules(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='viewpoint_rules'").fetchone():return []
    return [json.loads(r[0]) for r in db.execute('SELECT data FROM viewpoint_rules ORDER BY rowid')]


def atomic_text(path, text):
    if path.is_file() and path.read_bytes()==text.encode():return
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        temp=Path(f.name)
        f.write(text.encode())
    try:os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def publish(db, directory, plan):
    # 调用方持有数据库写锁，两个进程按同一顺序投影；重复保存可修复中断的文件写入。
    rules=read_rules(db)
    if not rules:return
    directory.mkdir(parents=True,exist_ok=True)
    atomic_text(directory/'选片规律.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rules))
    document=plan.read_bytes().decode('utf-8')
    for rule in rules:
        mark='<!-- 选片规律 '+rule['id']+' -->'
        if mark not in document:
            document=document.rstrip()+'\n\n'+mark+'\n- '+ '、'.join(rule['categories'])+'选片时，优先找能看见「'+rule['example']+'」的片段。（'+ '、'.join(e['view'] for e in rule['evidence'])+'）\n'
    atomic_text(plan,document)

