"""本机自动初标与人工核对共用正式工作簿的逐条标注页。"""
import json
import os
import re
import tempfile
import time
import shutil
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import structured_selection as structured
from structured_selection import dataset, norm, read_tables
from copy_viewpoints import key as sentence_key

NATURES=('直接展示','语境承接','需事实依据','需上下文')
POLARITIES=('肯定','否定','需上下文')


def percentage_hook(text):
    """仅识别独立的受众开场句。含价格、工期或施工结论的整句仍按原数字匹配。"""
    return re.fullmatch(r'\s*(?:\d+(?:\.\d+)?\s*[%％]|百分之[零一二三四五六七八九十百点]+)\s*的人(?:都)?还不知道[，。！!？?\s]*',text)


def default_clean_book(root):
    root=Path(root)
    return root.with_name('镜序素材清洗与分类_云端.xlsx') if root.suffix=='.xlsx' else root/'修订产出/镜序素材清洗与分类_可见事实修订.xlsx'


def picture_names(root,clean_book=None):
    path=Path(clean_book) if clean_book is not None else default_clean_book(root)
    rows=read_tables(path,path.stat().st_mtime_ns,'标签字典')['标签字典']
    return {r['标签']:r['名称'] for r in rows if r['维度']=='画面类型'}


def draft(root,text,view,following=()):
    if not isinstance(text,str) or not 1<=len(text.strip())<=2000:
        raise ValueError('请选择一条有效字幕')
    if (view.get('entry_id') and view['primary'] and view['status']!=structured.AUTO_STATUS) or view['alternatives_by_id']:
        raise ValueError('当前字幕已有主类型或对应多个观点，请核对当前记录')
    path=structured.book_path(root)
    stamp=path.stat().st_mtime_ns
    tables=read_tables(path,stamp)
    old=dataset(root)[0].get(view.get('entry_id'))
    row=old[0] if old else {}
    sentence=row.get('代表句',text.strip())
    categories={r['类别条件编号']:r for r in tables['类别条件']}
    rules=[r for r in tables['逐句条件'] if norm(r['文案原句'])==norm(sentence)]
    related=(view.get('structured') or [{}])[0]
    category=row.get('类别条件编号','')
    rule_categories={r['观点类别'] for r in rules}
    if not category and len(rule_categories)==1:
        category=next((k for k,r in categories.items() if r['素材类别'] in rule_categories),'')
    if category and related.get('类别条件编号')!=category:related={}
    template=row or related
    form=dict(category=category or template.get('类别条件编号',''),nature=template.get('对应性质') or (rules[0]['对应性质'] if rules else '需上下文'),
              polarity=template.get('肯否','需上下文'),primary='、'.join(structured.codes(template.get('主画面类型',''))),
              alternative='、'.join(structured.codes(template.get('备选画面类型',''))),
              action=template.get('必须看见的动作',''),limit=template.get('禁用与限制',''))
    reference_id=''
    if (not category or category=='T07-9') and not rules and not form['primary'] and percentage_hook(sentence):
        examples=[r for r in tables['逐条标注'] if r['类别条件编号']=='T07-9' and percentage_hook(r['代表句'])
                  and r['主画面类型'] and r['标注状态']!=structured.AUTO_STATUS]
        choices={(tuple(structured.codes(r['主画面类型'])),r['对应性质'],r['肯否']) for r in examples}
        if len(choices)==1:
            sample=examples[0]
            reference_id=sample['观点ID']
            form.update(category='T07-9',nature=sample['对应性质'],polarity=sample['肯否'],
                        primary='、'.join(structured.codes(sample['主画面类型'])),
                        alternative='、'.join(structured.codes(sample['备选画面类型'])),
                        action=sample['必须看见的动作'],limit=sample['禁用与限制'])
            if form['primary']=='V01':
                form['action']='人物面向镜头开口讲述，用短镜头引出下文。'
            form['limit']='镜头只承接口播，原句中的人数比例须另有依据。'+form['limit']
    if category=='T07-23' and '过度翻新' in sentence and '不' in sentence and following and '砸' in following[0] and '瓷砖' in following[0]:
        form.update(nature='语境承接',polarity='否定',primary='V12',action='看见改造前卫生间的原有墙砖和洁具，能辨认原有空间和部位。',
                    limit='开场交代卫生间旧态。单凭旧态镜头不能证明基层可保留或无需翻新，不把砸砖拍成推荐做法。')
    return dict(id=row.get('观点ID',''),text=sentence,version=str(stamp),form=form,categories=categories,reference_id=reference_id,
                line_ids=[r['记录ID'] for r in rules],natures=NATURES,polarities=POLARITIES)


