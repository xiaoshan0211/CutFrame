from __future__ import annotations
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / '.packages'))
import os
import json
import sqlite3
import threading
import time
import uuid
import hashlib
import shutil
import subprocess
import re
import secrets
import atexit
from datetime import datetime, timezone
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.exceptions import HTTPException
from media import probe, seconds, validate_range, clip_command, FLAGS
from network_access import NetworkAccess

STATE = Path(os.environ.get('CUTFRAME_STATE', str(BASE.parent / 'local' / 'cutframe')))
STATE.mkdir(parents=True, exist_ok=True)
CONFIG = json.loads((STATE / 'config.json').read_text('utf-8-sig'))
PORT = int(CONFIG.get('port', 4380))
ACCESS = NetworkAccess(CONFIG)
TOKEN = secrets.token_urlsafe(32)
DB = STATE / 'catalog.sqlite3'
VIDEO = {'.mp4', '.mov', '.mkv', '.avi', '.wmv', '.m4v', '.mts', '.m2ts', '.webm'}
LOCK = threading.Lock()
SCAN_LOCK = threading.Lock()
SCAN = {'running': False, 'count': 0, 'error': None}
PROCESSES = {}
app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=256 * 1024 * 1024)

def now():
    return datetime.now(timezone.utc).isoformat()

def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def execute(sql, args=()):
    with connect() as c:
        return c.execute(sql, args)

def one(sql, args=()):
    with connect() as c:
        row = c.execute(sql, args).fetchone()
        return dict(row) if row else None

def many(sql, args=()):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]

