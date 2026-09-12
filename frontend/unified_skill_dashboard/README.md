# 商策 · AI 电商工作台

已升级为面试演示与本地运营工作台。原始模块、算法与表头继续保留。

启动：在此目录运行 `python server.py --port 8765` 或 `启动综合看板.ps1`，访问 http://127.0.0.1:8765/ 。首次使用新环境先安装 `requirements.txt`。

也可直接打开 `index.html` 查看离线图表与规则分析。脚本清洗、SQLite 和 DeepSeek AI 分析需要服务。

在「AI 分析助理」选择范围并点击「生成 AI 分析」。本机已配置 DeepSeek；点击才会发送证据摘要并消耗 API 额度。报告与输入依据保存在本地分析历史，原 Skill 算法不变。`.env` 不要分享或打包。

行动中心已升级：候选 → AI草案 → 人工确认入列 → 执行记录 → 复盘验收。使用方法见 [行动中心说明](ACTION_CENTER_GUIDE.md)。

面试时点击右上角「面试演示」进入六步演示，自动开启显示脱敏。工程文件本身仍包含原始数据。

完整功能、计算口径、模型配置、数据保存路径和验证方式见 [WORKBENCH_GUIDE.md](WORKBENCH_GUIDE.md)。

原合集入口备份：`index.v1.backup.html`。
