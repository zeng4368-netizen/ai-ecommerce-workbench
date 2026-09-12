# 工作台运营优化检索

复核既有 `github_research_skill_integration_2026-09-08.md` 后，补查：

- `site:github.com fastapi full-stack-fastapi-template` → https://github.com/fastapi/full-stack-fastapi-template 。继续参考模块组织，不迁移 React/PostgreSQL 或公网部署。
- `site:github.com EvidentlyAI evidently data quality` → https://github.com/evidentlyai/evidently 。参考缺失值、重复值、范围和数据质量报告的检查分类；不引入整套 ML 监控依赖，不把统计漂移当经营原因。

决定：现有原 Skill 的计算与输出是业务基准，没有能直接替换的通用项目。本轮实现本地分区更新、透明的数据健康检查、商品档案和人工反馈；复用 SQLite、pandas、原 JS 计算及已有可视化组件。新增指标明确命名，原文件不改。
