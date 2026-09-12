# GitHub 检索记录：统一 Skill 运营看板

- 检索日期：2026-09-01
- 目标：把现有 GMV Max、广告、售后、日销库存 HTML 工具合并到一个模块化看板，同时保持各模块的算法、表头、导入导出逻辑不变。

## 检索关键词

1. `site:github.com static HTML dashboard sidebar iframe tabs multi page`
2. `site:github.com tabler dashboard static HTML sidebar tabs`
3. `site:github.com StartBootstrap simple sidebar dashboard`

## 相关项目

### StartBootstrap Simple Sidebar

- 地址：https://github.com/StartBootstrap/startbootstrap-simple-sidebar
- 许可证：MIT
- 可参考内容：响应式侧边栏、单页导航外壳。
- 结论：结构适合参考，但完整引入 Bootstrap 会增加外部依赖，没有必要直接复制。

### Tabler

- 地址：https://github.com/tabler/tabler
- 许可证：MIT
- 可参考内容：模块化后台看板布局、响应式导航。
- 结论：功能全面但体积和构建链较重，不适合仅做本地 HTML 拼接。

### FlexDash

- 地址：https://github.com/flexdash/flexdash
- 可参考内容：使用 iframe tab 嵌入独立看板，并复用已加载的 iframe 状态。
- 结论：其 iframe 模块思路与本任务最接近；不直接引入项目代码，仅采用“独立模块隔离、按需加载、切换不销毁”的架构思路。

## 最终决策

使用无第三方框架的静态 HTML 外壳：

- 原始 HTML 原样复制到 `modules/`，不修改任何算法、表头或数据处理逻辑。
- 统一入口通过 iframe 隔离并加载各模块，避免全局 JavaScript、CSS 和本地状态互相污染。
- 模块第一次打开时才加载；之后切换仅隐藏，不重新加载，避免用户已导入的数据丢失。
- Python 清洗技能及说明文档原样复制到 `skills/`，在统一入口提供资源和运行说明。

本次仅参考布局与容器架构，没有直接使用第三方项目代码。
