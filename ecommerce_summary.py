from pathlib import Path

import numpy as np
import pandas as pd


pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 80)


def n(series):
    return pd.to_numeric(series, errors="coerce")


def key(series):
    return series.astype(str).str.strip()


def print_table(title, df, cols=None, rows=10):
    print("\n## " + title)
    if cols:
        df = df[cols]
    print(df.head(rows).to_string(index=False))


files = {p.name: p for p in Path(".").glob("*.xlsx")}
sales_file = next(p for p in files.values() if "销售数据" in p.name)
income_file = next(p for p in files.values() if "income_" in p.name)
overdue_file = next(p for p in files.values() if "超期" in p.name)
price_file = next(p for p in files.values() if "控价" in p.name)

sales = pd.read_excel(sales_file, sheet_name="Sheet1")
sales["订单编号_key"] = key(sales["订单编号"])
sales["SKU_key"] = key(sales["SKU"])
for col in ["商品数量", "商品金额", "订单总金额", "订单实付金额（人民币）", "汇率\n（原始货币）"]:
    sales[col + "_num"] = n(sales[col])
sales["付款时间_dt"] = pd.to_datetime(sales["付款时间"], errors="coerce")
valid = sales[sales["状态"].astype(str).str.strip() != "已作废"].copy()
cancelled = sales[sales["状态"].astype(str).str.strip() == "已作废"].copy()

pkg = pd.read_excel(price_file, sheet_name="6月产品包")
pkg["SKU_key"] = key(pkg["SKU"])
for col in ["销售成本人民币", "销售成本国家币", "仓存"]:
    pkg[col + "_num"] = n(pkg[col])
pkg_unique = pkg.drop_duplicates("SKU_key", keep="last").copy()

valid = valid.merge(
    pkg_unique[
        [
            "SKU_key",
            "销售成本人民币_num",
            "销售成本国家币_num",
            "SKU状态",
            "主SKU",
            "赠品",
            "仓存_num",
        ]
    ],
    on="SKU_key",
    how="left",
)
valid["商品成本人民币"] = valid["商品数量_num"] * valid["销售成本人民币_num"]
valid["估算毛利人民币"] = valid["商品金额_num"] - valid["商品成本人民币"]

print("# 电商数据初步分析汇总")
print("文件：", sales_file.name, "|", income_file.name, "|", overdue_file.name, "|", price_file.name)
print("销售周期：", valid["付款时间_dt"].min(), "至", valid["付款时间_dt"].max())
print("销售表行数：", len(sales), "；非作废行数：", len(valid), "；作废行数：", len(cancelled))
print("非作废订单数：", valid["订单编号_key"].nunique(), "；非作废SKU数：", valid["SKU_key"].nunique())
print("非作废销量：", round(valid["商品数量_num"].sum(), 2), "；非作废商品金额RMB：", round(valid["商品金额_num"].sum(), 2))
print("作废订单数：", cancelled["订单编号_key"].nunique(), "；作废商品金额RMB：", round(cancelled["商品金额_num"].sum(), 2))
print("成本匹配行覆盖率：", round(valid["销售成本人民币_num"].notna().mean() * 100, 2), "%")

store = (
    valid.groupby("店铺名", dropna=False)
    .agg(
        订单数=("订单编号_key", "nunique"),
        SKU数=("SKU_key", "nunique"),
        销量=("商品数量_num", "sum"),
        商品金额RMB=("商品金额_num", "sum"),
        估算毛利RMB=("估算毛利人民币", "sum"),
    )
    .reset_index()
)
store["估算毛利率"] = store["估算毛利RMB"] / store["商品金额RMB"].replace(0, np.nan)
print_table("店铺表现", store.sort_values("商品金额RMB", ascending=False), rows=8)

cod = (
    valid.groupby("是否COD", dropna=False)
    .agg(订单数=("订单编号_key", "nunique"), 销量=("商品数量_num", "sum"), 商品金额RMB=("商品金额_num", "sum"))
    .reset_index()
)
print_table("COD / 非COD", cod.sort_values("商品金额RMB", ascending=False), rows=10)

cat = (
    valid.groupby(["一级类目", "二级类目", "三级类目"], dropna=False)
    .agg(SKU数=("SKU_key", "nunique"), 订单数=("订单编号_key", "nunique"), 销量=("商品数量_num", "sum"), 商品金额RMB=("商品金额_num", "sum"), 估算毛利RMB=("估算毛利人民币", "sum"))
    .reset_index()
)
cat["估算毛利率"] = cat["估算毛利RMB"] / cat["商品金额RMB"].replace(0, np.nan)
print_table("销售额Top品类", cat.sort_values("商品金额RMB", ascending=False), rows=12)

sku = (
    valid.groupby(["SKU_key", "商品中文名称"], dropna=False)
    .agg(订单数=("订单编号_key", "nunique"), 销量=("商品数量_num", "sum"), 商品金额RMB=("商品金额_num", "sum"), 成本RMB=("商品成本人民币", "sum"), 估算毛利RMB=("估算毛利人民币", "sum"))
    .reset_index()
)
sku["估算毛利率"] = sku["估算毛利RMB"] / sku["商品金额RMB"].replace(0, np.nan)
print_table("销售额Top SKU", sku.sort_values("商品金额RMB", ascending=False), rows=12)
print_table("估算毛利Top SKU", sku.sort_values("估算毛利RMB", ascending=False), rows=12)
print_table("低毛利/亏损SKU 商品金额>=1000", sku[sku["商品金额RMB"] >= 1000].sort_values("估算毛利RMB"), rows=15)

