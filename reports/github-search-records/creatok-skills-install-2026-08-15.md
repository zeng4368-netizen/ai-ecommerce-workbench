# CreatOK Skills GitHub 搜索与安装记录

- 日期：2026-08-15
- 搜索目标：用户指定的 GitHub 项目，TikTok 创作者/卖家可用的 AI Agent skills 集合
- GitHub 项目：https://github.com/EchoSell/creatok-skills
- 选择结论：采用用户指定的官方仓库；该仓库为纯文档（无运行时代码），技能与 CLI 一起分发
- 仓库状态：文档型仓库，`README.md` + `AGENTS.md`，无 `skills/` 目录
- 本地源码目录：`external/creatok-skills/`
- 安装方式：
  - `npm install -g @creatok/cli`
  - `creatok skills install --dir C:\Users\PC\.codex\skills`
- CLI 版本：`v0.10.2`（commit `a6d8342`，skills_hash `2e5afaf8c674`）
- 已安装 skills（12 个）：
  - `creatok-analyze-video` 2.1.1
  - `creatok-avatar` 1.0.9
  - `creatok-generate-image` 2.1.5
  - `creatok-generate-video` 2.4.1
  - `creatok-image-upscale` 1.0.15
  - `creatok-optimize-prompt` 1.1.1
  - `creatok-publish-tiktok` 1.0.4
  - `creatok-recreate-video` 2.1.1
  - `creatok-seedance2-copilot` 1.0.0
  - `creatok-video-subtitle-remover` 1.0.16
  - `creatok-video-upscale` 1.0.18
  - `creatok-video-watermark-remover` 1.0.15

## 环境结论

- 已有 Node.js 24.15.0 与 npm 11.12.1，无需额外安装
- CLI 为 npm 全局安装，无需 Docker

## 安装结果

- `creatok version` 返回 `{"ok":true,"cli_version":"v0.10.2"}`
- skills 已写入 `C:\Users\PC\.codex\skills\`，每个 skill 含 `SKILL.md` 与 `references/`

## 待用户操作

- 在 https://www.creatok.ai/app/workspace/api-keys 生成 API Key
- 设置环境变量 `CREATOK_API_KEY`（示例：`export CREATOK_API_KEY="ok_xxx"`）
- 重启 Codex 会话后技能即可被识别使用

## 更新记录

- 2026-08-15：用户已提供 API Key，已通过 .NET API 写入用户级环境变量 `CREATOK_API_KEY`（未写入任何项目文件/日志）
- 2026-08-15：`creatok doctor` 复核通过，`api_key_configured: true`、`reachable: true`，12 个 skills 状态全部 `ok`
