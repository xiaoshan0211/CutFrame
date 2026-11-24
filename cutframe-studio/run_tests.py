"""在新的临时台账中执行离线单元测试，关闭子进程后再清理 SQLite。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from init_local import BASE, initialize


def main():
    with tempfile.TemporaryDirectory(prefix="cutframe-tests-") as temporary:
        config_path = initialize(Path(temporary))
        config = json.loads(config_path.read_text("utf-8"))
        config["roots"] = {}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        command = [sys.executable, "-B", "-m", "unittest"]
        command += sys.argv[1:] or ["discover", "-s", ".", "-p", "test_*.py"]
        result = subprocess.run(
            command, cwd=BASE,
            env={**os.environ, "CUTFRAME_STATE": temporary},
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
