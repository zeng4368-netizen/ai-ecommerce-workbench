# 工作台 GitHub 迁移选型记录

日期：2026-09-12。用户要求新建私有仓库，迁移源码、真实数据和 AI 接手说明。

## 检索与取舍

- 官方项目 https://github.com/cli/cli ：采用 GitHub CLI，不引入另一套工作台模板。
- https://cli.github.com/manual/gh_repo_create ：创建仓库支持显式 `--private`；上传前需核实仓库所有者和可见性。
- https://cli.github.com/manual/gh_release_create ：数据快照可作为 Release 附件，与可持续开发的源码分开管理。
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository ：删除工作区文件不能保证从 Git 历史清除密钥；凭据不进入明文源码提交。

现有 `frontend/unified_skill_dashboard/package_workbench.py` 可复用作纯代码包参考，但其排除运行数据与密钥，不能把它当作完整业务迁移包。完整迁移还需数据库一致快照、原始表格、内容图片、清单校验与新电脑恢复验收。

## 本次检查

- 工作目录原先不是 Git 仓库。
- 连接的 GitHub 账号：zeng4368-netizen；当前连接提供仓库内容操作，但无新建仓库接口。
- 通过 winget 安装 GitHub 官方 CLI，安装器校验通过；创建/推送前需要用户完成 CLI 登录。
- 拟用仓库名 ai-ecommerce-workbench，必须私有；此记录不表示仓库已创建或文件已上传。
- 业务数据允许按用户要求迁移到私有仓库/附件；API 密钥若迁移需独立加密，紫鸟在新电脑重新核验授权，不复制个人浏览器 Cookie。
