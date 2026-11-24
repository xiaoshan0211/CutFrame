"""字幕选片按工程来源读写，已保存的批次始终回到生成它的库。"""
from dataclasses import dataclass
from pathlib import Path
from flask import current_app, request

from cloud_materials import ROOT


@dataclass(frozen=True)
class SelectionSource:
    learning: Path
    clean_book: Path
    rules: Path
    plan: Path
    ranking: Path
    prefix: str = ''


def active_source():
    local,cloud=current_app.extensions['selection_sources']
    data=request.get_json(silent=True) if request.is_json else {}
    data=data if isinstance(data,dict) else {}
    rid=(request.view_args or {}).get('rid') or data.get('run_id')
    if rid:
        return cloud if str(rid).startswith('cloud-') else local
    scope=request.args.get('scope') or request.headers.get('X-Material-Scope')
    if request.path=='/api/local/discover':
        scope=data.get('scope') or scope
    return cloud if scope==ROOT else local
