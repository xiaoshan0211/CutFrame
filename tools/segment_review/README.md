# 从原片判读候选秒段

`segment_review.py` 来自镜序的逐段标注流程。它用 FFprobe 取得原片各显示帧的时间戳，用 FFmpeg 读取画面并寻找切镜点。起秒包含首帧，止秒为最后一帧之后的时间。镜头长度允许时优先保留至少 3 秒。

## 查看切镜候选

使用 Python 3.10 或更高版本，安装 NumPy、Pillow 10.1 或更高版本，并将同一套 FFmpeg 和 FFprobe 加入 PATH。以下命令在仓库根目录运行。

```shell
python -m pip install numpy "Pillow>=10.1"
python tools/segment_review/review.py examples/synthetic-scene-01.mp4
```

命令输出每个候选的起止帧序号和秒数。亮度突变也可能触发切镜判定，选片前按给出的区间回放原片。若 FFmpeg 安装在单独的目录，可加 `--ffmpeg-dir` 指定位置。

## 生成机器初标

另行准备适配机器的 PyTorch、支持 `Qwen3VLForConditionalGeneration` 的 Transformers、openpyxl 以及本地 Qwen3-VL Instruct 权重。工作簿采用镜序的「标签字典」工作表，包含「维度」「标签」「名称」三列以及「画面类型」「素材类别」两组条目。

```shell
python tools/segment_review/review.py examples/synthetic-scene-01.mp4 --model /path/to/local/model --workbook examples/synthetic-cloud-segments.xlsx
```

程序先按镜头选取窗口，再抽取窗口两端的原帧复核边界，并在选中的秒段里按字典判读。输出的 JSON 包含起止秒、画面描述、标签编码和逐项依据，核验状态为「机器初标，待人工核对」。声轨存在性的检查来自容器信息，声音内容须另行复听。

生产队列还连接了 COS 对象清单、对象校验与缓存、断点账本、现场复核留置记录和当前打开的 WPS 工作簿。此目录提供从已取得的原片到候选 JSON 的环节。生产队列及 WPS 写表、守护脚本依赖团队环境，未随公开版分发。
