# GMV MAX 数据清洗 · 字段与口径参考

本文件供 WorkBuddy 在执行 `gmv-max-data-cleaning` 技能时按需加载，说明输入列、
人员名单表头、输出表头，以及关键计算口径与边界情况。

## 1. 广告数据文件（每家店铺一个，文件名 = 店编）

必需核心列（脚本通过别名自动匹配，支持中英文变体）：

| 标准列名 | 用途 | 兼容别名（部分） |
|---|---|---|
| `Cost` | 广告消耗 | Spend / 广告消耗 / 消耗 / Advertising cost |
| `Creative type` | 素材类型（商品卡 / 视频素材） | Creative Type / 素材类型 / Ad type |
| `Time posted` | 发布时间，用于 L7D 筛选 | Time Posted / 发布时间 / 创建时间 / Creation time |
| `Product ad click rate` | 点击率 CTR | CTR / 点击率 / Click-through rate / 广告点击率 |
| `Ad conversion rate` | 转化率 CVR | CVR / 转化率 / Conversion rate / 广告转化率 |

- 每行 = 一条素材 / 商品卡广告。
- 一次导出的时间窗口（如 7.1–7.14）反映在 `Time posted` 上。
- 列名匹配优先级：精确 → 大小写不敏感 → 子串包含。
- 若文件前几行是 TikTok 导出的元数据，脚本会自动下移表头；文件末尾的
  Total/总计/合计 行会被自动移除。

## 2. 人员名单（单表）

表头（严格顺序不强制，按列名匹配）：

```
店名 | 店编 | 国家 | 初级 | 中级 | 储高/见高 | CEO
```

- `店编` 为关联键，须与广告数据文件名（去扩展名）一致。
- 名单中但无数据文件的店铺仍保留在结果中，指标为 0 / `0.00%`。
- 数据文件无法匹配店编时，人员信息留空但仍汇总广告指标，并给出警告。

## 3. 处理步骤与判断条件

1. **剔除 Cost=0**：所有后续指标均在剔除 Cost=0 的行之后计算。
2. **创意类型分布**：按 `Creative type` 统计商品卡 / 视频素材条数（仅日志，不写入结果表）。
3. **L7D 筛选**：`Time posted >= --start-date`（含当日 00:00）。`--start-date` 由用户
   在运行前提供（导出起始日）。未提供时脚本以最大发布日期前推 6 天兜底。
4. **CTR / CVR**：
   - 总 CTR/CVR = 全部（Cost>0）素材 `Product ad click rate` / `Ad conversion rate` 的算术平均。
   - L7D CTR/CVR = 上述窗口内素材的同口径平均。
   - 均值 ×100 后得到百分比数值（百分点，如 3.25，保留两位小数）；单元格数字格式设为 `0.00"%"`，显示为 `3.25%`，且为真实可计算数字。

## 4. 输出表头（固定，不可增减列）

```
店名 | 店编 | 国家 | 初级 | 中级 | 储高/见高 | CEO
| L7D新建素材数 | L7D新建素材消耗额 | 总素材数 | 总消耗
| L7D CTR | L7D CVR | 总CTR | 总CVR
```

各列含义：

| 列 | 口径 |
|---|---|
| L7D新建素材数 | Time posted ≥ 起始日期 的素材条数（Cost>0） |
| L7D新建素材消耗额 | 上述素材的 Cost 求和 |
| 总素材数 | 剔除 Cost=0 后的全部素材条数 |
| 总消耗 | 剔除 Cost=0 后的 Cost 求和 |
| L7D CTR / L7D CVR | 窗口内素材平均 CTR / CVR，百分比字符串 `xx.xx%` |
| 总CTR / 总CVR | 全部素材平均 CTR / CVR，百分比数值（显示为 `xx.xx%`，可计算） |

## 5. 输入数值解析规则

- **Cost**：清除货币符号、千位分隔符后转数值；0 或空 → 视为 Cost=0 被剔除。
- **比率（CTR/CVR）**：
  - 带 `%` 的字符串（如 `5.23%`）→ 按百分比解析（÷100）。
  - 数值 `>1`（如 12.34）→ 视为百分比数值（÷100）。
  - 数值 `≤1`（如 0.1234）→ 视为小数，原样作为 fraction。
  - 空值不计入均值。
- **日期**：支持 `YYYY-MM-DD`、`YYYY/MM/DD`、`DD/MM/YYYY`、`YYYY年MM月DD日` 等常见格式。

## 6. 运行命令

```bash
python scripts/gmv_max_cleaner.py \
  --ad-dir <广告数据目录> \
  --mapping <人员名单.xlsx> \
  --start-date 2026-07-01 \
  --output <输出.xlsx>
```

依赖：`pandas`、`openpyxl`（在隔离 venv 中安装）。
