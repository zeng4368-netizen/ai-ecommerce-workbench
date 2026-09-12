# 视频混剪流水线 — 项目记忆（可给 GPT 读取）

> 本文件是 Codex 与用户长期协作过程中沉淀的项目上下文。如果你（GPT/新会话）被要求接管或继续这个项目，请先完整阅读本文件再行动。

## 1. 项目目标

为 TikTok Shop 卖家做**带货视频混剪**：从卖家导出的达人视频数据表里，按**同一个商品 ID** 筛选素材 → 下载无水印视频 → 用转化数据评分 → AI 分析脚本打标签 → 切段 → 按"钩子→介绍→展示→演示→诱导下单"等逻辑拼接成新带货视频。

关键要求（用户明确强调）：
- **只允许混剪同一个商品 ID 的素材**，绝不能跨商品混剪。
- 标签体系和混剪顺序不是写死的，需要**基于该商品大量视频的实际共性**去总结（例如有些商品视频没有"产品介绍"环节）。
- 混剪动作用 **ffmpeg** 完成；CreatOK 只用于 AI 分析和直链下载。

## 2. 数据文件（本机路径）

| 文件 | 说明 |
| --- | --- |
| `data/raw/video_data.xlsx` | 视频数据123：6861 条有效行、337 个商品。列结构（索引）：0 视频标题、1 视频 ID、2 发布日期、3 视频链接、4 达人名称、5 商品 ID、6 联盟视频归因 GMV、7 订单数、8 平均订单金额、9 成交件数、10 退款金额、11 退款件数、12 点赞、13 评论、14 分享、15 视频商品曝光、16 商品点击、17 完播率、18 播放量、19 商品点击率、20 千次曝光成交金额、21 互动率、22 每位客户平均 GMV、23 预计佣金 |
| `data/raw/ad_data.xlsx` | 广告数据123：按 Video ID 与视频表合并，补转化率/点击率/2秒与6秒观看率等广告指标 |

注意：读取表格时视频 ID 必须用 openpyxl 字符串读（pandas 会丢精度），用链接里 `/video/<id>` 与广告表 Video ID 匹配。

## 3. 流水线架构（`src/ecom_ops/video_mixer/`）

1. `table_loader.py`：读表、识别列、合并广告表、按商品 ID 分组。
2. `scoring.py`：按 GMV/转化率/点击率/曝光/完播/互动等加权算质量分，分 S/A/B/C。
3. `downloader.py`：**tikwm API 优先**（拿无水印直链）→ 失败回退 yt-dlp（Firefox 登录 cookie）→ 本地/手动素材兜底。
4. `segmenter.py`：静音检测 + 自动切块 → 打标签（LLM 可用则用 LLM，否则关键词/位置启发式）。
5. `mixer.py`：从高分段里挑片段并排序（LLM 可用则让 LLM 排序，否则按标签优先级规则）。
6. `media.py`：ffmpeg 切段/拼接/加水印裁剪。
7. `pipeline.py`：编排以上步骤；`review_app.py` 是 Streamlit 人工审阅台。

## 4. 下载方案（重要决策与教训）

- **yt-dlp 对带货视频只返回音频流**（拿不到视频），且部分被风控（"Unable to extract universal data for rehydration"）。已验证方案：**tikwm 公开 API**（`https://www.tikwm.com/api/?url=<tiktok_url>`）返回 `data.play` 无水印视频直链；图文帖返回 `data.images`。
- **Firefox 登录 TikTok 后**，yt-dlp 用 `--cookies-from-browser firefox` 直读登录态（Firefox 不受 App-Bound Encryption 影响）。Firefox 已安装：`C:\Program Files\Mozilla Firefox\firefox.exe`，用户已登录 TikTok。
- **Edge 151 的 cookie 无法被 yt-dlp 读取**（App-Bound Encryption，issue #10927）。曾尝试 CDP/目录联接读取，导致 **Edge cookie 库被清空（1383→0，无法恢复）**。教训：**永远不要对真实浏览器配置做自动化实验**；cookie 获取只走浏览器扩展导出或 Firefox。
- 转换工具：`video-mix cookies-convert --input <Cookie-Editor导出的json> --output data/raw/tiktok_cookies.txt`。

## 5. 模型配置（.env）

流水线的 LLM 客户端在 `src/ecom_ops/video_mixer/llm.py`（OpenAI 兼容 `/chat/completions`），由 `config.py` 读取环境变量：

```env
OPENAI_API_KEY=sk-...          # 设置后自动启用 LLM 标签 + LLM 排序
OPENAI_MODEL=gpt-4o-mini       # 默认 gpt-4o-mini，可换 gpt-4o / gpt-4.1-mini 等
OPENAI_BASE_URL=https://api.openai.com/v1   # 可换兼容网关
CREATOK_API_KEY=ok_...         # CreatOK 视频分析（每天 3 次额度，分析转写+分镜+直链）
```

LLM 接管范围：
- `segmenter.py::_llm_label_segments`：给每个切好的片段打标签。
- `mixer.py::_llm_plan`：给候选片段排序生成混剪计划。

LLM 不负责：转写/分镜（需 CreatOK 或 faster-whisper+PySceneDetect，尚未接入）、下载、评分、ffmpeg。

## 6. 常用命令

```powershell
# 跑混剪（指定商品）
python -m ecom_ops.video_mixer.cli run --table data/raw/video_data.xlsx --ad-table data/raw/ad_data.xlsx --cookies-from-browser firefox --product-id <商品ID> --top-videos 8 --target-duration 30

# 检查表格列映射
python -m ecom_ops.video_mixer.cli inspect --table data/raw/video_data.xlsx --ad-table data/raw/ad_data.xlsx

# 人工审阅台
streamlit run src/ecom_ops/video_mixer/review_app.py   # http://localhost:8501
```

输出目录：`data/output/mashup/`（mp4 / manifest.json / summary.md / scores.xlsx）。

## 7. 当前状态

- 已出片：商品 `1729519472561719259`（显示器支架，28.8s，9:16，8 条素材）；商品 `1729648224014796763`（无线扩音器，19.6s 测试片）。
- 最近一次：`data/output/mashup/mashup_video_data_20260817_173640_mashup.mp4`。
- 测试：`tests/test_video_mixer.py` 15 个用例全过；ruff 干净。

## 8. 已知限制与下一步

- 标签目前是**位置启发式**（开头=钩子、结尾=CTA、中间=展示），不够贴合每个商品的实际视频逻辑。
- 未接入本地转写/分镜。可选：`faster-whisper`（CPU 转写）、`PySceneDetect`（场景切分）、OpenAI audio transcriptions API。
- 下一步优先级：① 配置 OPENAI_API_KEY 让 GPT 接管标签与排序；② 接入转写/分镜提升标签质量；③ 按商品批量出片。
