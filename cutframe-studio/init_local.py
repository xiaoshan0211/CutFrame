"""根据公开示例初始化本机目录、素材根和工具路径。"""
import json
import os
import shutil
import sys
from pathlib import Path


BASE = Path(__file__).resolve().parent


def default_state():
    return Path(os.environ.get("CUTFRAME_STATE", BASE.parent / "local" / "cutframe")).resolve()


def initialize(state):
    state = Path(state).resolve()
    state.mkdir(parents=True, exist_ok=True)
    target = state / "config.json"
    if target.exists():
        return target
    config = json.loads((BASE / "config.example.json").read_text(encoding="utf-8"))
    for key in ("output", "music_root"):
        path = (state / config[key]).resolve()
        path.mkdir(parents=True, exist_ok=True)
        config[key] = str(path)
    for source in config["roots"].values():
        path = (state / source["path"]).resolve()
        path.mkdir(parents=True, exist_ok=True)
        source["path"] = str(path)
    examples = BASE.parent / "examples"
    if (examples / "synthetic-scene-01.mp4").is_file():
        config["roots"]["demo"] = {
            "path": str(examples),
            "path_aliases": ["examples"],
            "label": "演示素材",
            "role": "raw",
            "origin": "local",
        }
    config["python"] = sys.executable
    for key in ("ffmpeg", "ffprobe"):
        config[key] = shutil.which(config[key]) or config[key]
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
    except FileExistsError:
        pass
    return target


if __name__ == "__main__":
    print(initialize(default_state()))
