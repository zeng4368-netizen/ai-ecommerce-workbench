# 自动混剪智能体

本模块把历史表现数据、授权素材、结构化视频理解、约束式混剪、人工时间线和审核记录放在同一个本地工作流中。20 万行历史指标可以全量入库，但素材只按商品按需处理：

    指标快照 -> 每商品 Top 30 -> 下载与去重 -> 最多分析 15 条 -> 3 条候选 -> 人工审核

## 安全边界

- 素材只能来自本地文件、授权直链或用户提供登录态的 yt-dlp。
- 登录、验证码、2FA、HTTP 403/429 会暂停任务，不绕过验证。
- 公共解析通道默认关闭，仅在 MIXER_USE_TIKWM_FALLBACK=true 时作为末级备选。
- 不跨商品混剪；不足 6 条素材不自动出片。
- 不克隆达人声音，不自动发布，不自动删除素材。
- 首个商品标签模板必须人工批准，所有时间线和审核均版本化留痕。

## 启动

    python -m pip install -e .
    npm --prefix frontend/video_timeline install
    npm --prefix frontend/video_timeline run build
    streamlit run src/ecom_ops/ui/streamlit_app.py
    uvicorn ecom_ops.api.main:app --host 127.0.0.1 --port 8000

工作台默认地址为 http://127.0.0.1:8501，API 文档为 http://127.0.0.1:8000/docs。

## 配置

在 .env 中配置：

    OPENAI_API_KEY=
    OPENAI_BASE_URL=https://api.openai.com/v1
    MIXER_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
    MIXER_VISION_MODEL=gpt-5-mini
    MIXER_TTS_MODEL=gpt-4o-mini-tts
    MIXER_TTS_VOICE=marin
    MIXER_DAILY_BUDGET=0
    MIXER_DOWNLOAD_CONCURRENCY=2
    MIXER_RENDER_CONCURRENCY=1
    MIXER_USE_TIKWM_FALLBACK=false
    MIXER_COOKIES_FILE=
    MIXER_COOKIES_FROM_BROWSER=

没有 OPENAI_API_KEY 时仍可导入、评分、下载、镜头切分和使用工作台；视觉标签会标记为待云端分析，不能越过低置信边界自动出片。

## 命令行

    ecom-ops mixer-import "视频数据.xlsx" --ad-file "广告数据.xlsx"
    ecom-ops mixer-worker --once
    ecom-ops mixer-worker --interval 5
    ecom-ops mixer-evaluate gold.jsonl predictions.jsonl

后台任务使用 SQLite 租约、心跳、重试和过期恢复。也可以在工作台的“分析任务”页手动运行下一项任务。

## API

- POST /mixer/imports
- GET /mixer/products
- POST /mixer/products/{id}/analyze
- POST /mixer/taxonomies/{id}/approve
- POST /mixer/projects
- PATCH /mixer/projects/{id}/timeline
- POST /mixer/projects/{id}/render
- POST /mixer/renders/{id}/approve
- GET /mixer/jobs
- POST /mixer/jobs/run-next

## 数据与输出

- 原始表格和授权视频：data/raw/
- 代理、音频、关键帧和切片：data/processed/
- 原声版、旁白版、SRT、封面、时间线和来源清单：data/output/mashup/
- 浏览器步骤截图：data/screenshots/
- 运行日志：logs/
- 导入批次、指标快照、素材、片段、模板、任务、时间线和审核：SQLite

## 评分

同一商品、同一批次内计算：净 GMV 20%、订单 10%、千次曝光 GMV 15%、平滑 CTR 10%、广告转化/ROAS 15%、2 秒/6 秒观看 10%、完播率 10%、互动率 5%、样本可信度 5%。金额、千分位和百分比会被规范化；缺失指标会自动重算有效权重。

S 级要求样本不少于 10 条、可信度达标且位于前 5%；A/B/C 分别按后续 15%、30% 和其余素材划分。退款会进入净 GMV 和风险扣分。

## 测试

    python -m pytest -q
    python -m ruff check src tests

GitHub 选型与许可证记录见 reports/github-search-records/video-mixer-agent-search-2026-08-19.md。
人工金标格式见 config/video_mixer_gold_set.example.jsonl；验收器会强制要求至少 5 个商品、50 个片段。
