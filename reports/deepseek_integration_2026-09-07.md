# DeepSeek 接入记录

沿用已有工作台与已有 GitHub 检索记录 reports/github_research_ai_ecommerce_workbench_2026-09-07.md，不引入新看板框架，不修改原 Skill。

2026-09-07 核对官方文档：https://api-docs.deepseek.com/zh-cn/
- 官方 OpenAI 兼容地址：https://api.deepseek.com
- 文档当前列出 deepseek-v4-flash 与 deepseek-v4-pro，默认选 flash 用于运营分析。
- 使用 chat/completions、Bearer 验证；禁止重定向与任意外部地址，密钥仅存本地 .env。
- 输入使用原有快照的规则汇总与带编号的证据，保留各模块独立周期/币种。
- SQLite 保存报告、输入依据摘要哈希、实际返回模型名和 token 用量。无自动业务动作。

## 实际验证

通过工作台页面进行了两次真实分析调用，均返回 deepseek-v4-flash、finish_reason=stop。
- 初次接入验证：29d2449a485e432f8dd8ece34bbd9c20，6126 Tokens。
- 增强边界约束后：cfa44abfe8fb4ca8b28e12441f2d47f5，6076 Tokens。
- 共 12202 Tokens；不臆测账单金额，以 DeepSeek 账户账单为准。

复核发现：模型仍可能发生计数错误及超出证据的推断，已在 data/processed/ai_workbench/review_notes.json 单独记录，页面历史报告展示这些备注，保留模型原文。此记录不能作为实际经营收益已验证的证明。
