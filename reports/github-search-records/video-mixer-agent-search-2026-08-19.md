# 自动混剪智能体 GitHub 调研记录

- 日期：2026-08-19
- 目标：寻找可复用的视频理解、自动混剪、时间线编辑和本地渲染项目。
- 结论：没有单一项目同时满足“20 万条指标筛选、TikTok 授权下载、商品级语义分析、三变体混剪、Streamlit 人工审核”。继续扩展现有 `ecom_ops.video_mixer`，按组件复用或参考。

## 检索词

- `open source AI video editor semantic video search timeline remix`
- `video scene detection shot boundary TransNetV2 PySceneDetect`
- `video understanding timestamped segments multimodal LLM`
- `React video timeline editor trim MIT license`

## 核对项目

| 项目 | 许可证 | 用途 | 决策 |
| --- | --- | --- | --- |
| `Theorvane/openscene` | MIT | 本地优先编辑器、AI 与时间线共享状态、人工批准 | 参考架构，不整仓引入 |
| `ipmotionmc/AiCut` | MIT | 可嵌入 React 时间线、JSON 项目、拖动/裁剪 | 工作台时间线候选，封装后使用 |
| `Relo-video/SynthCut` | GPL-3.0 | AI 操作时间线、媒体检索、FFmpeg 渲染 | 只参考设计，不复制代码 |
| `RenShuhuai-Andy/TimeChat` | BSD-3-Clause 等 | 时间定位视频理解 | 需要 A100/A6000，不适合当前电脑 |
| `TencentARC/TimeLens` | 研究代码 | 视频时间定位 | 用作评估思路，不用于本机生产推理 |
| `Breakthrough/PySceneDetect` | BSD-3-Clause | 镜头边界检测 | 采用，保留 FFmpeg 回退 |
| `SYSTRAN/faster-whisper` | MIT | 本地转写 | 作为无云端 API 时的可选回退 |
| `yt-dlp/yt-dlp` | Unlicense | 授权链接下载 | 采用，cookie 仅由用户显式提供 |

## 实施边界

- Python/FastAPI/Streamlit/SQLite 保持为主技术栈，FFmpeg 负责最终渲染。
- 不引入 GPL 编辑器代码到核心包。
- 不绕过登录、验证码、2FA 或平台访问控制。
- 所有素材必须有商业二次剪辑授权；系统不自动发布、不自动删除。

## 来源

- https://github.com/Theorvane/openscene
- https://github.com/ipmotionmc/AiCut
- https://github.com/Relo-video/SynthCut
- https://github.com/RenShuhuai-Andy/TimeChat
- https://github.com/TencentARC/TimeLens
- https://github.com/Breakthrough/PySceneDetect
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/yt-dlp/yt-dlp

## 2026-08-20 片段库与时间线复核

用户批准建设可复用片段数据库和类剪映人工时间线。本轮新增检索词：

- `react timeline editor split trim video MIT license open source`
- `OpenCut video editor timeline split trim license`
- `AiCut embeddable timeline split trim snap frame step`
- `transcript waveform split trim browser video editor`

| 项目 | 许可证/状态 | 复核结论 |
| --- | --- | --- |
| `ipmotionmc/AiCut` | MIT | 继续作为首选交互模型；支持播放头分割、边缘裁剪、吸附、逐帧步进、撤销恢复、JSON 项目和宿主渲染。优先复用可独立嵌入的时间线能力。 |
| `xzdarcy/react-timeline-editor` | MIT | 成熟的通用 React 时间线，适合作为 AiCut 集成受阻时的备用组件，但视频剪辑语义需要自行补充。 |
| `OpenCut-app/OpenCut` | MIT，正在重写 | 仅参考素材面板、时间线和属性检查器布局；当前架构仍在重写，不整仓引入。 |
| `wassgha/rescript` | 当前版本许可已变化 | 波形、文字时间条、播放头分割和边缘裁剪设计可参考；不复制当前版本代码。 |

实施决策：保留 Python/FastAPI/Streamlit/SQLite/FFmpeg 主架构；片段只保存原素材时间引用，不复制物理视频；AI 和人工边界均版本化；用户可见字段尽可能中文化；内部稳定标识仍使用英文枚举，避免破坏 API 与历史数据。

新增来源：

- https://github.com/ipmotionmc/AiCut
- https://github.com/xzdarcy/react-timeline-editor
- https://github.com/OpenCut-app/OpenCut
- https://github.com/wassgha/rescript