def picture_clause(rule,field,names):
    """提取画面类型行的明确类型，其他维度的词不作画面类型。"""
    result=[]
    for line in rule.get(field,'').splitlines():
        if not re.match(r'^[-\s]*画面类型[：:]',line):continue
        if field!='禁止':
            line=re.split(r'；|不得|不要|不能|禁止|反例',line)[0]
        text=line.replace('/','、')
        result.extend(structured.codes(text))
        result.extend(code for code,name in names.items() if name.split('（')[0] in text and code!='V22')
    return list(dict.fromkeys(result))


def apply_entry_rules(root,entry,form,text):
    path=structured.book_path(root)
    tables=read_tables(path,int(entry['version']))
    category=entry['categories'].get(form['category'],{})
    lines=[r for r in tables['逐句条件'] if r['记录ID'] in entry['line_ids']]
    names=picture_names(root)
    basis='、'.join([form['category'],*entry['line_ids']]).strip('、')
    # 分套类别的类别说明同时列出正反例，不能把两个分支合成可选项。
    split=category.get('肯否定')=='是'
    proposed=structured.codes(form['primary'])
    preferred=structured.codes(form['alternative'])
    if split and re.search(r'(?:不拆不砸|不(?:用|再|必|需要)?(?:敲|砸)(?:掉)?(?:瓷)?砖|免拆)',text) and form['category'] in ('T07-14','T07-5'):
        proposed=['V05'];preferred=[c for c in preferred if c!='V08']
    rules=lines or ([category] if category and not split else [])
    contexts=set()
    for rule in lines:
        contexts.update(n for n in NATURES if rule['对应性质'].startswith(n))
    if len(contexts)==1:form['nature']=next(iter(contexts))
    if form['nature'] not in NATURES:form['nature']='需上下文'
    limits=[picture_clause(r,'必须',names) for r in rules]
    limits=[opts for opts in limits if opts]
    allowed=[c for c in limits[0] if all(c in opts for opts in limits)] if limits else []
    banned=set(c for r in [category,*lines] for c in picture_clause(r,'禁止',names))
    if limits:
        preferred_in_rule=[c for r in rules for c in picture_clause(r,'优先',names) if c in allowed]
        proposed=[c for c in proposed if c in allowed] or list(dict.fromkeys(preferred_in_rule))
        if not proposed and (lines or len(allowed)==1):proposed=allowed
    if not proposed and not limits:
        options=[picture_clause(r,'优先',names) for r in rules]
        if len(options)==1 and len(options[0])==1:proposed=options[0]
    if len(contexts)>1 or len({r['观点类别'] for r in lines})>1:
        proposed=[];preferred=[]
    if lines and not entry['id'] and not form['action']:
        actions=[line.partition('：')[2].split('（词表')[0].strip() for r in lines
                 for line in r['必须'].splitlines() if line.startswith('- 主动作：')]
        if actions:form['action']='；'.join(dict.fromkeys(actions))
    if category and not entry['id'] and not form['limit']:
        form['limit']='；'.join(dict.fromkeys(r['画面证明不了的部分'] for r in [*lines,category] if r.get('画面证明不了的部分')))
    form['primary']='、'.join(c for c in proposed if c not in banned)
    form['alternative']='、'.join(c for c in preferred if c not in banned and c not in proposed)
    return basis


def type_codes(value):
    if not isinstance(value,str):raise ValueError('画面类型格式无效')
    codes=list(dict.fromkeys(re.split(r'[、，,\s]+',value.strip()))) if value.strip() else []
    if any(not re.fullmatch('V(0[1-9]|1[0-9]|2[0-4])',c) for c in codes):raise ValueError('画面类型仅支持 V01 至 V24')
    return codes


