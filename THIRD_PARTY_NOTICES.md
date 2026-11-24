# 第三方来源与许可证

镜序自研代码和随附文档采用 MIT 许可证。下列代码、字体和外部组件各自沿用原权利人的许可。[本项目许可证](LICENSE)

| 组成 | 来源、版本与使用方式 | 适用许可 |
| --- | --- | --- |
| CutFrame 上游 | 镜序精裁工具参考 V0ightt/CutFrame。时间数值校验函数改编自其 parse_seconds，参考提交为 6fe247eb09d8e154f0530305e8a2c572b58a3ec4。[上游提交](https://github.com/V0ightt/CutFrame/tree/6fe247eb09d8e154f0530305e8a2c572b58a3ec4) | MIT，Copyright (c) 2026 V0ightt。[完整原文](LICENSE-CutFrame.txt) |
| 思源黑体 | 仓库随附 Adobe Source Han Sans CN 常规和粗体两个原始 OTF 文件，以便按所选字重渲染字幕。版权归 Adobe，Source 为保留字体名称。 | SIL Open Font License 1.1。再分发字体时请同时保留随附的版权声明和许可文本。[字体许可证](cutframe-studio/static/fonts/LICENSE.txt) |
| GPT-SoVITS | 本地配音通过外部 GPT-SoVITS 进程生成。[上游项目](https://github.com/RVC-Boss/GPT-SoVITS) | 上游代码为 MIT，Copyright (c) 2024 RVC-Boss。训练音色、参考录音及模型权重的使用取决于各自授权。[上游代码许可](LICENSE-GPT-SoVITS.txt) |
| Chinese-CLIP | 本地候选检索集成 OFA-Sys 的 Chinese-CLIP ViT-B/16。[上游项目](https://github.com/OFA-Sys/Chinese-CLIP) | 上游代码采用 MIT，许可文件保留 OFA-Sys Team 和原始 CLIP 相关贡献者的版权声明。模型权重另按实际分发条款取得。[上游代码许可](LICENSE-Chinese-CLIP.txt) |

## 运行时依赖与素材

Python 包可按版本清单从各自的发行渠道安装。Flask、Werkzeug、Jinja2、MarkupSafe、itsdangerous、click、colorama 等包的版权声明及许可证随各自发行物提供。FFmpeg 和 FFprobe 作为外部程序运行，其适用条款取决于所安装的构建版本。[Python 依赖清单](cutframe-studio/requirements.txt)

用户接入的原片、图片、背景音乐、配音和客户工程数据由相应权利人授权。仓库代码的 MIT 许可适用于软件及其文档。
