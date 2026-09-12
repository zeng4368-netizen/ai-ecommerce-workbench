# 原 Skill 深度整合检索记录

复用 2026-09-01、2026-09-07 的布局、图表与工作流检索。
本轮检索词：`site:github.com fastapi full-stack-fastapi-template`、`site:github.com pandas-dev pandas excel read_excel`。

- https://github.com/fastapi/full-stack-fastapi-template ：仅参考模块组织，不引入其 PostgreSQL/部署/账户系统，保留本地 SQLite。
- https://github.com/pandas-dev/pandas ：沿用已安装的 pandas/openpyxl 文件处理能力。

决定：无可直接替换用户自定义 Skill 的通用项目。复用现有 FastAPI、SQLite、图表组件与原 Skill 计算代码。原 HTML、Python Skill 文件不改动，以适配器连接统一版本化数据。

模型工具调用实现已核对官方文档：https://api-docs.deepseek.com/guides/tool_calls/ 和 https://api-docs.deepseek.com/api/create-chat-completion/ 。使用非思考模式与客户端验证，不依赖 beta strict 模式；模型只能调用白名单只读工具。
