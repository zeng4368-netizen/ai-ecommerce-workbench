# 行动中心升级检索

日期：2026-09-07。检索：GitHub kanban task workflow human approval AI task management；langchain-ai human-in-the-loop approval。

- https://github.com/earlyprototype/kanbanger ：参考服务端强制 REVIEW 后才能 DONE 的验收关卡。
- https://github.com/bricef/Taskflow ：参考显式状态机与 human/AI 分工。
- https://github.com/langchain-ai/docs/blob/main/src/oss/langchain/human-in-the-loop.mdx ：参考模型建议与人工批准分离、状态持久化。

结论：上述项目不含本工作台的电商口径和快照数据，直接替换会破坏已有集成。参考状态机和确认关卡设计，在现有 FastAPI/SQLite/HTML 上实现独立模块，不引入完整框架，不复制外部源码，不改原 Skill。

实际测试：已对现有数据同步94个冻结候选；任务 a89c56e00f67f6d0318d6ab7821d5643 调用 deepseek-v4-flash 生成结构化草案，1118 Tokens，证据引用 ADS-1 校验通过。仍为 candidate，未代替用户批准或执行。完整状态流转在隔离数据库/模拟模型中测试，不污染真实业务状态。
