# Multica GitHub 搜索与安装记录

- 日期：2026-08-04
- 搜索目标：可直接用于 AI Agent 任务管理和编排的成熟项目
- GitHub 项目：https://github.com/multica-ai/multica
- 选择结论：采用用户指定的官方仓库，不使用名称相近的镜像或非官方分支
- 核对时状态：43,722 stars，5,536 forks，默认分支 `main`
- 稳定版本：`v0.4.17`（2026-08-03 发布）
- 固定源码提交：`6b56bc05a4a5e3e189ff1da9ce31bdf465ac5528`
- Windows CLI 资产：`multica-cli-0.4.17-windows-amd64.zip`
- 安装方式：官方 Windows 安装器，下载 GitHub Release 并校验 SHA-256
- 本地源码目录：`external/multica/`
- CLI 安装目录：`%USERPROFILE%\.multica\bin\multica.exe`

## 技术栈与依赖

- 前端：Next.js 16
- 后端：Go
- 数据库：PostgreSQL 17 + pgvector
- 本地 Agent：Multica CLI/daemon
- 完整自托管：需要 Docker 与 Docker Compose
- 源码开发：需要 Node.js、pnpm、Go 和 Docker

## 当前机器结论

- 已有 Git、Node.js 和 npm
- 尚无 Docker、Go、pnpm
- 因此本次安装固定版本源码与 Windows CLI；不启动完整自托管栈
- `multica setup` 涉及账号登录、授权和 daemon 启动，保留给用户明确执行

## 安装结果

- Windows CLI 已安装并通过官方 SHA-256 校验
- 版本验证：`multica 0.4.17`，commit `6b56bc05a`
- 用户 PATH 已包含 `%USERPROFILE%\.multica\bin`
- 固定源码已解压至 `external/multica/`，来源标记与 lock 文件一致
- 已加入 AI 电商工作台“成熟平台中心”

## 许可证提醒

仓库 SPDX 标识为 `NOASSERTION`。项目的 Multica License 以 Apache-2.0 为基础，但增加了托管服务、商业分发和品牌展示等条件。用于向第三方提供托管服务或嵌入商业分发产品前，应先核对许可证并联系项目方取得商业许可。
