# AI 电商工作台

AI 电商工作台是本项目的统一本地入口，当前包含：

- 运营总览与 AI 决策留痕
- 销售分析 Agent
- 投诉登记 Agent
- TikTok 自然流量监控
- TikTok 广告投放只读报表
- Postiz 与 BrightBean Studio 成熟平台入口和健康检查
- Multica AI Agent 任务工作台入口和健康检查

## 启动

首次安装：

```powershell
python -m pip install -e ".[dev]"
```

同时启动 FastAPI 与 Streamlit：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_workbench.ps1
```

打开：

- 工作台 UI：http://127.0.0.1:8501
- 本地 API 文档：http://127.0.0.1:8000/docs

## TikTok 自然流量

在 `.env` 中配置 TikTok for Developers 应用：

```dotenv
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=http://127.0.0.1:8000/tiktok/oauth/callback
TIKTOK_SCOPES=user.info.basic,video.list
```

进入“TikTok 自然流量”生成授权链接。该模块只读取公开视频和累计指标。

## TikTok 广告报表

在 `.env` 中配置 TikTok API for Business 的只读授权：

```dotenv
TIKTOK_BUSINESS_ACCESS_TOKEN=
TIKTOK_BUSINESS_ADVERTISER_ID=
TIKTOK_ADS_REPORT_DAYS=30
```

同步命令：

```powershell
ecom-ops tiktok-ads-sync --days 30
```

工作台读取 `/open_api/v1.3/report/integrated/get/`，保存 advertiser 和 campaign
日级报表。它不会创建、暂停、调价或修改广告。

## 成熟平台

固定版本源码存放在：

- `external/postiz-app/`
- `external/brightbean-studio/`
- `external/multica/`

重新获取固定版本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_external_integrations.ps1
```

本机当前没有 Docker。安装 Docker Desktop 后，分别根据两个项目自己的 README/Compose
启动服务，然后配置：

```dotenv
POSTIZ_URL=http://127.0.0.1:4200
BRIGHTBEAN_URL=http://127.0.0.1:8001
MULTICA_URL=http://127.0.0.1:3000
```

工作台不会把外部项目代码复制到核心包，也不会代替用户执行发布或 Agent 任务。Multica 使用带附加条件的 Multica License；完整自托管同样需要 Docker。

## 质量检查

```powershell
python -m ruff check src tests
python -m mypy src/ecom_ops
python -m pytest --tb=short -q
```

所有敏感凭据必须放在本地 `.env`；不要把 `.env`、SQLite 数据库、Cookie 或 Token
提交到版本库。
