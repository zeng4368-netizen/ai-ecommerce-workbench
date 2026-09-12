# 开源视频混剪工具 GitHub 搜索与安装记录

- 日期：2026-08-15
- 搜索目标：可用于电商/短视频「混剪」的直接可用开源项目（素材拼接、自动剪辑、无损裁剪合并）
- 搜索方式：GitHub API（`api.github.com/search/repositories` + 具体仓库信息核对）

## 搜索记录

查询词：
- `video+mashup+editor`：结果质量低，仅有低星 web 编辑器
- `auto+video+editor`：命中 `WyattBlue/auto-editor`
- `视频混剪`：结果噪音大（多为编程教程/无关仓库），无直接可用的成熟混剪项目
- `ffmpeg+concat+gui` / `video+montage+mixer`：无高价值命中

重点核对的候选项目（stars / 语言 / 许可证 / 最近推送 / 活跃）：

| 项目 | Stars | 语言 | 许可证 | 最近推送 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `mifi/lossless-cut` | 42,933 | TypeScript | GPL-2.0 | 2026-08-14 | 无损裁剪/合并片段，便携版 |
| `mltframework/shotcut` | 14,921 | C++ | GPL-3.0 | 2026-08-15 | 完整时间线剪辑器（重） |
| `OpenShot/openshot-qt` | 6,167 | Python | NOASSERTION | 2026-08-15 | 完整时间线剪辑器（重） |
| `WyattBlue/auto-editor` | 4,888 | Nim | Unlicense | 2026-08-14 | CLI 自动剪辑（切静音/批量） |
| `ozmartian/vidcutter` | 1,974 | Python | GPL-3.0 | 2025-04-24 | GUI 裁剪/拼接（较老） |

## 选择结论

- 采用 `mifi/lossless-cut`：日常手动混剪最实用（无损、快、便携单 exe），做「裁剪片段→合并」
- 采用 `WyattBlue/auto-editor`：可脚本化、可接进本项目 Python 自动化流程，做批量自动剪辑（如切静音/按条件裁剪）
- 需要复杂转场/多轨/配乐时再考虑 `Shotcut` / `OpenShot`

## 安装结果

- `auto-editor`：`pip install auto-editor` → v29.3.1；pip 包装器自动下载 Windows amd64 二进制（37,913,600 字节）；首次运行曾因中断产生损坏文件，已重新下载完整二进制修复
  - 注意：首次超时中断后二进制不完整，报 `WinError 193`；修复方式为重新覆盖下载完整 release 二进制
- `LosslessCut`：下载 `v3.69.0` Windows x64 便携版（146,192,088 字节 7z），解压至 `external/tools/lossless-cut/`，入口 `LosslessCut.exe`

## 使用提示

- LosslessCut：双击 `external/tools/lossless-cut/LosslessCut.exe`，拖入素材裁剪后「Export → Merge」合并片段
- auto-editor（示例）：
  - `auto-editor input.mp4 -o output.mp4`（自动切掉静音段）
  - `auto-editor --help` 查看参数；可指定帧率、剪切条件等
- 若要做完整混剪（转场/BGM/字幕/卡点），用剪映/CapCut（本地免费）或 Shotcut
