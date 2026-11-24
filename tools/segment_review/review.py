"""根据原片时间戳列出切镜候选，或用本地 Qwen3-VL 和标签字典生成候选标注。"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from segment_review import inspect_media, read_media, scene_ranges


def run(arguments, timeout):
    return subprocess.run(arguments, check=True, capture_output=True, timeout=timeout).stdout


def dictionary(workbook):
    import openpyxl

    book = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    try:
        rows = book["标签字典"].values
        header = next(rows)
        positions = [header.index(name) for name in ("维度", "标签", "名称")]
        groups = {}
        for row in rows:
            dim, code, label = (row[i] for i in positions)
            if all(isinstance(value, str) and value.strip() for value in (dim, code, label)):
                entries = groups.setdefault(dim.strip(), {})
                if entries.setdefault(code.strip(), label.strip()) != label.strip():
                    raise ValueError(f"字典编码重复且名称冲突：{dim} / {code}")
        if not all(groups.get(name) for name in ("画面类型", "素材类别")):
            raise ValueError("标签字典须包含画面类型和素材类别")
        return groups
    finally:
        book.close()


def load_model(model_path):
    import torch
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        model_path, local_files_only=True, torch_dtype=dtype, attn_implementation="sdpa"
    ).to(device).eval()
    processor = AutoProcessor.from_pretrained(
        model_path, local_files_only=True, min_pixels=256 * 28 * 28, max_pixels=1800 * 28 * 28
    )

    def ask(image, prompt):
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=[image], return_tensors="pt").to(device)
        budget = 360 if "逐项对照" in prompt else 144
        with torch.inference_mode():
            answer = model.generate(**inputs, max_new_tokens=budget, do_sample=False)
        return processor.batch_decode(answer[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0].strip()

    return ask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--ffmpeg-dir", type=Path, help="同时包含 ffmpeg 和 ffprobe 的目录")
    parser.add_argument("--model", type=Path, help="本地 Qwen3-VL Instruct 权重目录")
    parser.add_argument("--workbook", type=Path, help="含“标签字典”工作表的工作簿")
    args = parser.parse_args()
    if bool(args.model) != bool(args.workbook):
        parser.error("--model 和 --workbook 须同时指定")
    folder = args.ffmpeg_dir
    if folder is None:
        executable = shutil.which("ffmpeg")
        if executable is None:
            parser.error("请安装 FFmpeg 或指定 --ffmpeg-dir")
        folder = Path(executable).parent
    if args.model:
        groups = dictionary(args.workbook)
        result = inspect_media(args.video, groups, folder, run, load_model(args.model), all_scenes=True)
        allowed = {code for entries in groups.values() for code in entries}
        for segment in result:
            segment["codes"] = [code for code in segment["codes"] if code in allowed]
            segment["evidence"] = {c: segment["evidence"][c] for c in segment["codes"]}
            segment["file"] = args.video.name
            segment["核验状态"] = "机器初标，待人工核对"
    else:
        pts, duration, _, _, _ = read_media(args.video, folder, run)
        scenes = scene_ranges(args.video, len(pts), folder, run)
        result = [{"first_frame": a, "stop_frame": b, "start": pts[a],
                   "end": pts[b] if b < len(pts) else duration} for a, b in scenes]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
