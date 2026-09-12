# 内容工作室

入口：http://127.0.0.1:8765/#content-studio 。仍为本地服务，不公开部署。

## 两条流程

1. **新建生成任务**：登记已确认事实、不可变外观和缺失信息，上传产品/风格参考图；选择 6–10 张详情图（默认8），方图固定主图1+副图8。下载会话任务包，在具备生图工具的会话中策划、确认和生成，回填 plan.json 与独立图片，人工审核后导出。
2. **导入已有成品实例**：保存用户标题和详情原文，选择详情图数量，批量选择文件并确认图片与位置的对应关系，原样归档。可以查看图册、分类浏览、复制文案和下载整套实例。不要求伪造一份 AI 策划才能展示已有素材。

网页不能调用聊天订阅额度。当前没有网页一键自动生图，也未接入付费图像 API。`generate` 扩展入口明确返回503，现有 DeepSeek 密钥不会用于内容生图；此状态不是假同步或假成功。未来接入模型应在服务端新增实际适配器、费用确认、失败重试和任务状态，不改变现有事实/版本/素材管理接口。

## M98 展示实例

- 数据库任务：`2a1c47e896624b598adf8f2c2dac3258`。
- 用户原始文件：`data/raw/content_studio/m98-user-example-20260908/`。
- 01为主图，02–09为副图，10–16为详情图，共16张。详情图不是8张，不自动补造第17张。
- 标题161字符；详情保留原始 Markdown。生成样稿未混入此实例。
- `manifest.json` 记录每个源文件的 SHA256；图片归档不重新编码。
- 部分详情图含4GB/1080P、TX98盒式机身、不同遥控器，与M98标题不一致。原图保留，实例中另列核对提示，不把素材内容自动加入已确认产品事实。
- 这套图的来源是用户提供，不能作为“工作台本次通过API自动生成”的证据，也不等同于上架合规或产品性能认证。

## 规则与数据

用户 V2.0 原文：`content_rules/product_images_v2.txt`；每个任务记录规则 SHA256。ecom-image2 的产品锁定、逐图策划思路用于工作流，具体数量、文案、产品真实性约束以用户规则和最新要求为准。已有成品原样归档是用户本次明确例外，不宣称通过新生图规则全部检查。

- 独立 SQLite 表：`content_projects`、`content_history`。原业务数据版本和指标不改变。
- 原图：`data/raw/content_studio/<project_id>/<asset_id>.<extension>`，不可变保存。
- 项目修改有修订号；并发旧版本写入返回409；原图重复上传不重复累计。
- 改资料/参考图使旧策划失效。旧策划和图片保留在审计历史，不能当作当前交付。
- 会话试制与人工确认分开；未经人工确认的内容只能导出内部样稿包。
- 生产结果图比例错误时拒绝，不自动裁切。已有实例允许保留不同尺寸/比例的原图。
- 研究结论分观察与假设，观察必须引用来源。链接仅保存，不由后端自动抓取；文字作为不可信数据安全显示。

## 接口（均以 /api/hub/content 为前缀）

- GET `/capabilities`、`/policy`：能力边界、原规则。
- GET/POST `/projects`；GET `/projects/{id}`；PUT `/projects/{id}/brief`。
- POST `/examples`：保存已有成品文案。
- POST `/projects/{id}/plan`、`/approve`：策划回填、试制/人工确认。
- POST `/projects/{id}/assets`：图片校验、不可变保存；GET `/assets/{asset_id}`：原图。
- POST `/projects/{id}/assets/{asset_id}/review`：逐图人工审核。
- GET `/projects/{id}/history?revision=N`：历史快照。
- GET `/projects/{id}/export?mode=handoff|preview|delivery|example`：会话包、试制包、已审核交付、原样实例。
- POST `/projects/{id}/generate`：预留，当前明确未配置，不执行模型调用。

## 验证

`python -X utf8 -m pytest frontend/unified_skill_dashboard/tests -q`

`python -X utf8 frontend/unified_skill_dashboard/tests/check_content_ui.py`：只读检查真实实例16张图片与源文件字节一致，图序、文案、ZIP下载、刷新和移动端。

`python -X utf8 frontend/unified_skill_dashboard/tests/check_hub_ui.py`：临时数据库内测试生成任务表单、成品实例表单、批量上传和不可信文案转义，不写入真实业务测试记录。
