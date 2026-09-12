# 六店账单批量导出：交付记录

## 用户范围与选型

用户要求扩展紫鸟账号下全部六家店，一次导出账单。仅使用各店「财务 → 交易 → 已结算」报表，日期按店铺运营时区取当月 1 日至当天。未采集订单列表、未启用定时、未调用付费 DeepSeek、未激活本批次业务版本。

GitHub 选型复用已保存的 `github_research_ziniao_2026-09-11.md`：https://github.com/ziniao-open/skills 。本次完整读取并使用本地 ziniao-shared、ziniao-store、ziniao-page Skill 及相关 reference，先 doctor 检查，再 store list 与财务页面身份核验。没有引入替代浏览器框架、Cookie 或私有 API；未重复检索相同项目。

## 实际导出结果

批次 `4f568ffe190b4564a3679beac172dd19`，六店日期均为 **2026-09-01～2026-09-11**，包含当天截至导出时的数据。

| 紫鸟店铺 | 页面实际店名 | 币种/时区 | 交易行 | 结算金额（不是利润） |
|---|---|---|---:|---:|
| MS0237-EXPOSE.TK | EXPOSE TK | MYR / UTC+8 | 1,678 | 105,047.72 |
| MS0352-JOURNEY.MY | OPLO. | MYR / UTC+8 | 104 | 4,879.83 |
| MS0319-EXPOSE & TechPioneer | Tech Pioneer TK | MYR / UTC+8 | 138 | 6,994.24 |
| MS0307-EXPOSE.Tech Wealth | Tech.wealth | MYR / UTC+8 | 678 | 37,100.39 |
| BS0573-EXPOSE Electronics Thailand | EXPOSE Electronics Thailand | THB / UTC+7 | 442 | 148,709.34 |
| MS0186-Tech Junction | Tech Junction | MYR / UTC+8 | 70 | 3,827.26 |

每店均以实际文件的报告页检查日期、币种、时区，并将交易明细的结算金额、收入、退款、费用、调整逐项对账。英文 MY 与英文 TH 分别保留 64/68 列原表头、原工作表和费用列，未覆盖中文版规范；泰国个人所得税等费用保留原列，不与父级金额重复相加。

六店原始 XLSX 已按运行 ID 存在 `data/raw/ai_workbench/imports/<run_id>/settlement.xlsx`，原平台文件名仍在任务中保存。打包文件：`data/output/ai_workbench/six_store_bills_20260901_20260911_4f568ffe.zip`，含六个店铺子目录及 manifest.json；ZIP 内每个文件 SHA256 与归档原文件一致。

开始采集前的 SQLite 备份：`data/processed/ai_workbench/workbench_before_six_stores_20260911_163619.sqlite3`。

## 实现与审核

- 配置在 `config/selectors.yaml` 的 ziniao_stores；固定环境 ID、紫鸟名称、页面身份、币种、时区和报表覆盖项。英文表头作为独立 YAML schema 复用，不改变原基准。
- `/api/hub/ziniao/batches` 一次原子创建 1～6 店任务；重名/重复 ID/未绑定店铺/已有未结束任务时不部分创建。逐店执行，店铺失败不阻止其他店。SQLite 互斥防止多服务同时操控不同店铺导出。
- 批次/子任务持久化，恢复不重算日期，不重复提交不确定的导出请求；已审核、已完成、已取消任务不重新导出。重启后不自动补跑队列，需人工继续。
- 单店配方、数据快照、版本、报告聊天证据和 AI 日额度均绑定本店。旧 EXPOSE 历史批次保留原范围，新增店数据不覆盖其他店。
- 六店 ZIP 仅在六份原文件均已取得且哈希一致时提供；如果存在待校验文件，界面与 manifest 明确标注，不能视为已校验。
- 旧计划默认仍只针对原店，不会自动扩展到六店收费。用户明确启用全部店计划时，必须六店均先审核。自动请求额度为每店本地自然日最多一次，六店可能合计六次，不是整个账号一次。
- 三份英文文件首次按旧中文规范解析时被安全暂停；在本次明确的接入工作中，用真实工作表建立英文 MY/TH 规范，并离线重新校验原文件，没有重新下载。`six_store_onboarding_audit.json` 和各任务 schema_reviews 保存原哈希、导出配置哈希和新规范哈希；导出环境身份、日期选择器和原文件必须不变才允许这次首批重验。
- 六份文件现在均为 pending_review；需用户确认才进入工作台分析版本/AI。当前数据 head 仍为 `1db6ecb9d27640dcaa9d92ea076c5277`，未替换。

## 验证及运行状态

- 全工作台 pytest：**83 项通过**（158.47 秒）。覆盖批量原子性、互斥、故障隔离、六店快照保留、独立 AI 额度、计划审核、时区切月、英文/泰文地区表头控制、ZIP 完整性；无付费请求。
- 新前端 JS 语法检查通过。桌面 1440px / 手机 390px 的六店入口、六店批量请求、按店查看、泰国金额、下载 ZIP 均通过；页面无脚本错误。浏览器测试的 POST 全部拦截，不创建真实重复任务。新版只读 API 在测试进程执行，未替换运行服务。
- 截图 `data/screenshots/ai_workbench/ziniao/six-store-panel-desktop.png` 与 `six-store-panel-mobile.png`。
- 本次检查时后台 PID 33388 仍是用户此前启动的单店版本，status 暂无 batch_supported。需用户重启后台加载最新代码。新前端在后台未升级时禁用采集、计划及任务写入按钮，防止混用新旧模块。
- 本次真实六店下载由显式执行的 `build_tools/collect_ziniao_batch.py --run` 走同一 SQLite 队列完成。该脚本要求计划关闭，不启动调度器、不调用模型。不是模拟导出。

## 使用

重启最新工作台 → 数据中心 → 紫鸟自动采集：可查看六店任务，下载全部账单 ZIP，逐店核对后导入。以后用「一键导出全部店铺账单」创建新批次；存在待审核任务需先处理，不会默默覆盖。

开发脚本 `review_six_store_schema.py` 仅针对本文固定首批，不能作为任意表头变更的自动放行机制。未来表头变化仍暂停人工审核。
