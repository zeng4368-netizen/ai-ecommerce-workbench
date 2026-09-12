# AI 电商工作台升级：GitHub 检索记录

日期：2026-09-07。已复用 2026-09-01 统一看板检索记录，本次补充可视化组件。

检索词：`site:github.com tabler tabler dashboard MIT`、`site:github.com apache echarts dashboard visualization`。

- https://github.com/tabler/tabler ：参考侧栏、工作区、指标卡的布局层级，不复制组件代码。
- https://github.com/apache/echarts ：直接使用 Apache-2.0 的 ECharts 5.6.0，存入 assets/vendor，供趋势图、散点图、构成图、排行使用，离线可用。许可证同目录保留。
- https://github.com/SheetJS/sheetjs ：沿用原页面已经使用的 SheetJS 0.18.5，下载本地副本用于上传预检、Excel 导出。许可证同目录保留。

实现决策：在现有独立 HTML 模块外增加工作台层，保留模块与 Skill 文件字节。重复的旧广告页面保留兼容入口；共用售后页的利润/售后子视图。新增分析单独标明计算口径。FastAPI 本地服务负责 SQLite 待办、日志与原清洗脚本调用。原 HTML 交互不迁移重写到 Streamlit，避免破坏已授权保留的功能。
