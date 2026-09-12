# Multica GitHub 检索与安装记录

- 日期：2026-08-04
- 目标仓库：https://github.com/multica-ai/multica
- 检索关键词：`site:github.com/multica-ai/multica multica installation README`
- 项目用途：开源托管式 Agent 管理平台，可分派任务、跟踪进度并复用技能。
- 官方 Windows CLI 安装方式：运行仓库中的 `scripts/install.ps1`。
- 官方完整自托管方式：设置 `MULTICA_MODE=with-server` 后运行安装脚本，需要 Docker 与 Docker Compose。
- 安全检查：安装脚本从 GitHub Releases 下载与系统架构匹配的 CLI 压缩包；若发布页提供 `checksums.txt`，脚本会校验 SHA-256；CLI 安装到 `%USERPROFILE%\.multica\bin` 并加入用户 PATH。
- 本机检查：Git 2.54.0、Node.js 24.15.0 已安装；Docker、pnpm、Go、Multica CLI 未安装。
- 本次决定：先安装并验证官方 Multica CLI。由于 Docker 缺失，不启动完整自托管服务，也不执行需要浏览器交互的登录配置。
- 参考文档：https://github.com/multica-ai/multica/blob/main/README.md
- CLI 文档：https://github.com/multica-ai/multica/blob/main/CLI_INSTALL.md
- 自托管文档：https://github.com/multica-ai/multica/blob/main/SELF_HOSTING.md

## Docker 前置环境安装结果

- 参考官方文档：https://docs.docker.com/desktop/setup/install/windows-install/
- 安装版本：Docker Desktop 4.85.0（当前用户模式，WSL 2 后端）
- 安装位置：`C:\Users\PC\AppData\Local\Programs\DockerDesktop`
- Docker CLI：29.6.2
- Docker Compose：v5.3.1
- 安装包校验：SHA-256 `5417cedc1aeb16b488b8084025246b64a5e9da4d71388f324b107140dfe00699`，Authenticode 签名有效
- WSL：2.7.11.0；Linux 内核 6.18.33.2-2
- 当前状态：Windows 已标记需要重启。重启前 WSL 2 虚拟机平台尚未生效，Docker 引擎不能完成启动。
- 重启后验证：运行 `wsl --status`、`docker version` 和 `docker run --rm hello-world`。

## Multica 自托管部署结果

- 部署版本：v0.4.17 源码归档；容器镜像使用官方 `latest` 稳定标签。
- 安装目录：`C:\Users\PC\.multica\server`
- 环境配置：已从 `.env.example` 创建本地 `.env`，并生成随机 JWT 与 PostgreSQL 密码；密钥未写入本记录。
- 前端：http://127.0.0.1:3000
- 后端：http://127.0.0.1:8080
- 健康检查：后端 `/health` 返回 HTTP 200 和 `{"status":"ok"}`；前端返回 HTTP 200；PostgreSQL 容器状态为 healthy。
- 容器：`multica-frontend-1`、`multica-backend-1`、`multica-postgres-1`。
- 说明：GitHub 浅克隆因代理连接停滞，未完成目录已可恢复地移动到 `C:\Users\PC\.multica\server-incomplete-20260804-1800`；正式部署改用相同 v0.4.17 官方源码归档。
- 启停命令：在安装目录运行 `docker compose -f docker-compose.selfhost.yml up -d` 或 `docker compose -f docker-compose.selfhost.yml down`。
