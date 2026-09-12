# 换电脑运行工作台

本说明于 2026-09-12 整理。仓库：https://github.com/zeng4368-netizen/ai-ecommerce-workbench （私有）。配套快照见仓库 Releases；附件是否上传完整以实际附件和 SHA256 清单为准。

## 需要迁移的三部分

1. 私有仓库中的源码、原 Skill、前端资源、配置模板与项目说明。
2. 与源码配套的真实业务数据快照及原始图片、表格。只有源码不足以恢复已有聊天、行动和采集记录。
3. 本机运行环境及账号配置。密钥使用独立加密包或自行恢复 `.env`；加密包口令单独保管。紫鸟设备授权须在新电脑复检，必要时重新授权。

不要上传明文 `.env`、浏览器个人配置、Cookie、登录态、私钥或未经检查的原始运行日志。私有仓库不能代替密钥管理。

## 新电脑准备

安装 Python 3.11+、Node.js、Git（需要继续开发时）及紫鸟客户端。克隆完整仓库后保持目录结构，数据包恢复到仓库根目录，而不是主工作台子目录。

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r frontend/unified_skill_dashboard/requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest httpx
```

将工作台 `.env` 恢复到 `frontend/unified_skill_dashboard/.env`；没有备份时复制该目录的 `.env.example` 并填写自己的配置。根目录 `.env` 不等同于工作台 `.env`。不要把填好的文件提交到 Git。

## 获取数据与解密配置

在 GitHub 仓库的 Releases 下载 `workbench-data.zip`、`workbench-credentials.fernet`、`migration-manifest.json`。核对 manifest 的 artifacts 中 SHA256；例如 `Get-FileHash workbench-data.zip -Algorithm SHA256`。

将 `workbench-data.zip` 解压到仓库根目录，保持 `data/raw/...`、`data/processed/...` 的层级。请在新目录恢复，不覆盖已有业务数据。

解密钥匙是旧电脑的 `data/recovery/github-migration-<时间>.key`，不会上传到 GitHub。通过自己的 U 盘等单独带走；丢失钥匙就无法解密凭据包。不要把钥匙发给 AI 或提交到仓库。

```powershell
.\.venv\Scripts\python.exe -m pip install cryptography
.\.venv\Scripts\python.exe scripts/decrypt_workbench_credentials.py --bundle workbench-credentials.fernet --key-file E:/github-migration-时间.key --output D:/workbench-private-restore
```

将解密目录内的两处 `.env` 放回对应项目位置。解密工具不会自动覆盖任何文件或安装授权。紫鸟文件备份在解密目录的 `ziniao-cli/`；如需沿用旧授权，先安装官方 CLI，在新电脑本地安全恢复配置并执行 doctor。遇到设备绑定或解密不兼容问题，使用官方新授权流程，不绕过检查。新电脑的店铺浏览器由紫鸟客户端正常登录，不迁移个人浏览器 profile。

数据包也保留了项目内已有视频、图片和历史备份；外部第三方项目克隆、node_modules、缓存、运行日志、浏览器 profile 不在迁移范围。外部集成需要按原项目文档重新安装，不能把它们称为已经一模一样恢复。主工作台的原 Skill 和本地资源包含在源码内。

安装并授权 CLI：

```powershell
npm install -g @ziniao-open/cli
ziniao-cli config init --new
ziniao-cli doctor
```

新授权必须由用户在浏览器完成。不要通过复制 Cookie 或绕过设备检查来恢复登录。

## 启动

从仓库根目录运行，保持终端开启：

```powershell
.\.venv\Scripts\python.exe frontend/unified_skill_dashboard/server.py --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。

也可使用工作台的 `启动综合看板.ps1`，但该脚本使用 PATH 中的 Python，且检测到 8765 已有正常服务时只会打开页面，不会替你重启旧进程。不要使用根目录旧 Streamlit 启动入口代替它。

## 恢复后检查

- 核对数据清单及 SHA256；数据库、原表和图片必须属于同次完整备份。
- 确认历史聊天、行动、内容实例可打开，原账单可下载。
- 六店身份、下载目录、时区和账单范围在新设备复检。
- 保持定时计划关闭，确认新旧电脑不会同时采集或调用付费 AI 后再人工启用。
- 不把新电脑的空数据库覆盖到原始备份，不自动激活待审核任务。
- 如果更换数据盘或根目录，核查 `WORKBENCH_DATA_DIR` 和导出路径配置；旧设备的绝对下载路径不可直接沿用。

完整恢复验收仍须在新电脑实际执行；源码上传成功不等于跨电脑运行已验证。