def initialize():
    with connect() as c:
        c.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, root TEXT, rel TEXT, name TEXT, size INTEGER, stamp TEXT, meta TEXT, error TEXT, available INTEGER DEFAULT 1);
        CREATE INDEX IF NOT EXISTS asset_root ON assets(root);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, created TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT, status TEXT, progress REAL, message TEXT, result TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS clips(id TEXT PRIMARY KEY, asset_id TEXT, path TEXT, data TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, data TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, name TEXT, path TEXT, kind TEXT, meta TEXT);
        CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY);
        INSERT OR IGNORE INTO categories VALUES ('未分类');''')
        c.execute("UPDATE jobs SET status='interrupted',message='上次运行中断；请检查保留的工作记录后重新发起' WHERE status IN ('queued','running')")
    for folder in ('jobs', 'metadata', 'proxies', 'imports'):
        (STATE / folder).mkdir(exist_ok=True)

def safe_child(root, rel):
    root = Path(root).resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError('路径超出授权目录')
    return target

def asset_path(asset):
    roots = CONFIG['roots']
    if asset['root'] not in roots:
        raise ValueError('素材库未配置')
    p = safe_child(roots[asset['root']]['path'], asset['rel'])
    if not p.is_file():
        raise ValueError('源文件不可读，请检查共享连接')
    if p.stat().st_size == 0:
        raise ValueError('源文件为零字节，不能预览或导出')
    return p

def get_asset(asset_id):
    a = one('SELECT * FROM assets WHERE id=?', (asset_id,))
    if not a:
        raise ValueError('素材不存在，请刷新列表')
    return a

def metadata(a):
    p = asset_path(a)
    st = p.stat()
    stamp = str(st.st_mtime_ns)
    if a['meta'] and a['stamp'] == stamp and a['size'] == st.st_size:
        return json.loads(a['meta'])
    try:
        m = probe(CONFIG['ffprobe'], p)
        execute('UPDATE assets SET meta=?,error=NULL,stamp=?,size=? WHERE id=?', (json.dumps(m), stamp, st.st_size, a['id']))
        return m
    except Exception as e:
        execute('UPDATE assets SET error=? WHERE id=?', (str(e), a['id']))
        raise

def event(payload):
    execute('INSERT INTO events VALUES (?,?,?)', (uuid.uuid4().hex, now(), json.dumps(payload, ensure_ascii=False)))

def scan():
    if not SCAN_LOCK.acquire(False):
        return
    SCAN.update(running=True, count=0, error=None)
    errors = []
    try:
        for alias, cfg in CONFIG['roots'].items():
            if cfg.get('origin')=='cloud':continue  # 导入接口按内容登记，目录扫描按路径编号。
            root = Path(cfg['path'])
            if not root.is_dir():
                errors.append(cfg['label'] + '：共享不可达')
                continue
            found, local_errors = [], []
            for parent, dirs, files in os.walk(root, followlinks=False, onerror=lambda e: local_errors.append(str(e))):
                dirs[:] = [d for d in dirs if not Path(parent, d).is_symlink()]
                for name in files:
                    p = Path(parent, name)
                    if p.suffix.lower() not in VIDEO or name.startswith('._'):
                        continue
                    try:
                        rel = p.relative_to(root).as_posix()
                        checked = safe_child(root, rel)
                        st = checked.stat()
                        aid = hashlib.sha256((alias + '/' + rel).encode()).hexdigest()[:32]
                        found.append(aid)
                        with connect() as c:
                            c.execute('''INSERT INTO assets(id,root,rel,name,size,stamp,available) VALUES(?,?,?,?,?,?,1)
                            ON CONFLICT(id) DO UPDATE SET available=1,size=excluded.size,stamp=excluded.stamp,
                            meta=CASE WHEN assets.size=excluded.size AND assets.stamp=excluded.stamp THEN assets.meta ELSE NULL END,
                            error=CASE WHEN assets.size=excluded.size AND assets.stamp=excluded.stamp THEN assets.error ELSE NULL END''',
                                      (aid, alias, rel, name, st.st_size, str(st.st_mtime_ns)))
                        SCAN['count'] += 1
                    except OSError as e:
                        local_errors.append(str(e))
            if not local_errors:
                with connect() as c:
                    c.execute('CREATE TEMP TABLE seen(id TEXT PRIMARY KEY)')
                    c.executemany('INSERT OR IGNORE INTO seen VALUES(?)', [(i,) for i in found])
                    c.execute('UPDATE assets SET available=0 WHERE root=? AND id NOT IN (SELECT id FROM seen)', (alias,))
            errors.extend(local_errors)
    except Exception as e:
        errors.append(str(e))
    finally:
        SCAN.update(running=False, error='\n'.join(errors[:10]) or None)
        SCAN_LOCK.release()

def update_job(jid, **fields):
    execute('UPDATE jobs SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?', tuple(fields.values()) + (jid,))

def run_media(jid, command, duration, logname='ffmpeg.log', cwd=None):
    if one('SELECT status FROM jobs WHERE id=?',(jid,))['status']=='cancelled':
        raise ValueError('用户已取消')
    jobdir = STATE / 'jobs' / jid
    log = jobdir / logname
    cmd = command[:1] + ['-progress', 'pipe:1', '-nostats'] + command[1:]
    with log.open('w', encoding='utf-8') as f:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=f, encoding='utf-8', errors='replace',
                             creationflags=FLAGS, cwd=cwd)
        PROCESSES[jid] = p
        started = time.monotonic()
        stop_reason = []
        def monitor():
            while p.poll() is None:
                if time.monotonic()-started > max(300, duration*20+120):
                    stop_reason.append('处理超时，已停止；源文件未改动')
                    p.terminate(); return
                if shutil.disk_usage(STATE).free < 256*1024*1024:
                    stop_reason.append('本地工作区剩余空间不足 256MB，已停止')
                    p.terminate(); return
                time.sleep(1)
        threading.Thread(target=monitor,daemon=True).start()
        try:
            for line in p.stdout:
                if line.startswith('out_time_us='):
                    try:
                        pct = min(98, max(0, float(line.split('=')[1]) / 1000000 / max(duration, .01) * 100))
                        update_job(jid, progress=pct)
                    except ValueError:
                        pass
            code = p.wait()
        finally:
            PROCESSES.pop(jid, None)
        if one('SELECT status FROM jobs WHERE id=?', (jid,))['status'] == 'cancelled':
            raise ValueError('用户已取消')
    if code:
        if stop_reason:
            raise ValueError(stop_reason[0])
        raise ValueError(log.read_text('utf-8', errors='replace')[-2200:])

def submit(kind, worker):
    free=shutil.disk_usage(STATE).free
    if free < 256*1024*1024:
        raise ValueError(f'本地工作区所在盘剩余 {free/1024/1024:.0f}MB，不足256MB，任务未启动。请先释放磁盘空间；已有工程和素材保持不变。')
    if not LOCK.acquire(False):
        raise ValueError('已有处理任务，请等待结束或取消；当前不提供批量队列')
    jid = uuid.uuid4().hex
    try:
        (STATE / 'jobs' / jid).mkdir()
        execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)', (jid, kind, 'queued', 0, '准备中', None, now()))
        def work():
            try:
                if one('SELECT status FROM jobs WHERE id=?',(jid,))['status']=='cancelled':
                    return
                update_job(jid, status='running', message='处理中')
                result = worker(jid)
                if one('SELECT status FROM jobs WHERE id=?', (jid,))['status'] != 'cancelled':
                    update_job(jid, status='done', progress=100, message='完成', result=json.dumps(result, ensure_ascii=False))
            except Exception as e:
                if one('SELECT status FROM jobs WHERE id=?', (jid,))['status'] != 'cancelled':
                    update_job(jid, status='failed', message=str(e))
            finally:
                LOCK.release()
        threading.Thread(target=work, daemon=True).start()
        return jid
    except Exception:
        LOCK.release()
        raise

def clean_name(name):
    name = '' if name is None else str(name).strip()
    if not name:
        raise ValueError('名称不能为空，请先填写名称')
    if len(name) > 100:
        raise ValueError('名称不能超过100个字符')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith(('.', ' ')) or name in ('.','..'):
        raise ValueError('名称不能含路径分隔符或 Windows 文件名禁用字符')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        raise ValueError('名称是系统保留字')
    return name

def output_root():
    root = Path(CONFIG['output']).resolve()
    for source in CONFIG['roots'].values():
        src = Path(source['path']).resolve()
        if root == src or root.is_relative_to(src) or src.is_relative_to(root):
            raise ValueError('输出目录必须与源目录完全分离')
    root.mkdir(parents=True, exist_ok=True)
    return root

def publish(temp, category, stem):
    root = output_root()
    if shutil.disk_usage(root).free < temp.stat().st_size + 256*1024*1024:
        raise ValueError('输出磁盘剩余空间不足，未发布；工作文件保留在本地工作区')
    folder = safe_child(root, clean_name(category))
    folder.mkdir(exist_ok=True)
    # 先复制到目标盘暂存区，再原子发布；源路径永远不会作为写入目标。
    stage = safe_child(root, '.staging')
    stage.mkdir(exist_ok=True)
    part = stage / (uuid.uuid4().hex + '.part')
    shutil.copyfile(temp, part)
    for n in range(1, 100000):
        name = clean_name(stem) + f'_{n:02d}.mp4'
        if any(d.is_dir() and (d / name).exists() for d in root.iterdir()):
            continue
        dest = folder / name
        try:
            if os.name == 'nt':
                os.rename(part, dest)  # Windows 上已存在时抛错，不覆盖。
            else:
                os.link(part, dest)
                part.unlink()
            return dest
        except FileExistsError:
            continue
    raise ValueError('无法分配唯一输出名称；暂存文件已保留')

@app.before_request
def guard():
    denied = ACCESS.check(request.host, request.remote_addr, request.headers.get('Origin'))
    if denied:
        return jsonify(error=denied), 403
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('X-Local-Token') != TOKEN:
        return jsonify(error='页面已过期，请刷新'), 403

@app.after_request
def headers(r):
    r.headers['X-Content-Type-Options'] = 'nosniff'
    r.headers['Referrer-Policy'] = 'no-referrer'
    r.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    if request.path.startswith('/api'):
        r.headers['Cache-Control'] = 'no-store'
    return r

@app.errorhandler(Exception)
def error(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    return jsonify(error=str(e)), 400

@app.get('/')
def index():
    return render_template('index.html', token=TOKEN, access_label=ACCESS.label)

@app.get('/classification-selection')
def classification_selection_page():
    return render_template('classify-select.html', token=TOKEN)

@app.get('/api/state')
def state():
    return jsonify(application='cutframe-studio',roots={k:dict(label=v['label'],role=v['role'],origin=v.get('origin','local')) for k,v in CONFIG['roots'].items()},
                   scan=SCAN, output=CONFIG['output'], categories=[r['name'] for r in many('SELECT name FROM categories ORDER BY name')],
                   jobs=many('SELECT * FROM jobs ORDER BY created DESC LIMIT 10'))

@app.post('/api/scan')
def scan_api():
    threading.Thread(target=scan, daemon=True).start()
    return jsonify(ok=True)

@app.get('/api/assets')
def assets():
    page = max(1, int(request.args.get('page', 1)))
    root, q = request.args.get('root',''), request.args.get('q','')
    where, args = 'available=1', []
    if root:
        where += ' AND root=?'; args.append(root)
    if q:
        where += ' AND (instr(name,?)>0 OR instr(rel,?)>0)'; args += [q,q]
    total = one('SELECT count(*) AS n FROM assets WHERE '+where, args)['n']
    rows = many('SELECT id,root,rel,name,size,meta,error FROM assets WHERE '+where+' ORDER BY rel LIMIT 60 OFFSET ?', args+[(page-1)*60])
    return jsonify(total=total, page=page, items=rows)

@app.get('/api/assets/<aid>')
def asset_detail(aid):
    a = get_asset(aid)
    m = metadata(a)
    source={k:a[k] for k in ('id','name','root','rel','size')}
    source['source_path']=str(asset_path(a))
    return jsonify(asset=source, meta=m)

@app.get('/media/<aid>')
def stream(aid):
    p = asset_path(get_asset(aid))
    return send_file(p, mimetype='video/mp4' if p.suffix.lower()=='.mp4' else 'video/quicktime', conditional=True)

@app.post('/api/events')
def event_api():
    data = request.get_json()
    if len(json.dumps(data)) > 16000:
        raise ValueError('记录过长')
    event(data)
    return jsonify(ok=True)

@app.post('/api/categories')
def categories():
    name = clean_name(request.json.get('name'))
    if name in ('成片验证', '.staging'):
        raise ValueError('此名称由系统保留')
    execute('INSERT OR IGNORE INTO categories VALUES(?)', (name,))
    return jsonify(ok=True)

@app.post('/api/clip')
def export_clip():
    data = request.get_json()
    a = get_asset(data['asset_id']); meta = metadata(a)
    start, end = validate_range(data['start'], data['end'], meta['duration'])
    mode = data.get('mode', 'encode')
    if mode not in ('copy','encode'):
        raise ValueError('未知导出方式')
    category = clean_name(data.get('category','未分类'))
    if not one('SELECT name FROM categories WHERE name=?',(category,)):
        raise ValueError('请先创建该分类')
    def work(jid):
        source = asset_path(a)
        before = source.stat()
        temp = STATE / 'jobs' / jid / 'clip.mp4'
        run_media(jid, clip_command(CONFIG, source, temp, start, end, mode, meta), end-start)
        result_meta = probe(CONFIG['ffprobe'], temp)
        after = source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise ValueError('处理期间源文件发生变化，未发布结果')
        if result_meta['duration'] <= 0:
            raise ValueError('导出文件无有效时长')
        if mode == 'encode' and abs(result_meta['duration']-(end-start)) > .3:
            raise ValueError('转码结果时长偏差过大，未发布')
        cid = uuid.uuid4().hex
        record = dict(schema_version=1, clip_id=cid, asset_id=a['id'], root_alias=a['root'], relative_path=a['rel'],
                      source_size=before.st_size, source_mtime_ns=before.st_mtime_ns, requested_start=start, requested_end=end,
                      actual_source_boundaries=None, boundary_status='未核验，尤其无损切割受关键帧约束',
                      mode=mode, source_meta=meta, output_meta=result_meta, category=category,
                      tags=data.get('tags',[]), purpose=data.get('purpose',''), copy=data.get('copy',''),
                      rating=data.get('rating','未评价'), reason=data.get('reason',''), created=now(), job_id=jid)
        journal = STATE / 'metadata' / (cid+'.json')
        record['publication_status'] = 'pending'
        journal.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
        if one('SELECT status FROM jobs WHERE id=?',(jid,))['status']=='cancelled':
            raise ValueError('用户已取消')
        path = publish(temp, category, Path(a['name']).stem)
        record.update(output_relative=path.relative_to(output_root()).as_posix(), publication_status='published')
        journal.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
        execute('INSERT INTO clips VALUES(?,?,?,?,?)',(cid,a['id'],str(path),json.dumps(record,ensure_ascii=False),now()))
        event(dict(action='export_success',clip_id=cid,asset_id=a['id'],rating=record['rating']))
        return dict(path=str(path), clip_id=cid, duration=result_meta['duration'], warning=record['boundary_status'])
    return jsonify(job_id=submit('精裁导出',work))

@app.post('/api/proxy/<aid>')
def proxy(aid):
    a=get_asset(aid); meta=metadata(a); source=asset_path(a)
    stamp=source.stat()
    key=hashlib.sha256(f'{aid}:{stamp.st_size}:{stamp.st_mtime_ns}'.encode()).hexdigest()
    target=STATE/'proxies'/(key+'.mp4')
    if target.exists():
        return jsonify(url='/proxy/'+key)
    def work(jid):
        temp=STATE/'jobs'/jid/'proxy.mp4'
        run_media(jid,clip_command(CONFIG,source,temp,0,meta['duration'],'encode',meta,True),meta['duration'])
        pm=probe(CONFIG['ffprobe'],temp)
        if abs(pm['duration']-meta['duration'])>.3:
            raise ValueError('代理时长与源素材不一致')
        shutil.copyfile(temp,target)
        return dict(url='/proxy/'+key,asset_id=aid)
    return jsonify(job_id=submit('兼容预览',work))

@app.get('/proxy/<key>')
def proxy_stream(key):
    if not re.fullmatch('[0-9a-f]{64}',key):
        raise ValueError('代理标识无效')
    return send_file(STATE/'proxies'/(key+'.mp4'),conditional=True)

@app.get('/api/jobs/<jid>')
def job(jid):
    r=one('SELECT * FROM jobs WHERE id=?',(jid,))
    if not r:
        raise ValueError('任务不存在')
    r['result']=json.loads(r['result']) if r['result'] else None
    return jsonify(r)

@app.post('/api/jobs/<jid>/cancel')
def cancel(jid):
    r=one('SELECT * FROM jobs WHERE id=?',(jid,))
    if r and r['status'] in ('queued','running'):
        update_job(jid,status='cancelled',message='用户取消')
        p=PROCESSES.get(jid)
        if p:
            p.terminate()
    return jsonify(ok=True)

@app.get('/api/clips')
def clips():
    return jsonify(items=many('SELECT * FROM clips ORDER BY created DESC LIMIT 100'))

initialize()
from cloud_materials import register as register_cloud_materials
register_cloud_materials(app,globals())
from composition import register
register(app, globals())
from tts_service import register as register_tts
register_tts(app, globals())
from workflow import register as register_workflow
register_workflow(app, globals())
from ai_service import register as register_ai
register_ai(app, globals())

from annotation_service import register as register_annotation
register_annotation(app, globals())
from annotation_rule_service import register as register_annotation_rules
register_annotation_rules(app, globals())
from local_selection_service import register as register_local_selection
register_local_selection(app, globals())

from pilot_library import register as register_pilot
register_pilot(app, globals())

from classification_service import register as register_classification
from viewpoint_selection import register as register_viewpoint_selection
register_classification(app, globals())
register_viewpoint_selection(app, BASE.parent / '画面类型素材路径库', CONFIG['ffmpeg'])

# 可在本机配置中登记独立审核集目录，保留用户已有的批次编号。
review_dirs = {str(key): Path(value).resolve() for key, value in CONFIG.get('review_dirs', {}).items()}
review_lock = threading.Lock()

def sentence_records(cards, updates=None, rid='8'):
    folder = review_dirs[rid]
    index = json.loads((folder/'记录索引.json').read_text('utf8'))
    scores = {}
    for number, dirname in index.items():
        record = folder.parent/dirname/'选片记录.md'
        names = {Path(c[3]).stem:c[3] for c in cards if c[0]==int(number)}
        lines = record.read_text('utf8').splitlines(keepends=True)
        changed = False
        for pos,line in enumerate(lines):
            cells = line.split('|')
            if len(cells)!=(12 if rid=='10' else 10) or cells[1].strip() not in names:
                continue
            name = names[cells[1].strip()]
            if updates and name in updates:
                cells[7] = ' '+updates[name]+' '
                lines[pos] = '|'.join(cells)
                changed = True
            if cells[7].strip():
                scores[name] = cells[7].strip()
        if changed:
            temp = record.with_suffix('.tmp')
            temp.write_text(''.join(lines),encoding='utf8')
            temp.replace(record)
    return scores

def review_data(rid):
    from flask import abort
    if rid not in review_dirs:
        abort(404)
    folder = review_dirs[rid]
    cards = json.loads((folder/'候选.json').read_text('utf8'))
    if rid in ('8','9','10'):
        return cards,None,sentence_records(cards,rid=rid)
    target = folder/'审核结果.json'
    scores = json.loads(target.read_text('utf8')) if target.exists() else {}
    return cards,target,scores

@app.get('/review500/<rid>')
def review500_page(rid):
    cards,_,scores = review_data(rid)
    return render_template('review500.html',cards=cards,rid=rid,scores=scores,token=TOKEN)

@app.get('/review500/<rid>/media/<name>')
def review500_video(rid,name):
    cards,_,_ = review_data(rid)
    if name not in {c[3] for c in cards}:
        return '',404
    return send_file(review_dirs[rid]/name,conditional=True)

@app.post('/api/review500/<rid>')
def review500_save(rid):
    updates = request.get_json()
    with review_lock:
        cards,target,scores = review_data(rid)
        allowed = {c[3] for c in cards}
        ratings = ('合适','不合适','勉强') if rid in ('8','9','10') else ('合适','不合适')
        if not isinstance(updates,dict) or any(k not in allowed or v not in ratings for k,v in updates.items()):
            return '',400
        if rid in ('8','9','10'):
            if len(updates)!=1:
                return '',400
            return jsonify(sentence_records(cards,updates,rid))
        scores.update(updates)
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(scores,ensure_ascii=False,indent=2),encoding='utf8')
        temp.replace(target)
    return jsonify(scores)

def stop_children():
    for process in list(PROCESSES.values()):
        if process.poll() is None:
            process.terminate()
atexit.register(stop_children)

if __name__ == '__main__':
    from werkzeug.serving import make_server
    print(f'本地精裁工作台：http://127.0.0.1:{PORT}',flush=True)
    make_server(ACCESS.listen,PORT,app,threaded=True).serve_forever()
