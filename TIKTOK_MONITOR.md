# TikTok 账号数据监控

本模块通过 TikTok 官方 Login Kit 和 Display API 接入账号，读取该账号的公开视频及播放量、点赞量、评论量、分享量，并将每次同步结果作为历史快照保存在本地 SQLite。

## 能力边界

- 支持：公开视频列表、播放量、点赞量、评论量、分享量、互动率、变化趋势。
- 评论量是数字指标；如需读取和分类评论正文，需要 TikTok Business Account Organic API 的额外权限。
- TikTok 当前没有用于指标变化的实时 webhook。系统使用周期轮询，默认 5 分钟一次。
- 只读取并生成看板，不会发布视频、回复评论或修改账号内容。

## 1. 创建 TikTok 开发者应用

1. 登录 [TikTok for Developers](https://developers.tiktok.com/)。
2. 创建应用，启用 Login Kit 和 Display API。
3. 申请并启用 `user.info.basic`、`video.list` 两个 scope。
4. 本地运行请选择 **Desktop** 平台，并登记回调地址：`http://127.0.0.1:8000/tiktok/oauth/callback`。系统会自动使用 PKCE。
5. 正式 Web 部署时请选择 Web 平台、使用已登记的 HTTPS 回调地址，并把 `TIKTOK_LOGIN_PLATFORM` 改成 `web`。

## 2. 本地配置

复制 `.env.example` 为 `.env`，填写：

```dotenv
TIKTOK_CLIENT_KEY=你的ClientKey
TIKTOK_CLIENT_SECRET=你的ClientSecret
TIKTOK_REDIRECT_URI=http://127.0.0.1:8000/tiktok/oauth/callback
TIKTOK_LOGIN_PLATFORM=desktop
TIKTOK_SCOPES=user.info.basic,video.list
TIKTOK_SYNC_INTERVAL_SECONDS=300
```

Client Secret、access token 和 refresh token 仅保存在本机；不要提交 `.env` 或 SQLite 文件。

## 3. 启动与授权

首次运行先安装项目依赖：

```powershell
python -m pip install -e ".[dev]"
```

启动本地 API（OAuth 回调必须使用）：

```powershell
uvicorn ecom_ops.api.main:app --host 127.0.0.1 --port 8000
```

启动 Streamlit 看板：

```powershell
streamlit run src/ecom_ops/ui/streamlit_app.py --server.port 8501
```

打开 `http://127.0.0.1:8501`，进入 `TikTok Account Monitor`，生成授权链接并完成 TikTok 登录授权。

## 4. 周期同步

单次同步：

```powershell
ecom-ops tiktok-sync
```

持续同步（默认读取 `.env` 的 300 秒间隔）：

```powershell
ecom-ops tiktok-worker
```

也可以指定间隔，最短 60 秒：

```powershell
ecom-ops tiktok-worker --interval 300
```

## API

- `GET /tiktok/oauth/start`：跳转到 TikTok 授权。
- `GET /tiktok/accounts`：已连接账号。
- `POST /tiktok/sync`：立即同步。
- `GET /tiktok/overview?open_id=...`：汇总指标。
- `GET /tiktok/videos?open_id=...`：视频表现。
- `GET /tiktok/timeseries?open_id=...`：历史趋势。
