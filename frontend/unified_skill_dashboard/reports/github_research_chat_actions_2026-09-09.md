# 聊天到行动联动检索

检索：site:github.com/open-webui/open-webui message actions custom tools
来源：https://github.com/open-webui/docs/blob/main/docs/features/extensibility/plugin/functions/index.mdx
参考：https://docs.openwebui.com/features/extensibility/plugin/functions/action/

取舍：采用逐条回复下的用户触发 Action 入口思路；继续使用现有 FastAPI、SQLite 和行动状态机，不引入另一套 UI 或执行任意 Python 的插件。点击后编辑并明确确认，复用已保存回答，不新增模型费用；来源从服务端分析审计读取，不相信客户端传入的证据。保留原指标与人工批准边界。