zero = valid[(valid["商品数量_num"] > 0) & (valid["商品金额_num"].fillna(0) <= 0)].copy()
zero["零售价成本RMB"] = zero["商品数量_num"] * zero["销售成本人民币_num"]
zero_sku = (
    zero.groupby(["SKU_key", "商品中文名称"], dropna=False)
    .agg(订单数=("订单编号_key", "nunique"), 数量=("商品数量_num", "sum"), 金额RMB=("商品金额_num", "sum"), 成本占用RMB=("零售价成本RMB", "sum"))
    .reset_index()
)
print_table("零金额/疑似赠品或样品成本占用", zero_sku.sort_values("成本占用RMB", ascending=False), rows=15)

income = pd.read_excel(income_file, sheet_name="订单详情")
for col in ["结算总金额", "总收入", "总费用", "交易手续费", "TikTok Shop 佣金费", "实际运费", "实际退货运费", "客户付款", "客户退款", "联盟佣金"]:
    income[col + "_num"] = n(income[col])
print("\n## 结算表汇总 MYR")
print("结算行数：", len(income), "；订单/调整ID数：", key(income["订单ID/调整单ID"]).nunique())
print("结算总金额：", round(income["结算总金额_num"].sum(), 2))
print("客户付款：", round(income["客户付款_num"].sum(), 2), "；客户退款：", round(income["客户退款_num"].sum(), 2))
print("总费用：", round(income["总费用_num"].sum(), 2), "；佣金：", round(income["TikTok Shop 佣金费_num"].sum(), 2), "；交易手续费：", round(income["交易手续费_num"].sum(), 2), "；实际运费：", round(income["实际运费_num"].sum(), 2), "；联盟佣金：", round(income["联盟佣金_num"].sum(), 2))
print("退款/付款比例：", round(abs(income["客户退款_num"].sum()) / income["客户付款_num"].sum() * 100, 2), "%")
print("费用/付款比例：", round(abs(income["总费用_num"].sum()) / income["客户付款_num"].sum() * 100, 2), "%")

income["订单ID_key"] = key(income["订单ID/调整单ID"])
income_by_order = income.groupby("订单ID_key", dropna=False).agg(结算总金额MYR=("结算总金额_num", "sum")).reset_index()
matched_orders = valid[["订单编号_key"]].drop_duplicates().merge(income_by_order, left_on="订单编号_key", right_on="订单ID_key", how="left")
print("结算表匹配到非作废销售订单：", matched_orders["结算总金额MYR"].notna().sum(), "/", len(matched_orders), "，匹配率", round(matched_orders["结算总金额MYR"].notna().mean() * 100, 2), "%")

inv = pd.read_excel(price_file, sheet_name="6月库存")
for col in ["预测日销量(个)", "仓位库存", "当前可售天数", "可用库存量"]:
    inv[col + "_num"] = n(inv[col])
print_table(
    "高库存/长可售天数",
    inv.sort_values("当前可售天数_num", ascending=False),
    ["库存SKU编号", "中文名称", "商品状态", "活跃度", *([c for c in ("销量(7)", "销量(28)", "销量(42)") if c in inv.columns] or ["销量(7/28/42)"]), "预测日销量(个)", "仓位库存", "当前可售天数", "可用库存量"],
    rows=12,
)
normal_short = inv[(inv["商品状态"].astype(str).str.contains("正常", na=False)) & (inv["预测日销量(个)_num"] > 0) & (inv["当前可售天数_num"] <= 7)]
print_table(
    "正常销售但库存紧张 <=7天",
    normal_short.sort_values("当前可售天数_num"),
    ["库存SKU编号", "中文名称", "商品状态", "活跃度", *([c for c in ("销量(7)", "销量(28)", "销量(42)") if c in inv.columns] or ["销量(7/28/42)"]), "预测日销量(个)", "仓位库存", "当前可售天数", "可用库存量"],
    rows=20,
)

overdue = pd.read_excel(overdue_file, sheet_name="6月分配 ", header=2)
for col in ["销售成本", "当前库存", "日销量", "周转天数", "月预估超期库存", "月预估超期金额", "日销差距（50天）", "预计出清数量（50天）", "日销差距（90天）", "预计出清数量（90天）"]:
    overdue[col + "_num"] = n(overdue[col])
print("\n## 超期库存")
print("6月超期SKU/主SKU数：", len(overdue), "；月预估超期库存：", round(overdue["月预估超期库存_num"].sum(), 2), "；月预估超期金额：", round(overdue["月预估超期金额_num"].sum(), 2))
print_table(
    "超期金额Top产品",
    overdue.sort_values("月预估超期金额_num", ascending=False),
    ["主SKU", "商品名称", "品类", "三级分类", "销售成本", "当前库存", "日销量", "周转天数", "月预估超期库存", "月预估超期金额", "日销差距（50天）", "预计出清数量（50天）"],
    rows=15,
)
overdue_cat = (
    overdue.groupby(["品类", "三级分类"], dropna=False)
    .agg(款数=("主SKU", "count"), 超期库存=("月预估超期库存_num", "sum"), 超期金额=("月预估超期金额_num", "sum"))
    .reset_index()
)
print_table("超期金额Top品类", overdue_cat.sort_values("超期金额", ascending=False), rows=12)

adjust = pd.read_excel(price_file, sheet_name="6月调整栏")
print_table("6月控价调整原因", adjust["特殊原因"].fillna("(空)").astype(str).str.strip().value_counts().reset_index().rename(columns={"index": "特殊原因", "特殊原因": "数量"}), rows=10)
print_table("6月控价调整明细样例", adjust, rows=10)
