# 聊天式 AI 工作区检索与取舍

2026-09-09。需求：聊天式页面、独立会话持久化、自然上下文、普通问题与按需工作台查数。

- 检索 GitHub 的 Open WebUI、FastAPI 官方模板。
- https://github.com/open-webui/open-webui ：参考会话列表、消息流、输入栏和数据工具组织方式，不直接引入整套独立部署或其前端框架，不复制品牌或声称是GPT。
- https://github.com/fastapi/full-stack-fastapi-template ：保留现有 FastAPI 模块化路由组织，不换框架。
- https://api-docs.deepseek.com/api/create-chat-completion ：依据官方流式返回结构解析 delta、tool_calls、usage 和完成原因。保持现有官方接口地址限制与服务端密钥。

实施采用现有 SQLite + 原生前端，保留旧 analyses 与 hub_conversations，新增聊天管理、消息状态、真实SSE输出及上下文保护。普通问题不强制查数，工作台工具仍只读；不增加公网部署或平台写入能力。
