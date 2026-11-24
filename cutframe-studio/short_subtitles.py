"""只在包含当前字幕的连续窗口里匹配完整观点，变量位置由表中原句决定。"""
import re
from collections import defaultdict
from pathlib import Path

CITIES=set((Path(__file__).parent/'rules/选片城市词.txt').read_text('utf-8').split())
CITY_TERMS='|'.join(sorted(CITIES,key=lambda s:(-len(s),s)))
HAN=r'[\u3400-\u9fff]'
NAME=rf'{HAN}{{1,2}}阿姨'
# 地址只能从地名开头匹配；“武汉的硚口区”的连接词和“住江汉区”的动词保留。
DISTRICT=rf'(?!(?:哪个|哪些|各个|每个|哪一|这一|住|在|了|的)){HAN}{{2,3}}区'
DISTRICT_SITE=rf'(?:(?:^|(?<=[给在到住市的])|(?<=到了)|(?<=武汉)){DISTRICT}|(?:硚口|江岸|武昌|江汉|金牛)区)'
GENERIC_AREAS=('小区','评论区','生活区','施工区','保护区','各区','老城区')
PLACE=rf'(?:{CITY_TERMS}|{DISTRICT_SITE})'
# 「武汉的张阿姨」和「金牛区一位张阿姨」的连接词只在完整客户地址位置等价。
SLOTS=re.compile(rf'(?P<address>{PLACE})(?=(?:的|一位){NAME})|'
                 rf'(?P<link>(?:的|一位))(?={NAME})|(?P<city>{CITY_TERMS})(?!方|大的)|(?P<district>{DISTRICT_SITE})|'
                 rf'(?P<host>[阿啊]文)|(?P<client>(?:^|(?<=给)|(?<=的)|(?<=一位)|(?<=区)){NAME}|[张刘李王陈赵孙周吴郑]阿姨)|'
                 r'(?P<area>[0-9]+(?:\.[0-9]+)?|[一二两三四五六七八九十])(?P<unit>平方米|平方大(?=的)|平方)')
DIGITS='零一二三四五六七八九十'
PARTICLES={'的','了','啊','呀','呢','吧','嘛','哦','么','啦'}

def meaning_key(sentence):
    """只归并可核对的口播表达；数字、施工动作、材料、否定与使用条件参与整句比对。"""
    sentence=re.sub(r'(?<=点个)(免费([的])?)?小爱心',r'\1爱心',sentence)
    sentence=re.sub(r'^(?:[啊阿]文)?全程不需要[你您]动手$', '全程不需要你动手',sentence)
    sentence=re.sub(r'完工后?(?:即可|就能)(?:正常)?使用','完工即可使用',sentence)
    sentence=sentence.replace('没有瓷砖缝的升级效果','没有瓷砖缝的升级')
    return re.sub(r'^(?:改造|做出来)(墙地一体无缝)$',r'\1',sentence)


class SentencePattern:
    def __init__(self, sentence):
        pieces=[]
        self.fields=[]
        self.maximum=len(sentence)
        end=0
        for slot in SLOTS.finditer(sentence):
            kind=slot.lastgroup
            original=slot.group()
            if kind=='link' and not (end==slot.start() and self.fields and self.fields[-1][0]=='address'):
                continue
            if kind in ('district','address') and original.endswith(GENERIC_AREAS):
                continue
            if kind=='client' and original in ('叔叔阿姨','一位阿姨'):continue
            pieces.append(re.escape(sentence[end:slot.start()]))
            if kind in ('address','city','district'):
                size=4 if kind!='city' else 3
                expr={'address':rf'{DISTRICT}|{HAN}{{2,3}}','city':rf'{HAN}{{2,3}}','district':DISTRICT}[kind]
            elif kind=='link':expr,size='的|一位',2
            elif kind=='client':expr,size=NAME,4
            elif kind=='host':expr,size='[啊阿]文',2
            else:
                # 比较实际数值，只接受面积单位的等值读法，不吞掉数字、面积或施工对象。
                number=slot['area']
                if number=='两':number='二'
                if number in DIGITS:number=str(DIGITS.index(number))
                forms=[re.escape(number)]
                if number.isascii() and number.isdigit() and int(number)<=10 and str(int(number))==number:
                    forms.append(DIGITS[int(number)])
                    if number=='2':forms.append('两')
                expr='(?:'+'|'.join(forms)+')(?:平方米|平方大(?=的)|平方)'
                size=len(number)+3
            pieces.append('('+expr+')')
            self.fields.append((kind,original))
            self.maximum+=max(0,size-len(original))
            end=slot.end()
        pieces.append(re.escape(sentence[end:]))
        self.pattern=re.compile(''.join(pieces)) if self.fields else None

    def covers(self,text,start,end):
        match=self.pattern.fullmatch(text)
        if not match:return False
        width=end-start
        replacements={}
        for i,(kind,original) in enumerate(self.fields,1):
            value=match[i]
            if kind=='city' and value not in CITIES:return False
            if kind=='address' and value not in CITIES and not re.fullmatch(DISTRICT,value):return False
            if kind in ('address','district') and value.endswith(GENERIC_AREAS):return False
            if kind=='client' and value in ('叔叔阿姨','一位阿姨'):return False
            if replacements.setdefault((kind,original),value)!=value:return False
            left,right=match.span(i)
            lo=max(start,left);hi=min(end,right)
            if lo<hi:
                # 按原句槽位长度折算本条贡献的连续字符，连接词和姓名不能靠展开的字数凑四字。
                width+=(hi-left)*len(original)//(right-left)-(lo-left)*len(original)//(right-left)-(hi-lo)
        return width>=4


class ShortSubtitleIndex:
    def __init__(self, exact):
        self.exact=exact
        self.max_length=max(map(len,exact),default=0)
        self.by_length=defaultdict(list)
        for sentence,ids in exact.items():
            template=SentencePattern(sentence)
            if template.pattern:
                self.max_length=max(self.max_length,template.maximum)
                for length in range(max(4,len(sentence)-3*len(template.fields)),template.maximum+1):
                    self.by_length[length].append((template,ids))

    def find(self,current,before,after):
        if len(current)<4:return {}
        # 只取完整相邻字幕。以标注表中最长的整句为上限，不跨过中间字幕或截掉其中几个字。
        lefts=[(0,'')]
        for i,piece in enumerate(reversed(before),1):
            prefix=piece+lefts[-1][1]
            if not piece or len(prefix)+len(current)>self.max_length:break
            lefts.append((-i,prefix))
        matches=[]
        for left,prefix in lefts:
            joined=prefix+current
            for right in range(len(after)+1):
                if right:
                    if not after[right-1]:break
                    joined+=after[right-1]
                if len(joined)>self.max_length:break
                ids=set(self.exact.get(joined,()))
                for template,owners in self.by_length[len(joined)]:
                    if template.covers(joined,len(prefix),len(prefix)+len(current)):ids.update(owners)
                if ids:matches.append((left,right,ids))
        # 完整长句已经解释其内的短称谓（如“武汉阿文”）。交叉窗口和同窗多 ID 仍须列出全部歧义。
        owners={}
        for left,right,ids in matches:
            if (left==right==0 and current[:-2] in CITIES and current[-2:] in ('阿文','啊文')
                    and any(a<0 or b>0 for a,b,_ in matches)):
                continue
            for ident in sorted(ids):owners.setdefault(ident,(left,right))
        return owners

