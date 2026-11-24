"""将用户选定的视频流式复制到独立的阿里云来源库。"""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from flask import jsonify, request
from media import probe

ROOT = 'aliyun-import'
MAX_BYTES = 16 * 1024**3
TEAM_BUCKET=os.environ.get('CUTFRAME_COS_HOST', '').strip().lower()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def oss_object(url):
    if not isinstance(url,str) or len(url)>8192:
        raise ValueError('请粘贴一个 OSS 视频对象的 HTTPS 下载链接')
    parts=urlsplit(url)
    if (parts.scheme!='https' or parts.username is not None or parts.password is not None
            or parts.port not in (None,443) or parts.fragment or
            not (re.fullmatch(r'[a-z0-9][a-z0-9-]*\.oss-[a-z0-9-]+\.aliyuncs\.com',parts.hostname or '') or
                 bool(TEAM_BUCKET) and parts.hostname==TEAM_BUCKET and re.fullmatch(r'/originals/[a-f0-9]{20}\.[a-zA-Z0-9]+',parts.path))):
        raise ValueError('请输入 OSS 视频链接或团队素材库签发的原片对象链接。')
    return unquote(parts.path.rsplit('/',1)[-1])


def register(app,env):
    folder=env['STATE']/'aliyun-materials'
    env['CONFIG']['roots'][ROOT]=dict(label='团队云端',role='raw',origin='cloud',path=str(folder))

    @app.get('/api/materials/aliyun/segments/<aid>')
    def cloud_segment_list(aid):
        import cloud_segments
        asset=env['get_asset'](aid)
        if asset['root']!=ROOT:raise ValueError('请选择团队云端来源的原片')
        path=app.extensions['selection_sources'][1].clean_book
        rows=cloud_segments.index(path)[0].get(aid,[]) if path.is_file() else []
        return jsonify(items=rows)

    def ingest(stream,relative,size):
        parts=relative.replace('\\','/').split('/')
        if any(not part or len(part)>200 or re.search(r'[<>:"|?*\x00-\x1f]',part)
               or part.endswith(('.',' ')) or PureWindowsPath(part).is_reserved() for part in parts):
            raise ValueError('素材文件名或目录名无效')
        name=parts[-1]
        if Path(name).suffix.lower() not in env['VIDEO']:
            raise ValueError('请选择视频原片')
        if size is not None and (size<=0 or size>MAX_BYTES):
            raise ValueError('单条视频须大于 0 字节且不超过 16 GB')
        folder.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256()
        total=0
        with tempfile.NamedTemporaryFile(dir=folder,suffix='.part',delete=False) as f:
            temp=Path(f.name)
        try:
            with temp.open('wb') as out:
                while True:
                    block=stream.read(1024*1024)
                    if not block:break
                    total+=len(block)
                    if total>MAX_BYTES:raise ValueError('单条视频超过 16 GB')
                    digest.update(block)
                    out.write(block)
            if not total or (size is not None and size!=total):raise ValueError('视频传输不完整，请重新导入')
            aid=hashlib.sha256((ROOT+digest.hexdigest()).encode()).hexdigest()[:32]
            old=env['one']('SELECT * FROM assets WHERE id=?',(aid,))
            if old and old['available'] and env['safe_child'](folder,old['rel']).is_file():
                return dict(id=aid,name=old['name'],duplicate=True)
            meta=probe(env['CONFIG']['ffprobe'],temp,uploaded=True)
            if not meta.get('width') or not meta.get('height') or meta['duration']<=0:raise ValueError('文件中没有可用的视频画面')
            with env['connect']() as db:
                db.execute('BEGIN IMMEDIATE')
                old=db.execute('SELECT * FROM assets WHERE id=?',(aid,)).fetchone()
                rel=old['rel'] if old else '/'.join([aid,*parts])
                path=env['safe_child'](folder,rel)
                path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():os.replace(temp,path)
                db.execute('INSERT OR REPLACE INTO assets(id,root,rel,name,size,stamp,meta,available) VALUES(?,?,?,?,?,?,?,1)',
                           (aid,ROOT,rel,path.name,total,str(path.stat().st_mtime_ns),json.dumps(meta)))
            return dict(id=aid,name=path.name,duplicate=bool(old))
        finally:
            temp.unlink(missing_ok=True)

    @app.post('/api/materials/aliyun/file')
    def import_aliyun_file():
        request.max_content_length=MAX_BYTES
        return jsonify(ingest(request.stream,request.args.get('name',''),request.content_length))

    @app.post('/api/materials/aliyun/oss')
    def import_oss():
        data=request.get_json() or {}
        url=data.get('url')
        name=oss_object(url)
        try:
            with build_opener(NoRedirect()).open(url,timeout=60) as source:
                size=source.headers.get('Content-Length')
                item=ingest(source,data.get('name') or name,int(size) if size else None)
                if urlsplit(url).hostname==TEAM_BUCKET:
                    with env['connect']() as db:
                        db.execute('CREATE TABLE IF NOT EXISTS team_objects(object_id TEXT PRIMARY KEY,asset_id TEXT NOT NULL)')
                        db.execute('INSERT OR REPLACE INTO team_objects VALUES(?,?)',(Path(name).stem,item['id']))
                return jsonify(item)
        except HTTPError as exc:
            raise ValueError('OSS 返回 HTTP %s，请检查链接的读取权限和有效期。'%exc.code) from None
        except (URLError,TimeoutError,ConnectionError):
            raise ValueError('无法从 OSS 完整读取视频，请检查网络后重试') from None
