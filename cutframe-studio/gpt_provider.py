"""GPT抽帧调用、规则快照和跨进程预算；不上传原视频。"""
import base64
import hashlib
import http.client
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.request
import urllib.error
import uuid
from contextlib import contextmanager
from pathlib import Path


class BudgetStop(ValueError):
    pass


class GPTRequestError(ValueError):
    def __init__(self,message,diagnostic):
        super().__init__(message)
        self.diagnostic=diagnostic


def open_tracked_request(req, mark):
    """区分TLS建立前和正文发送后故障；不重试付费POST，保持证书验证。"""
    class TrackedConnection(http.client.HTTPSConnection):
        def connect(self):
            mark('建立TLS连接')
            try:
                super().connect()
            except Exception:
                # 代理CONNECT也是握手准备，不是发给模型的POST。
                mark('建立TLS连接')
                raise
            mark('TLS已建立，准备发送请求')
        def send(self, data):
            if self.sock is None:
                self.connect()
            mark('发送HTTP请求')
            return super().send(data)
    class TrackedHandler(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(TrackedConnection,request,context=self._context)
    return urllib.request.build_opener(TrackedHandler()).open(req,timeout=120)


def safe_error(value,key=''):
    text=str(value)
    if key:text=text.replace(key,'[密钥已遮盖]')
    text=re.sub(r'sk-[A-Za-z0-9_-]+','[密钥已遮盖]',text)
    text=re.sub(r'data:image/[^\s\"\']+','[图片数据已遮盖]',text)
    return text[:1500]


def load_rules(path):
    raw = Path(path).read_text('utf-8-sig')
    rule = json.loads(raw)
    if rule.get('model') != 'gpt-6.1-sol':
        raise ValueError('模型变更需同时核验价格与图片额度，当前仅支持gpt-6.1-sol')
    if not rule.get('version') or not isinstance(rule.get('instructions'), list) or not all(isinstance(x, str) for x in rule['instructions']):
        raise ValueError('检索规则缺少版本或instructions列表')
    lim = rule['limits']
    for key, low, high in [('max_sources_per_round',1,100),('max_calls_per_round',1,100),('window_seconds',2,60),('frames_per_window',8,8),('max_image_dimension',640,640),('max_output_tokens',1800,1800)]:
        if not isinstance(lim.get(key), (int,float)) or not low <= lim[key] <= high:
            raise ValueError('检索规则参数无效：'+key)
    # 图像数、分辨率、输出上限固定，预留覆盖该请求上限；不能通过修改规则绕过授权。
    if lim.get('request_reserve_usd') != .08:
        raise ValueError('单次请求须预留0.08美元')
    b = rule['budget']
    if b != dict(total_cap_usd=2.0, previous_reserved_usd=0.0, input_per_million_usd=2.0, output_per_million_usd=10.0):
        raise ValueError('费用配置与已授权预算不符，需明确授权后调整')
    rule['hash'] = hashlib.sha256(raw.encode()).hexdigest()
    return rule


@contextmanager
def budget_db(path):
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, created REAL, reserved REAL, pending INTEGER, data TEXT)')
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def budget_status(path, rule):
    with budget_db(path) as db:
        used, pending = db.execute('SELECT coalesce(sum(reserved),0), coalesce(sum(pending),0) FROM calls').fetchone()
    b = rule['budget']; total = b['previous_reserved_usd'] + used
    return dict(cap_usd=b['total_cap_usd'], reserved_usd=round(total,6), remaining_usd=round(max(0,b['total_cap_usd']-total),6), pending=pending)


def reserve(path, rule, metadata):
    with budget_db(path) as db:
        db.execute('BEGIN IMMEDIATE')
        used, pending = db.execute('SELECT coalesce(sum(reserved),0), coalesce(sum(pending),0) FROM calls').fetchone()
        if pending:
            raise BudgetStop('存在进行中或未核账的GPT请求，请等待完成；异常请求需先核账')
        value = rule['limits']['request_reserve_usd']
        if used + rule['budget']['previous_reserved_usd'] + value > rule['budget']['total_cap_usd'] + 1e-9:
            raise BudgetStop('GPT费用预算不足，已停止；不会自动提高原2美元总额上限')
        key = uuid.uuid4().hex
        db.execute('INSERT INTO calls VALUES(?,?,?,?,?)', (key,time.time(),value,1,json.dumps(metadata,ensure_ascii=False)))
    return key


def read_key(home):
    configured = os.environ.get('OPENAI_API_KEY', '').strip()
    if configured:
        return configured
    # DPAPI仅能由保存密钥的Windows用户解密；输出在内存中接收，不写请求文件和日志。
    path = Path(home)/'local/gpt-pilot/api-key.dpapi'
    script = "$ErrorActionPreference='Stop';$s=(Get-Content -LiteralPath '"+str(path).replace("'","''")+"' -Raw).Trim()|ConvertTo-SecureString;$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);try{[Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p);$s.Dispose()}"
    env=dict(os.environ);env.pop('PSModulePath',None)
    shell=shutil.which('pwsh.exe')
    if not shell:
        # 自动恢复服务的PATH可能不包含配置密钥所用的PowerShell 7。
        installed=Path(os.environ.get('USERPROFILE',''))/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
        if not installed.is_file():raise ValueError('找不到配置密钥所用的PowerShell 7，未发送请求')
        shell=str(installed)
    encoded=base64.b64encode(script.encode('utf-16-le')).decode()
    r = subprocess.run([shell,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],env=env,capture_output=True,creationflags=0x08000000,timeout=20)
    if r.returncode or not r.stdout.strip():
        raise ValueError('API密钥无法解密，请在本机重新配置；未发送请求')
    return r.stdout.decode().strip()


