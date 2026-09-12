# 内容工作室 GitHub 检索与取舍

日期：2026-09-08。需求：在既有本地 FastAPI / SQLite 电商工作台中增加产品文案、商品图与竞品研究工作流，不启用付费生成 API。

检索：`site:github.com fastapi full-stack-fastapi-template`、`site:github.com invoke-ai InvokeAI canvas workflow image generation`。

- https://github.com/fastapi/full-stack-fastapi-template ：参考独立路由/业务模块组织。不引入 React、云部署或认证模板，不替换当前前端与原 Skill。
- https://github.com/invoke-ai/InvokeAI/releases ：参考素材集合、工作流、结果版本的组织方式。未直接安装；本任务不需要引入 GPU 推理依赖或替换当前会话生图工具。

取舍：新增独立 content_studio 模块，共享现有 SQLite 连接但独立表，沿用现有 UI 组件。保留不可变原图和任务修订。当前以可下载的会话任务包对接人工回填，不构造“网页可直接调用聊天额度”的假接口。官方 API 扩展入口明确返回未配置，不自动调用现有 DeepSeek 配置。

规则来源：用户附件原文复制至 `frontend/unified_skill_dashboard/content_rules/product_images_v2.txt`，任务记录 SHA256。使用 ecom-image2 的产品锁定、图序策划思路，用户 V2.0 优先；未使用其 CLI 服务或外部模型调用路径。
