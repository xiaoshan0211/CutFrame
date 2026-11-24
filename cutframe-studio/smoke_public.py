"""验证一个全新的工程能打开工作台并从空库读取有效响应。"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from init_local import initialize


def check_media(client, options):
    from app import CONFIG, TOKEN, scan
    from media import probe

    generated = subprocess.run(
        [CONFIG["ffmpeg"], "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=90x160:rate=10", "-t", "4", "-g", "1", "-c:v", "mpeg4",
         "-f", "mp4", "-movflags", "frag_keyframe+empty_moov", "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    write_options = {**options, "headers": {"X-Local-Token": TOKEN}}
    ingested = client.post("/api/materials/aliyun/file?name=demo.mp4", data=generated,
                           content_type="application/octet-stream", **write_options)
    assert ingested.status_code == 200, ingested.json
    asset_id = ingested.json["id"]
    with client.get(f"/media/{asset_id}", headers={"Range": "bytes=10-60"}, **options) as response:
        assert response.status_code == 206 and response.data == generated[10:61]
    response = client.post("/api/clip", json={"asset_id": asset_id, "start": 0.5,
                           "end": 3.5, "mode": "copy"}, **write_options)
    assert response.status_code == 200, response.json
    job_id = response.json["job_id"]
    for _ in range(120):
        job = client.get(f"/api/jobs/{job_id}", **options).json
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.25)
    assert job["status"] == "done", job["message"]
    duration = probe(CONFIG["ffprobe"], Path(job["result"]["path"]))["duration"]
    assert abs(duration - 3.0) <= 0.12, duration

    scan()
    samples = (("镜头中抹板在墙面移动并留下色带。", "P0001", "V05", 1.25, 5.25),
               ("把保护胶带铺到地面边缘。", "P0002", "V09", 5.25, 8.75))
    for text, entry_id, picture_type, start, end in samples:
        view = client.get("/api/local/viewpoint", query_string={"text": text}, **options)
        assert view.status_code == 200 and entry_id in (view.json.get("id"), view.json.get("entry_id")), view.json
        project = client.post("/api/projects", json={"name": "合成素材验证"}, **write_options)
        assert project.status_code == 200, project.json
        query = {"text": text, "duration": 2, "project_id": project.json["id"],
                 "task_id": entry_id, "scope": "demo", "conditions": {"must": [
                     {"dimension": "画面类型", "tags": [picture_type]}]}}
        result = client.post("/api/local/discover", json=query, **write_options)
        assert result.status_code == 200 and len(result.json.get("items", [])) == 1, result.json
        item = result.json["items"][0]
        assert item["start"] == start and item["end"] <= end and item["end"] > start, item


def check_routes(with_media):
    from app import app, PORT

    with app.test_client() as client:
        options = {"base_url": f"http://127.0.0.1:{PORT}"}
        for url in ("/", "/classification-selection", "/static/app.js", "/api/annotation/overview"):
            assert client.get(url, **options).status_code == 200, url
        assert client.get("/api/state", **options).json["application"] == "cutframe-studio"
        assert client.get("/api/assets", **options).json["items"] == []
        if with_media:
            check_media(client, options)


def main():
    with tempfile.TemporaryDirectory(prefix="cutframe-smoke-") as temporary:
        state = Path(temporary)
        config = initialize(state)
        original = config.read_bytes()
        assert initialize(state).read_bytes() == original
        settings = json.loads(original)
        assert not settings["lan_access"] and Path(settings["output"]).is_dir()
        subprocess.run(
            [sys.executable, "-B", __file__, "--routes", *sys.argv[1:]],
            env={**os.environ, "CUTFRAME_STATE": temporary},
            check=True,
        )
    print("通过：初始配置、重复初始化、工作台首页、选片页面、标注接口和空素材库。")
    if "--media" in sys.argv:
        print("通过：生成 4 秒合成素材，导入、范围预览、按 0.5 至 3.5 秒剪出并核查导出时长。")
        print("通过：扫描示例素材，按两句文案分别找到 V05 和 V09 在表内指定的秒段。")


if __name__ == "__main__":
    if "--routes" in sys.argv:
        check_routes("--media" in sys.argv)
    else:
        main()
