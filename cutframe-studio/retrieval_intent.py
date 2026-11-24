"""本地画面意图与分路召回；目录只作线索，不认证人物或产品。"""
from ai_discovery import rank_catalog

ACTION_TERMS=('批刮','取料','滚涂','罩面','打磨','拆除','拆砸','清洁','擦地','覆膜','搅拌','铲除')
PERSON_TERMS=('人物','出镜','讲解','沟通','上门','量房','团队')
PRODUCT_TERMS=('微陶泥','材料','产品','包装','材料桶')


def plan_intent(text,need=''):
    q=text+' '+need
    actions=[x for x in ACTION_TERMS if x in q]
    if actions:kind='action';terms=actions
    elif any(x in q for x in PERSON_TERMS+('他就是','我就是','阿文','改造大王')):
        kind='person';terms=list(PERSON_TERMS)
    elif any(x in q for x in PRODUCT_TERMS):kind='product';terms=list(PRODUCT_TERMS)
    else:kind='general';terms=[]
    return dict(kind=kind,label={'person':'人物介绍','action':'施工动作','product':'产品展示','general':'通用场景'}[kind],
                terms=terms,identity_policy='身份只按已确认源片段，不从目录或外观推断',
                visual_goal=('人物清楚出镜、现场讲解或沟通；宣传修辞不要求视觉证明，但不得冒认主体身份' if kind=='person' else '直接呈现本句目标，动作和施工部位分开判断'))


def rank_by_intent(assets,text,need='',context=''):
    intent=plan_intent(text,need)
    ranked=rank_catalog(assets,text,need+' '+' '.join(intent['terms']),context)
    if intent['kind']!='general':
        # 相关目录先于其他目录；不把多样性排在相关性前面。
        ranked.sort(key=lambda a:0 if any(t in a['rel']+' '+a['name'] for t in intent['terms']) else 1)
    return ranked,intent


def rejection(pred,valid):
    if valid:return None
    if pred.get('segments'):return ('invalid_segment','返回片段未通过时长、边界或确定性校验')
    codes={'category_mismatch':'画面类别不符','identity_unknown':'身份依据不足','action_mismatch':'动作不符',
           'duration_short':'目标画面时长不足','unclear':'画面或动作看不清','semantic_mismatch':'不符合画面要求'}
    code=pred.get('reject_code');detail=pred.get('evidence')
    if code in codes and isinstance(detail,str) and detail.strip():return code,codes[code]+'：'+detail[:500]
    return 'missing_reason','模型返回空候选但未给出有效拒绝理由；不能认定素材不合适'