def automatic(root,text,view,following):
    """在调用方持有写锁时决定补行、追加或复用。"""
    if view['alternatives_by_id']:
        return '对应多个既有观点，保留候选编号待核对。',False
    if view.get('entry_id') and (view['primary'] or view['status']=='人工确认'):
        return '',False
    entry=draft(root,text,view,following)
    form=entry['form']
    category=form['category']
    basis='按结构化标注框架自动入表'
    if not form['primary'] and category and entry['categories'][category]['肯否定']!='是':
        # 只有同类、同肯否方向的既有证据一致时，才迁移主类型。
        examples=[r for r,_,_,_ in dataset(root)[0].values() if r['类别条件编号']==category
                  and r['主画面类型'] and r['标注状态']!=structured.AUTO_STATUS
                  and structured.negative(r['代表句'])==structured.negative(text)]
        options={tuple(structured.codes(r['主画面类型'])) for r in examples}
        if len(options)==1:
            chosen=next(iter(options))
            form['primary']='、'.join(chosen)
            form['alternative']='、'.join(c for c in structured.codes(form['alternative']) if c not in chosen)
            basis=category+' 同类原句的主类型一致'
    reference=apply_entry_rules(root,entry,form,text)
    if not form['primary'] and entry['id']:
        return entry['id']+' 已在表内，当前依据不足以确定主画面类型。',False
    if not entry['id'] and view.get('structured'):
        basis+=' · 参考 '+view['structured'][0]['观点ID']
    if not form['primary']:
        basis='已收录字幕原句，主类型与可见动作待核对'
    if reference:basis+=' · '+reference
    if entry['reference_id']:basis+=' · 同句式参考 '+entry['reference_id']
    if not entry['id'] and not form['action']:
        form['action']='待核对原句的可见动作与对象：'+text
    if not entry['id'] and not form['limit']:
        form['limit']='可见证据待核对，不把语境画面当作事实证明。'
    ident=save(root,entry,form,'镜序',automatic_basis=basis)
    message='已自动补齐 '+ident if entry['id'] else '已自动新增 '+ident
    return message+('，主画面类型待定。' if not form['primary'] else '，'+structured.AUTO_STATUS+'。'),True


def save(root,entry,form,reviewer,automatic_basis='',*,clean_book=None):
    path=structured.book_path(root)
    if str(path.stat().st_mtime_ns)!=entry['version']:raise ValueError('表格已更新，请重新打开草稿')
    if not isinstance(form,dict):raise ValueError('缺少入表草稿')
    primary,alt=type_codes(form.get('primary')),type_codes(form.get('alternative',''))
    if (not primary and not automatic_basis) or set(primary)&set(alt):raise ValueError('请选择主画面类型，主型和备选须分开')
    rows=read_tables(path,int(entry['version']))['逐条标注']
    fill_only=any(r['观点ID']==entry['id'] and r['类别条件编号'] for r in rows)
    for value in ([reviewer] if fill_only or automatic_basis else [form.get('action'),form.get('limit'),reviewer]):
        if not isinstance(value,str) or not value.strip() or len(value)>2000 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):
            raise ValueError('请填写可见动作、禁用与限制和确认人')
    if not fill_only and not automatic_basis and (form['action'].strip()=='见原句' or form['action'].startswith('先核对原文前后句')):
        raise ValueError('请把待定说明改成镜头里必须看见的动作或对象')
    records,windows=dataset(root)
    if not entry['id'] and any(s==norm(entry['text']) for _,s,_,_ in records.values()):
        raise ValueError('表内已有相同原句，请先核对既有观点')
    ident=entry['id'] or 'P%04d'%(1+max(int(i[1:]) for i in records if re.fullmatch(r'P\d+',i)))
    position=next((i for i,r in enumerate(rows,2) if r['观点ID']==ident),len(rows)+2)
    count=len({r['原片ID'] for r in windows if r['画面类型'] in primary and r['原片ID']})
    names=picture_names(root,clean_book)
    def named(codes):
        return '；'.join(code+' · '+names[code] for code in codes)
    status=structured.AUTO_STATUS if automatic_basis else '人工确认'
    if fill_only:
        values=list(rows[position-2].values())
        values[5:7]=[named(primary),named(alt)]
        values[9]=status
        values[12]=count
        if automatic_basis:values[14]='；'.join(filter(None,[values[14],automatic_basis]))
    else:
        category=entry['categories'].get(form.get('category'))
        if (not category and not automatic_basis) or form.get('nature') not in NATURES or form.get('polarity') not in POLARITIES:
            raise ValueError('请核对素材类别、对应性质和肯否')
        values=[ident,entry['text'],category['素材类别'] if category else '新增观点',form['nature'],form['polarity'],named(primary),named(alt),
                form['action'].strip(),form['limit'].strip(),status,form['category'],'、'.join(entry['line_ids']),count,
                '按本句动作、肯否与禁用项逐段核对',automatic_basis or '工作台确认入表 · '+reviewer.strip()]
    replace_row(path,position,values,entry['version'])
    return ident


