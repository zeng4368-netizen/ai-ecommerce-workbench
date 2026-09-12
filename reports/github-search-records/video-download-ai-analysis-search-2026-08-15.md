# 视频无水印下载 + AI 分析开源工具 GitHub 搜索记录

- 日期：2026-08-15
- 搜索目标：支撑「表格链接→无水印下载→AI脚本分析→混剪」流程的开源工具

## 无水印下载

查询词：`tiktok+no+watermark+downloader`、`tiktok+watermark+remover+download`

候选核对：

| 项目 | Stars | 语言 | 许可证 | 结论 |
| --- | --- | --- | --- | --- |
| `yt-dlp/yt-dlp` | 184,539 | Python | Unlicense | 采用。通用下载器，TikTok 提取器内置 `download_addr`（无水印）格式并优先选择 |
| `Evil0ctal/Douyin_TikTok_Download_API` | 19,357 | Python | Apache-2.0 | 参考。TikTok/抖音解析 API，可作备用通道 |
| `xtekky/TikDown` | 42 | Python | - | 不采用。年久失修（2022 停更） |
| 其他低星 TikTok 下载器 | - | - | - | 不采用，质量不可靠 |

实现方式：`yt-dlp` 的 TikTok 提取器会把无水印流暴露为 format id `download_addr`，下载时用 `format: "download_addr/best"` 优先取无水印，失败回退最高画质。

## AI 视频脚本分析

- 采用本机已装的 `creatok analyze`（CreatOK CLI）：对 TikTok URL 返回字幕时间轴 + 视觉分析 + 建议，作为「AI 分析脚本」的真实来源（需要 `CREATOK_API_KEY`）
- 片段打标签/排序：管线内置 OpenAI 兼容 LLM 接口（`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL`），不可用时自动回退关键词+位置启发式

## 安装结果

- `pip install yt-dlp imageio-ffmpeg`：yt-dlp 2026.07.04；imageio-ffmpeg 自带 ffmpeg-win-x86_64-v7.1，无需单独装 ffmpeg
- 修复记录：`auto-editor` pip 包装器首次下载二进制中断会损坏文件（WinError 193），需重新覆盖下载完整 release

## 2026-08-15 实测补充

- `curl-cffi` 版本约束：yt-dlp 2026.07 要求 `>=0.5.10,<0.16`；装 0.16 会失去 impersonation（`no impersonate target available`），装 0.15 时被 TikTok 返回异常页。实测 0.16 + 原生 JS 挑战路径成功率更高
- TikTok 风控：无登录/无 cookie 时本机 IP 会被部分风控；「图文帖」（photo mode）网页端只有音频流，无法切视频，管线自动跳过
- 广告表合并：`广告数据123.xlsx` 的 `Video ID` 需按字符串读取（pandas 会转 float 丢精度）；与视频表按「链接 /video/(数字)」匹配，实测 6501/6861 条可匹配
- sucps.com（用户提供）：解析接口 `POST /parse/apply` 带 geetest 人机验证，无法稳定自动化；作为手动下载通道，配合 `data/raw/manual_videos/<行键>.mp4` 使用
- CreatOK 直链（新增）：`creatok analyze` 返回 `video.download_url`（TikTok CDN 直链），可绕过本机 IP 风控；同时返回 `transcript.segments` + `vision.scenes`，一次调用同时解决「无水印下载 + AI 脚本/分镜分析」。免费套餐每天 3 次分析
