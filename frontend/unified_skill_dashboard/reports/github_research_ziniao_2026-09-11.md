# 紫鸟采集选型与当前边界

检索日期：2026-09-11。关键词：site.github.com/ziniao-open/skills store automation CLI。

- https://github.com/ziniao-open/skills ：官方店铺/页面 Skill，复用已安装 CLI 和本地授权。
- https://github.com/ziniao-open/skills/blob/main/skills/ziniao-page/references/ziniao-page-automation.md ：步骤编排参考；实际参数以本机 CLI help 为准。
- https://www.npmjs.com/package/@ziniao-open/cli ：官方包；不引入第三方 Cookie/CDP 旁路。

取舍：现有 FastAPI/SQLite 内增加持久化任务和受限导出适配器，不替换工作台。模型只能读取经过字段白名单过滤的指标/证据，不控制 CLI。下载目录能力不等于已成功下载报表，必须验证本次文件来源、完整性和业务范围。

备份：D:/codex/data/output/ai_workbench_backups/20260911_114436（原模块/skills、SQLite 在线备份和校验清单）。

前置状态变更：用户确认更新客户端后，doctor 的配置、Key 与终端绑定、客户端账号、Bridge 明细全部通过，旧版终端绑定警告已消失。

真实联调：仅打开/复用 `27007200298613 / MS0237-EXPOSE.TK`，页面可见店铺身份为 `EXPOSE TK`。没有读取 Cookie 或调用私有 HTTP 接口。

- 订单：全部标签页，创建日期 2026-09-04 至 2026-09-10（MY/UTC+8），筛选出的 1,040 笔订单，CSV 2,549 行，1,040 个唯一订单 ID。
- 结算：已结算页面，在独立导出日历选同一日期范围；文件内「报告」明确 UTC+8/MYR/时间范围。1,082 条交易，明细结算金额 70,663.93，与文件汇总一致。
- 结算 XLSX 的 `<dimension>` 标记错误：默认只读出 1 条、24 列。对新原生解析器使用 `reset_dimensions()` 后读取 1,082 条、64 列，并执行总收入/退款/总费用/调整/结算金额五项对账。未修改原利润脚本。
- 订单唯一键：Order ID + SKU ID，实测无重复。结算订单号单独不唯一，采用订单/调整单ID + 交易类型 + 结算日期，实测无重复。未来冲突暂停人工审核，不加行号伪装唯一键。
- 两份真实平台记录已验证中断恢复：以导出时间、报告名、下载完成状态匹配归档，不重复提交导出。
- 日期控件使用不同实现，选择器已保存 `config/selectors.yaml` 的独立 `ziniao_collection` 节，原模板保留。

待人工确认：首批保存为 pending_review；尚未激活业务版本、未调用真实付费模型、未启用定时。真实次日定时执行需首批审核之后观察，不能把测试批次结果当作真实自动运行成果。