def update_primary(root, ident, version, selected, *, clean_book=None):
    path=structured.book_path(root)
    stamp=path.stat().st_mtime_ns
    if str(stamp)!=version:raise ValueError('共用文案表已更新，请刷新后重新核对')
    if not isinstance(selected,list) or not selected or any(not isinstance(c,str) or not re.fullmatch(r'V(?:0[1-9]|1[0-9]|2[0-4])',c) for c in selected):
        raise ValueError('请至少勾选一种有效画面类型')
    rows=read_tables(path,stamp,'逐条标注')['逐条标注']
    matches=[(i,row) for i,row in enumerate(rows,2) if row['观点ID']==ident]
    if len(matches)!=1:raise ValueError('当前代表句没有唯一原行')
    position,row=matches[0]
    names=picture_names(root,clean_book)
    value='；'.join(c+' · '+names[c] for c in dict.fromkeys(selected))
    if value!=row['主画面类型']:
        replace_row(path,position,{list(row).index('主画面类型'):value},version)


def _text(value,label,limit=2000,required=True):
    if not isinstance(value,str) or len(value)>limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):
        raise ValueError(label+'无效')
    value=value.strip()
    if required and not value:raise ValueError('请填写'+label)
    return value


PENDING_HEADERS=('字幕原句','状态','提交人','提交时间')
AUDIT_HEADERS=('修改时间','修改人','观点ID','代表句','修改前','修改后')


def pending_contains(root,text):
    path=structured.book_path(root)
    rows=read_tables(path,path.stat().st_mtime_ns).get('待标注',[])
    key=sentence_key(text)
    return bool(key) and any(sentence_key(r['字幕原句'])==key for r in rows)


def enqueue_pending(root,text,reviewer):
    text=_text(text,'字幕原句')
    reviewer=_text(reviewer,'提交人',128)
    path=structured.book_path(root)
    stamp=path.stat().st_mtime_ns
    tables=read_tables(path,stamp)
    key=sentence_key(text)
    if not key:raise ValueError('请选择有文字的字幕')
    if any(sentence_key(r['代表句'])==key for r in tables['逐条标注']):
        raise ValueError('这句已在逐条标注中，请打开代表句修订')
    if pending_contains(root,text):
        return False
    row=[text,'待标注',reviewer,datetime.now().astimezone().isoformat(timespec='seconds')]
    _write_workbook(path,str(stamp),[('待标注',None,row,PENDING_HEADERS)],backup=True)
    return True


def edit_draft(root,ident):
    path=structured.book_path(root)
    stamp=path.stat().st_mtime_ns
    tables=read_tables(path,stamp)
    matches=[r for r in tables['逐条标注'] if r['观点ID']==ident]
    if len(matches)!=1:raise ValueError('当前代表句没有唯一原行')
    row=matches[0]
    form=dict(category=row['类别条件编号'],nature=row['对应性质'],polarity=row['肯否'],
              primary='、'.join(structured.codes(row['主画面类型'])),
              alternative='、'.join(structured.codes(row['备选画面类型'])),
              action=row['必须看见的动作'],limit=row['禁用与限制'])
    return dict(id=ident,text=row['代表句'],version=str(stamp),form=form,
                categories={r['类别条件编号']:r for r in tables['类别条件']},
                natures=NATURES,polarities=POLARITIES)


