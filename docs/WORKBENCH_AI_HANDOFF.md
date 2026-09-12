# AI 电商工作台：接手说明

更新时间：2026-09-12。先读根目录 AGENTS.md，再读本文。本文描述当前代码与本次只读检查，不把早期规划当作已完成能力。

## 正确入口

- 主工作台：`frontend/unified_skill_dashboard/server.py`，FastAPI + SQLite + pandas + 原 JavaScript Skill 引擎。
- 页面：`http://127.0.0.1:8765/`，仅本机运行，不部署公网。
- 启动脚本：`frontend/unified_skill_dashboard/启动综合看板.ps1`。
- 根目录早期 Streamlit、8000/8501 服务以及视频混剪工具不是主工作台启动入口，不要误替换。
- 工作台的数据根目录默认是仓库根目录 `data/`；可由 `WORKBENCH_DATA_DIR` 覆盖。不要硬编码旧电脑路径。

## 模块定位

| 功能 | 主要文件（相对主工作台目录） |
|---|---|
| 服务、模型配置、数据库连接 | server.py |
| 导入、版本、映射 | data_hub.py、hub_partitions.py、hub_pipeline.py |
| 原指标与模块适配 | skill_engine.cjs、module_adapter.py、modules/、skills/ |
| 只读 AI 查数与聊天 | query_assistant.py、chat_store.py、model_stream.py |
| 建议加入行动、行动跟踪 | chat_actions.py、action_center.py、hub_actions.py |
| 内容制作与素材实例 | content_studio.py、content_rules/ |
| 六店账单采集 | ziniao_bridge.py、ziniao_tiktok.py、ziniao_collection.py、ziniao_reports.py |
| 店铺身份、日期与选择器 | 仓库根目录 config/selectors.yaml |
| 测试与验证记录 | tests/、reports/ |

## 不允许改变的口径

原 Skill 的算法、筛选集合、表头顺序、工作表及百分比格式必须回归一致。新增分析须独立命名，不能偷偷修正旧指标。退款金额占比不是订单退款率，结算金额不是利润；MYR 与 THB 不能直接合计。缺失资料不能伪造，缺失映射不能用猜测关联。

原广告四个脚本及固定 49 列规范仍有资料缺口。TikTok/马帮官方 API 占位连接器与紫鸟浏览器导出是两种不同能力，不得标为同一种已接通接口。

## 紫鸟当前需求与验证

最新需求已取代最早“最近 7 天订单和结算”：只导出各店 **财务 → 交易 → 已结算** 的“账单”，按该店运营时区选择当月 1 日到当天，包含当天尚未结束的数据。

六店绑定、真实导出结果、金额、验证范围和已知限制见：

`frontend/unified_skill_dashboard/reports/six_store_bills_2026-09-11.md`

2026-09-12 只读检查：SQLite quick_check 为 ok；任务状态为 complete 2、cancelled 3、pending_review 6；定时计划 enabled=false。这是检查时快照，不是以后运行时的固定状态。六店首批仍需用户审核，不自动激活。

只能经服务端白名单调用官方 ziniao-cli；禁止读取 Cookie、借用个人浏览器配置或让模型执行任意命令。身份不符、登录失效、验证码、表头变化均暂停。不要自动退款、调价、投放、发送消息或发布商品。

`build_tools/review_six_store_schema.py` 是固定首批的人工接入辅助脚本，不可当作未来任何表头变化的自动放行机制。`validate_ziniao_pilot.py` 不是恢复用户数据的通用工具。

## 数据与迁移边界

- 当前业务数据库：`data/processed/ai_workbench/workbench.sqlite3`，包含版本、聊天、行动、内容项目和采集记录。
- 原始表格：`data/raw/ai_workbench/`。
- 内容素材：`data/raw/content_studio/`，不能只复制数据库而漏掉图片。
- 产物：`data/output/ai_workbench/`、`data/output/content_studio/`；历史提取表、备份和其他实际输入也应在打包清单中说明是否包含。
- 原模块、内嵌历史数据及本地前端资源位于主工作台目录，也可能含真实业务数据；仓库必须保持私有。
- `.env` 与授权材料不得硬编码到源码。若迁移密钥，应使用独立加密包，解密口令不要放在同一仓库。
- 不迁移浏览器 Cookie 数据库或个人浏览器 profile。紫鸟新电脑须安装客户端、登录并完成 CLI 授权/doctor 复检；不能承诺复制授权即可跨设备使用。
- 数据打包须使用 SQLite backup API 获取一致快照；不要直接复制正在写入的数据库。备份不能替换源库。

## 开发与验证

Python 3.11+，Node.js 为原 Skill 计算所需。先安装主工作台 requirements；测试需要 pytest、httpx，浏览器测试另需 Playwright。

```powershell
python -m pytest frontend/unified_skill_dashboard/tests -q
node frontend/unified_skill_dashboard/tests/test_analysis.cjs
node frontend/unified_skill_dashboard/tests/test_question_context.cjs
```

历史验证结果必须带日期；本次仅迁移准备，未重新运行全套业务测试。涉及真实采集的脚本不是普通单元测试，未经用户要求不得运行。普通测试应使用临时数据库，不消费模型额度。

## 给新 AI 的开场指令

> 请先阅读 AGENTS.md、docs/WORKBENCH_AI_HANDOFF.md、docs/WORKBENCH_MIGRATION.md，以及主工作台 reports/six_store_bills_2026-09-11.md。检查实际代码、数据目录和服务版本后再开发。保留原 Skill 算法和历史记录，不公开项目，不自动启用采集或付费分析，不触碰浏览器 Cookie。不要把未验证功能称为已完成。