def validate_segments(prediction, start, end, duration):
    result=[]
    for row in prediction.get('segments',[]):
        try:
            s,e=float(row['start']),float(row['end'])
            if not all(math.isfinite(x) for x in (s,e)) or s < start or e > end+.001 or e-s+.001 < duration:
                continue
            if row.get('match') is not True or row.get('uncertain') is not False or not row.get('evidence') or not isinstance(row.get('actions'),list) or not row['actions']:
                continue
            result.append(dict(row,start=s,end=e))
        except (KeyError,ValueError,TypeError):
            continue
    return result


def call_gpt(rule, ledger, key, frames, query, start, end, metadata, transport=None):
    # JSON模式要求input消息本身包含JSON；仅写在instructions中会被接口拒绝。
    content=[dict(type='input_text',text='请返回JSON对象。任务数据：'+json.dumps(dict(task=query,range_seconds=[start,end]),ensure_ascii=False,allow_nan=False))]
    for f in frames:
        content.extend([dict(type='input_text',text=f'时间{f["time"]:.3f}秒'),dict(type='input_image',detail='high',image_url='data:image/jpeg;base64,'+base64.b64encode(Path(f['path']).read_bytes()).decode())])
    schema='返回JSON对象：segments数组，每项{start:数字,end:数字,match:布尔,uncertain:布尔,actions:动作中文数组,surface:部位中文,evidence:中文观察依据,preference_score:0到1的偏好排序分}。时间用输入绝对秒数。没有合格片段返回空数组，同时必须返回reject_code（category_mismatch/identity_unknown/action_mismatch/duration_short/unclear/semantic_mismatch）和evidence（具体画面依据），不得只返回空数组。顶层另返回scene_type、observed_actions、surface、person_status、product_status；身份未知如实写待核实。'
    body=dict(model=rule['model'],store=False,service_tier='default',reasoning={'effort':'low'},max_output_tokens=1800,instructions='\n'.join(rule['instructions'])+'\n'+schema,input=[dict(role='user',content=content)],text={'format':{'type':'json_object'}})
    # 发送前完成序列化；本地构造错误不占用付费额度。
    wire=json.dumps(body,allow_nan=False).encode()
    cid=reserve(ledger,rule,metadata); started=time.monotonic()
    stage='发送请求';request_id=None;response=None;data=dict(metadata);accounted=False
    try:
        if transport:
            response=transport(body)
        else:
            req=urllib.request.Request('https://api.openai.com/v1/responses',data=wire,headers={'Content-Type':'application/json','Authorization':'Bearer '+key,'X-Client-Request-Id':cid})
            def mark(value):
                nonlocal stage
                stage=value
            with open_tracked_request(req,mark) as f:
                request_id=f.headers.get('x-request-id');stage='读取HTTP响应'
                response=json.load(f)
        stage='核对返回用量'
        usage=response['usage']; inp=usage['input_tokens']; out=usage['output_tokens']
        if not isinstance(inp,int) or not isinstance(out,int) or min(inp,out)<0:
            raise ValueError('无有效用量，暂停后续调用')
        cost=(inp*2+out*10)/1e6
        upper=max(cost,(inp*5+out*10)/1e6)
        data=dict(metadata,usage=usage,response_id=response.get('id'),request_id=request_id,seconds=round(time.monotonic()-started,3),cost_estimate_usd=cost,response_status=response.get('status'),incomplete_details=response.get('incomplete_details'))
        with budget_db(ledger) as db:
            db.execute('UPDATE calls SET reserved=?,pending=0,data=? WHERE id=?',(upper,json.dumps(data,ensure_ascii=False),cid))
        accounted=True;stage='解析模型JSON'
        if response.get('status') in ('failed','incomplete','cancelled'):
            raise ValueError('模型返回状态 '+str(response.get('status'))+'：'+str(response.get('incomplete_details') or response.get('error')))
        text=''.join(c.get('text','') for o in response.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
        prediction=json.loads(text)
        if not isinstance(prediction,dict) or not isinstance(prediction.get('segments'),list):
            raise ValueError('GPT响应格式无效')
        return prediction,data
    except Exception as exc:
        error=dict(stage=stage,type=type(exc).__name__,message=safe_error(exc,key))
        if isinstance(exc,urllib.error.HTTPError):
            error.update(http_status=exc.code,request_id=exc.headers.get('x-request-id'))
            try:
                detail=json.loads(exc.read(65536)).get('error',{})
                error.update({k:safe_error(detail.get(k,''),key) for k in ('message','code','type','param')})
            except (ValueError,AttributeError):pass
        not_sent=stage=='建立TLS连接'
        diagnostic=dict(data,call_id=cid,request_id=error.get('request_id') or request_id,seconds=round(time.monotonic()-started,3),error=error,billing_status='用量已记录' if accounted else ('TLS建立失败，未发送模型请求' if not_sent else '未取得用量，预留待核账'))
        with budget_db(ledger) as db:
            db.execute('UPDATE calls SET data=? WHERE id=?',(json.dumps(diagnostic,ensure_ascii=False),cid))
            if not_sent:
                db.execute('UPDATE calls SET reserved=0,pending=0 WHERE id=?',(cid,))
        http=' HTTP '+str(error['http_status']) if error.get('http_status') else ''
        message=f"GPT请求失败：{stage}{http}；{error['message']}。{diagnostic['billing_status']}；已停止，不自动重试（记录{cid[:8]}）"
        raise GPTRequestError(message,diagnostic) from None