def revise(root,ident,version,form,reviewer,*,clean_book=None):
    path=structured.book_path(root)
    entry=edit_draft(root,ident)
    if entry['version']!=version:raise ValueError('共用文案表已更新，请重新打开代表句')
    reviewer=_text(reviewer,'修改人',128)
    if not isinstance(form,dict):raise ValueError('缺少修订标签')
    primary=type_codes(form.get('primary'))
    alt=type_codes(form.get('alternative',''))
    if set(primary)&set(alt):raise ValueError('主型和备选须分开')
    category=form.get('category')
    if not isinstance(category,str) or category not in entry['categories'] and (category or entry['form']['category']):
        raise ValueError('请选择标注表已有的素材类别')
    if form.get('nature') not in NATURES or form.get('polarity') not in POLARITIES:
        raise ValueError('请核对对应性质和肯否')
    tables=read_tables(path,int(version))
    row=next(r for r in tables['逐条标注'] if r['观点ID']==ident)
    names=picture_names(root,clean_book)
    if any(code not in names for code in primary+alt):raise ValueError('画面类型不在当前镜序标签字典中')
    def named(codes):return '；'.join(c+' · '+names[c] for c in codes)
    fields={'类别条件编号':category,'素材类别':entry['categories'][category]['素材类别'] if category else row['素材类别'],
            '对应性质':form['nature'],'肯否':form['polarity'],'主画面类型':named(primary),'备选画面类型':named(alt),
            '必须看见的动作':_text(form.get('action',''),'可见动作',required=False),
            '禁用与限制':_text(form.get('limit',''),'禁用与限制',required=False),'标注状态':'人工确认'}
    if primary!=structured.codes(row['主画面类型']):
        fields['同类型粗标原片数']=len({r['原片ID'] for r in tables['粗标秒段'] if r['原片ID'] and r['画面类型'] in primary})
    changed={k:v for k,v in fields.items() if row[k]!=str(v)}
    if not changed:return
    before={k:row[k] for k in changed}
    audit=[datetime.now().astimezone().isoformat(timespec='seconds'),reviewer,ident,row['代表句'],
           json.dumps(before,ensure_ascii=False),json.dumps(changed,ensure_ascii=False)]
    _write_workbook(path,version,[('逐条标注',ident,changed,None),('人工修订记录',None,audit,AUDIT_HEADERS)],backup=True)


def replace_row(path,position,values,version):
    _write_workbook(path,version,[('逐条标注',position,values,None)])


def _column_name(index):
    name=''
    index+=1
    while index:
        index,letter=divmod(index-1,26)
        name=chr(65+letter)+name
    return name


def _write_cells(body,ns,position,values):
    row=body.find(f"{ns}row[@r='{position}']")
    if row is None:row=ET.SubElement(body,ns+'row',{'r':str(position)})
    for col,value in (values.items() if isinstance(values,dict) else enumerate(values)):
        ref=(col if isinstance(col,str) else _column_name(col))+str(position)
        cell=row.find(f"{ns}c[@r='{ref}']")
        if cell is None:cell=ET.SubElement(row,ns+'c',{'r':ref})
        for child in list(cell):cell.remove(child)
        cell.set('t','n' if isinstance(value,int) else 'inlineStr')
        if isinstance(value,int):ET.SubElement(cell,ns+'v').text=str(value)
        else:ET.SubElement(ET.SubElement(cell,ns+'is'),ns+'t').text=value
    row[:]=sorted(row,key=lambda c:(len(c.get('r','').rstrip('0123456789')),c.get('r','').rstrip('0123456789')))


