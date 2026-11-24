"""分类行归一化、秒段记录键及原片摘要工具。"""
import hashlib
import re
from pathlib import Path

def split_types(text):
    parts=[];start=0;depth=0
    for i,ch in enumerate(text):
        if ch in '（(':depth+=1
        elif ch in '）)':depth=max(0,depth-1)
        elif ch=='、' and depth==0:parts.append(text[start:i].strip());start=i+1
    parts.append(text[start:].strip());return [x for x in parts if x]

def parse_types(text):
    result=[]
    for part in split_types(text.split('；',1)[0]):
        match=re.fullmatch(r'(.+?)\s+(\d+)',part)
        if not match:raise ValueError('无法解析画面类型及次数：'+part)
        name,count=match.groups();name='其他' if name=='其他（模糊画面、叠大字等）' else name
        result.append(dict(type=name,count=int(count)))
    return result

def full_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def stable_source_key(source,row_number):
    # 从原字段重建，重跑不会在旧键后重复追加。
    return f"{source.get('id')}:{source.get('start')}-{source.get('end')}:{source.get('工序','')}:#{row_number}"

def normalize_fact(row):
    row=dict(row);start,end=row.get('起秒'),row.get('止秒');source=row.get('来源文件','')
    if start is None or end is None:
        if source.endswith('目视纠正.jsonl'):row.update(确认级别='原片级',无起止秒=True)
        elif '对照表.md#明细' in source and start is None and end is None:row.update(确认级别='格子级',无起止秒=True)
        elif row.get('事实编号')=='F0191':row['无起止秒']=True
    if row.get('事实编号')=='F0018' and '本片段不是微陶泥' in str(row.get('内容',{}).get('product_identity','')):row['是否反例']=True
    return row

def normalize_coarse(row,source_line=None):
    row=dict(row)
    if row.get('记录种类')=='施工镜头':
        if source_line is None:raise ValueError('施工镜头必须有源行号')
        row['来源条目标识']=stable_source_key(row['原字段'],source_line)
    elif row.get('记录种类')=='用途片段':
        original=row.get('原来源条目标识',row['来源条目标识']);row['原来源条目标识']=original;row['来源条目标识']=row['粗标编号']+'#'+original
    return row

