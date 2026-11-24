"""本地候选与反馈台账，原始反馈只追加，经验启用需人工审核。"""
import json, sqlite3, uuid
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()

def connect(path):
    db=sqlite3.connect(str(path),timeout=30)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS slot_reviews(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,data TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS slot_reviews_run ON slot_reviews(run_id);
    CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, created TEXT, payload TEXT, result TEXT);
    CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, created TEXT, run_id TEXT, candidate_id TEXT, reviewer TEXT, verdict TEXT, reason_code TEXT, reason TEXT);
    CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY, created TEXT, feedback_id TEXT, status TEXT, reviewer TEXT, payload TEXT);
    CREATE TABLE IF NOT EXISTS rule_events(id TEXT PRIMARY KEY, created TEXT, rule_id TEXT, status TEXT, reviewer TEXT);
    CREATE TABLE IF NOT EXISTS adoptions(id TEXT PRIMARY KEY, created TEXT, project_id TEXT, task_id TEXT, run_id TEXT, candidate_id TEXT, action TEXT, payload TEXT);
    ''')
    columns={r[1] for r in db.execute('PRAGMA table_info(rule_events)')}
    for field in ('before_payload','after_payload'):
        if field not in columns:db.execute('ALTER TABLE rule_events ADD COLUMN '+field+' TEXT')
    return db

def latest_feedback(db, run_id):
    rows=db.execute('SELECT * FROM feedback WHERE run_id=? ORDER BY rowid',(run_id,)).fetchall()
    latest={}
    for r in rows: latest[(r['candidate_id'],r['reviewer'])]=dict(r)
    return list(latest.values())

def select_diverse(scored, limit=10):
    """同源最多一个；使用抽帧指纹去近似重复，不声称是全库查重。"""
    chosen=[];sources=set()
    for item in sorted(scored,key=lambda r:r['score'],reverse=True):
        if item['asset_id'] in sources: continue
        if any(bin(int(item['phash'],16)^int(x['phash'],16)).count('1')<=5 for x in chosen): continue
        chosen.append(item);sources.add(item['asset_id'])
        if len(chosen)==limit: break
    return chosen
