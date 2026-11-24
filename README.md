# 镜序 CutFrame

镜序是面向装修短视频制作的选片与剪辑工作台。剪辑师可以把原片按可用秒段标注，按字幕检索候选镜头，预览后选入分镜，再合成视频。

## 在 Windows 上启动

准备 Python、Git 和可在命令行调用的 FFmpeg、FFprobe。在仓库根目录用 PowerShell 执行以下命令。

```powershell
cd cutframe-studio
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe init_local.py
.\.venv\Scripts\python.exe app.py
```

默认工作台地址是 `http://127.0.0.1:4380`。初始化会创建本机配置、素材目录和导出目录。可在生成的 `local/cutframe/config.json` 中设置自己的素材根目录，保存后重启。已有配置会保留。

## 从一条素材开始

1. 选择有权使用的原片，用播放器核对适合剪辑的起点与终点，按原片时间轴记为秒数。
2. 在同一行填写这段实际拍到的画面类型、类别和描述。一条原片有两个不同的精华片段时，各写一行。
3. 选片时以同一行核对全部检索条件，从该行起秒预览。示例表包含同一原片的两个秒段，可用来检查跨段误匹配。

[9 秒竖屏示意视频](examples/synthetic-scene-01.mp4) · [合成标注示例](examples/synthetic-cloud-segments.xlsx) · [演示操作](examples/README.md) · [标注与选片规则](docs/镜头标注规则.md)

## 验证安装

在 `cutframe-studio` 目录运行以下命令。检查会使用临时空库，验证工作台、选片页、素材接口及重复初始化。

```powershell
.\.venv\Scripts\python.exe -B smoke_public.py
```

安装并配置 FFmpeg、FFprobe 后，可以再运行 `smoke_public.py --media`。这项检查会生成 4 秒测试视频、从 0.5 秒裁到 3.5 秒并测量输出时长，再用两句演示字幕核对候选秒段。

## 源码与数据

应用源码、前端、规则和测试在 `cutframe-studio/`。`修订产出/` 和 `画面类型素材路径库/` 按程序读取的路径放置演示工作簿和索引。它们与 `examples/` 中的示意视频配套。实际使用云素材需配置自己的数据表、存储和访问凭据。语音、模型检索和外部服务功能需要相应的运行环境。

项目自研代码采用 MIT 许可证。字体、上游代码及其他依赖的版权和使用条件见 [第三方许可说明](THIRD_PARTY_NOTICES.md) 和 [项目许可证](LICENSE)。

## 独立组件与验证范围

- [原片逐帧判读](tools/segment_review/README.md) 可从原片帧时间戳定位片段并生成初标 JSON。运行视觉模型需要另行配置权重。
- [字幕图叠加组件](extensions/member-portal/README.md) 可用于团队门户的字幕合成。完整团队网关和生产 COS 写表队列依赖单独的部署环境。
- 公开示例验证了空库启动、原片范围读取、按秒预览、组合条件检索和裁切导出。完整版历史回归还引用原业务句库及旧接口约定。在本次发布验证中，188 项历史测试有 6 项断言失败、17 项报错、8 项跳过。涉及原业务数据、可选依赖以及新旧规则差异；需要复现的用例可在 `cutframe-studio/run_tests.py` 中运行。