def _parts_for_rows(src,updates):
    book='xl/workbook.xml';rels='xl/_rels/workbook.xml.rels';types='[Content_Types].xml'
    main,links,mimes=[ET.fromstring(src.read(p)) for p in (book,rels,types)]
    ns=main.tag.split('}')[0]+'}'
    relation='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    sheets=main.find(ns+'sheets')
    edits={}
    strings=None
    def cell_text(cell):
        nonlocal strings
        if cell is None:return ''
        if cell.get('t')=='s':
            if strings is None:
                strings=[''.join(x.text or '' for x in item.iter(ns+'t'))
                         for item in ET.fromstring(src.read('xl/sharedStrings.xml'))]
            return strings[int(cell.findtext(ns+'v'))]
        if cell.get('t')=='inlineStr':return ''.join(x.text or '' for x in cell.iter(ns+'t'))
        return cell.findtext(ns+'v','')
    for title,position,values,headers in updates:
        sheet=next((s for s in sheets if s.get('name')==title),None)
        if sheet is None:
            if not headers:raise ValueError('文案表缺少工作表：'+title)
            number=max(int(s.get('sheetId')) for s in sheets)+1
            used={r.get('Id') for r in links}
            while 'rId'+str(number) in used or f'xl/worksheets/sheet{number}.xml' in src.namelist():number+=1
            rid='rId'+str(number);target=f'xl/worksheets/sheet{number}.xml'
            ET.SubElement(sheets,ns+'sheet',dict(name=title,sheetId=str(number),**{'{'+relation+'}id':rid}))
            ET.SubElement(links,links[0].tag,dict(Id=rid,Type=relation+'/worksheet',Target=target[3:]))
            ET.SubElement(mimes,mimes.tag.replace('}Types','}Override'),dict(PartName='/'+target,
                          ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'))
            edits.update({book:main,rels:links,types:mimes})
            xml=ET.Element(ns+'worksheet')
            views=ET.SubElement(xml,ns+'sheetViews')
            view=ET.SubElement(views,ns+'sheetView',dict(workbookViewId='0'))
            ET.SubElement(view,ns+'pane',dict(ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen'))
            cols=ET.SubElement(xml,ns+'cols')
            for i,h in enumerate(headers,1):
                width=64 if h in ('字幕原句','代表句','修改前','修改后') else 28 if '时间' in h else 16
                ET.SubElement(cols,ns+'col',dict(min=str(i),max=str(i),width=str(width),customWidth='1'))
            body=ET.SubElement(xml,ns+'sheetData')
            _write_cells(body,ns,1,headers)
        else:
            rid=sheet.get('{'+relation+'}id')
            target=next(r.get('Target').lstrip('/') for r in links if r.get('Id')==rid)
            if not target.startswith('xl/'):target='xl/'+target
            xml=ET.fromstring(src.read(target))
            body=xml.find(ns+'sheetData')
            cols={cell_text(c):c.get('r').rstrip('0123456789') for c in body[0].findall(ns+'c')}
            if headers and any(cols.get(h)!=chr(65+i) for i,h in enumerate(headers)):
                raise ValueError(title+'表头已变化，请核对后重试')
            if isinstance(position,str):
                # 人工整理过的表可能有空白行；按真实观点 ID 和单元格地址写回。
                id_col=cols['观点ID']
                actual=[int(r.get('r')) for r in body if
                        cell_text(r.find(f"{ns}c[@r='{id_col}{r.get('r')}']"))==position]
                if len(actual)!=1:raise ValueError('当前代表句没有唯一原行')
                position=actual[0]
                values={cols[h]:v for h,v in values.items()}
        if position is None:position=max((int(r.get('r')) for r in body),default=0)+1
        _write_cells(body,ns,position,values)
        dim=xml.find(ns+'dimension')
        if dim is not None:
            first,_,end=dim.get('ref','A1').partition(':')
            last=re.fullmatch(r'([A-Z]+)(\d+)',end or first)
            if last and position>int(last[2]):
                dim.set('ref',f'{first}:{last[1]}{position}')
        edits[target]=xml
    return {p:ET.tostring(xml,encoding='utf-8',xml_declaration=True) for p,xml in edits.items()}


def _write_workbook(path,version,updates,backup=False):
    # 原子替换整包，其他页、样式、冻结窗格和原工作簿关系均保留。
    fd,name=tempfile.mkstemp(prefix='.镜序入表-',suffix='.xlsx',dir=path.parent)
    os.close(fd)
    try:
        with ZipFile(path) as src, ZipFile(name,'w') as out:
            edits=_parts_for_rows(src,updates)
            for part in src.infolist():
                out.writestr(part,edits.pop(part.filename) if part.filename in edits else src.read(part))
            for part,data in edits.items():out.writestr(part,data)
        if backup:
            original=path.with_name(path.stem+'_首次人工入表前备份.xlsx')
            if not original.exists():
                fd,tmp=tempfile.mkstemp(prefix='.镜序备份-',dir=path.parent)
                os.close(fd)
                try:
                    shutil.copy2(path,tmp)
                    os.replace(tmp,original)
                finally:
                    Path(tmp).unlink(missing_ok=True)
        # Windows 预览器可能瞬时持有新生成的文件。每次重试都检查原表版本。
        for delay in (0, .08, .2, .5):
            if delay:time.sleep(delay)
            if str(path.stat().st_mtime_ns)!=version:raise ValueError('工作簿已变化，请重新核对草稿')
            try:
                os.replace(name,path)
                break
            except PermissionError:
                if delay==.5:raise
    except PermissionError as exc:
        raise ValueError('工作簿正被占用或不可写，请关闭表格后重试') from exc
    finally:
        Path(name).unlink(missing_ok=True)
