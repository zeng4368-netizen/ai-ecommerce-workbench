from pathlib import Path

import numpy as np
import pandas as pd


pd.set_option("display.max_columns", 80)
pd.set_option("display.width", 220)


def clean_num(series):
    return pd.to_numeric(series, errors="coerce")


def show(title, obj, n=20):
    print("\n" + "=" * 80)
    print(title)
    if hasattr(obj, "head"):
        print(obj.head(n).to_string())
    else:
        print(obj)


files = {p.name: p for p in Path(".").glob("*.xlsx")}
sales_file = next(p for p in files.values() if "销售数据" in p.name)
income_file = next(p for p in files.values() if "income_" in p.name)
overdue_file = next(p for p in files.values() if "超期" in p.name)
price_file = next(p for p in files.values() if "控价" in p.name)

print("FILES")
for label, path in [
    ("sales", sales_file),
    ("income", income_file),
    ("overdue", overdue_file),
    ("price", price_file),
]:
    print(label, path.name)


# Sales table
sales = pd.read_excel(sales_file, sheet_name="Sheet1")
print("\nSALES_SHAPE", sales.shape)
print("SALES_COLUMNS", list(sales.columns))
sales["付款时间_dt"] = pd.to_datetime(sales.get("付款时间"), errors="coerce")
sales["订单编号_key"] = sales["订单编号"].astype(str).str.strip()

for col in [
    "商品数量",
    "商品金额",
    "订单总金额",
    "订单核算金额（原始货币）",
    "订单核算金额（人民币）",
    "订单实付金额（原始货币）",
    "订单实付金额（人民币）",
    "商品销售单价",
    "原始商品销售单价",
]:
    if col in sales.columns:
        sales[col + "_num"] = clean_num(sales[col])

print("SALES_DATE_RANGE", sales["付款时间_dt"].min(), sales["付款时间_dt"].max())
print("UNIQUE_ORDERS", sales["订单编号"].astype(str).str.strip().nunique())
print("UNIQUE_SKUS", sales["SKU"].astype(str).str.strip().nunique())
print("TOTAL_QTY", sales["商品数量_num"].sum())
print("TOTAL_PRODUCT_AMOUNT", sales["商品金额_num"].sum())
print("TOTAL_ORDER_AMOUNT_RMB", sales["订单总金额_num"].sum())

valid_sales = sales[sales["状态"].astype(str).str.strip() != "已作废"].copy()
cancelled_sales = sales[sales["状态"].astype(str).str.strip() == "已作废"].copy()
print("VALID_ROWS", len(valid_sales))
print("VALID_UNIQUE_ORDERS", valid_sales["订单编号_key"].nunique())
print("VALID_UNIQUE_SKUS", valid_sales["SKU"].astype(str).str.strip().nunique())
print("VALID_TOTAL_QTY", valid_sales["商品数量_num"].sum())
print("VALID_TOTAL_PRODUCT_AMOUNT", valid_sales["商品金额_num"].sum())
print("CANCELLED_ROWS", len(cancelled_sales))
print("CANCELLED_UNIQUE_ORDERS", cancelled_sales["订单编号_key"].nunique())
print("CANCELLED_TOTAL_PRODUCT_AMOUNT", cancelled_sales["商品金额_num"].sum())

for col in ["状态", "平台", "店铺名", "国家", "是否补单", "是否测评", "是否COD", "一级类目", "二级类目"]:
    if col in sales.columns:
        counts = sales[col].fillna("(空)").astype(str).str.strip().value_counts(dropna=False).head(15)
        show("VALUE_COUNTS " + col, counts)

sku_sales = (
    valid_sales.groupby(["SKU", "商品中文名称"], dropna=False)
    .agg(
        row_count=("SKU", "size"),
        order_count=("订单编号", lambda x: x.astype(str).str.strip().nunique()),
        qty=("商品数量_num", "sum"),
        product_amount=("商品金额_num", "sum"),
        order_amount_rmb=("订单总金额_num", "sum"),
    )
    .reset_index()
)
show("TOP_SKU_BY_QTY", sku_sales.sort_values("qty", ascending=False), 20)
show("TOP_SKU_BY_AMOUNT", sku_sales.sort_values("product_amount", ascending=False), 20)

cat_sales = (
    valid_sales.groupby(["一级类目", "二级类目", "三级类目"], dropna=False)
    .agg(
        sku_count=("SKU", lambda x: x.astype(str).str.strip().nunique()),
        order_count=("订单编号", lambda x: x.astype(str).str.strip().nunique()),
        qty=("商品数量_num", "sum"),
        product_amount=("商品金额_num", "sum"),
    )
    .reset_index()
    .sort_values("product_amount", ascending=False)
)
show("TOP_CATEGORY_BY_AMOUNT", cat_sales, 20)


# TikTok income/settlement table
income = pd.read_excel(income_file, sheet_name="订单详情")
print("\nINCOME_SHAPE", income.shape)
print("INCOME_COLUMNS", list(income.columns))
for col in income.columns:
    if col not in ["订单ID/调整单ID", "交易类型", "订单创建时间", "订单结算时间", "货币", "相关订单 ID", "已售商品详情", "客户付款银行"]:
        income[col + "_num"] = clean_num(income[col])

print(
    "INCOME_DATE_RANGE",
    pd.to_datetime(income["订单创建时间"], errors="coerce").min(),
    pd.to_datetime(income["订单创建时间"], errors="coerce").max(),
)
print("INCOME_UNIQUE_ORDER_IDS", income["订单ID/调整单ID"].astype(str).str.strip().nunique())
print("INCOME_TRANSACTION_TYPES")
print(income["交易类型"].value_counts(dropna=False).to_string())

income_cols = [
    "结算总金额",
    "总收入",
    "享受商家折扣后小计",
    "享受折扣前小计",
    "商家折扣",
    "享受商家折扣后的退款小计",
    "享受商家折扣前的退款小计",
    "总费用",
    "交易手续费",
    "TikTok Shop 佣金费",
    "商家运费",
    "实际运费",
    "买家支付运费",
    "实际退货运费",
    "客户运费退款",
    "运费补贴",
    "联盟佣金",
    "GMV Max 广告费",
    "调整金额",
    "客户付款",
    "客户退款",
    "平台折扣",
    "平台折扣退款",
    "商家运费折扣",
]
summary = []
for col in income_cols:
    if col in income.columns:
        nums = clean_num(income[col])
        summary.append((col, nums.sum(), nums.mean(), nums.min(), nums.max()))
show("INCOME_NUMERIC_SUMMARY", pd.DataFrame(summary, columns=["field", "sum", "mean", "min", "max"]), 50)


# Cost/product package table
pkg = pd.read_excel(price_file, sheet_name="6月产品包")
print("\nPKG_SHAPE", pkg.shape)
print("PKG_COLUMNS", list(pkg.columns))
for col in ["仓存", "销售成本人民币", "国家汇率", "销售成本国家币", "1档价(20%)", "2档价(25%)", "3档价(35%)", "4档价(45%)", "连带率"]:
    if col in pkg.columns:
        pkg[col + "_num"] = clean_num(pkg[col])

print("PKG_UNIQUE_SKU", pkg["SKU"].astype(str).str.strip().nunique())
show("PKG_STATUS_COUNTS", pkg["SKU状态"].fillna("(空)").astype(str).str.strip().value_counts().head(20))
show(
    "PKG_COST_SAMPLE",
    pkg[
        [
            "SKU",
            "商品名称",
            "主SKU",
            "一级品类",
            "二级品类",
            "三级类目",
            "SKU状态",
            "仓存",
            "销售成本人民币",
            "销售成本国家币",
            "1档价(20%)",
            "2档价(25%)",
            "3档价(35%)",
            "4档价(45%)",
        ]
    ].head(20),
    20,
)

sales["SKU_key"] = sales["SKU"].astype(str).str.strip()
pkg["SKU_key"] = pkg["SKU"].astype(str).str.strip()
pkg_dupes = pkg[pkg["SKU_key"].duplicated(keep=False)].sort_values("SKU_key")
show("PKG_DUPLICATE_SKUS", pkg_dupes[["SKU", "商品名称", "主SKU", "SKU状态", "销售成本人民币", "销售成本国家币"]], 30)
pkg_unique = pkg.drop_duplicates("SKU_key", keep="last").copy()
valid_sales["SKU_key"] = valid_sales["SKU"].astype(str).str.strip()
merged = valid_sales.merge(
    pkg_unique[
        [
            "SKU_key",
            "销售成本人民币_num",
            "销售成本国家币_num",
            "SKU状态",
            "仓存_num",
            "主SKU",
            "一级品类",
            "二级品类",
            "三级类目",
            "1档价(20%)_num",
            "2档价(25%)_num",
            "3档价(35%)_num",
            "4档价(45%)_num",
        ]
    ],
    on="SKU_key",
    how="left",
    suffixes=("", "_pkg"),
)
merged["商品成本人民币"] = merged["商品数量_num"] * merged["销售成本人民币_num"]
merged["估算毛利人民币"] = merged["商品金额_num"] - merged["商品成本人民币"]
merged["估算毛利率"] = merged["估算毛利人民币"] / merged["商品金额_num"].replace(0, np.nan)
print("COST_MATCH_COVERAGE_ROW_PCT", round(merged["销售成本人民币_num"].notna().mean() * 100, 2))
print("COST_MATCHED_SKUS", merged.loc[merged["销售成本人民币_num"].notna(), "SKU_key"].nunique(), "of", merged["SKU_key"].nunique())

profit_sku = (
    merged.groupby(["SKU_key", "商品中文名称"], dropna=False)
    .agg(
        order_count=("订单编号", lambda x: x.astype(str).str.strip().nunique()),
        qty=("商品数量_num", "sum"),
        product_amount=("商品金额_num", "sum"),
        cost_rmb=("商品成本人民币", "sum"),
        est_gross_profit_rmb=("估算毛利人民币", "sum"),
        matched_rows=("销售成本人民币_num", lambda x: x.notna().sum()),
        row_count=("SKU_key", "size"),
    )
    .reset_index()
)
profit_sku["est_gross_margin"] = profit_sku["est_gross_profit_rmb"] / profit_sku["product_amount"].replace(0, np.nan)
profit_sku["cost_coverage"] = profit_sku["matched_rows"] / profit_sku["row_count"]
show("TOP_EST_PROFIT_SKU", profit_sku.sort_values("est_gross_profit_rmb", ascending=False), 20)
show(
    "LOW_EST_PROFIT_SKU_MIN_AMOUNT_1000",
    profit_sku[profit_sku["product_amount"] >= 1000].sort_values("est_gross_profit_rmb").head(20),
    20,
)

zero_amount = merged[(merged["商品数量_num"] > 0) & (merged["商品金额_num"].fillna(0) <= 0)].copy()
zero_amount["zero_cost_rmb"] = zero_amount["商品数量_num"] * zero_amount["销售成本人民币_num"]
zero_sku = (
    zero_amount.groupby(["SKU_key", "商品中文名称"], dropna=False)
    .agg(
        order_count=("订单编号", lambda x: x.astype(str).str.strip().nunique()),
        qty=("商品数量_num", "sum"),
        amount=("商品金额_num", "sum"),
        cost_leak_rmb=("zero_cost_rmb", "sum"),
        row_count=("SKU_key", "size"),
    )
    .reset_index()
    .sort_values("cost_leak_rmb", ascending=False)
)
show("ZERO_AMOUNT_SKU_COST_LEAKAGE", zero_sku, 30)


# Match settlement data to valid sales orders and allocate settlement profit by line share.
income["订单ID_key"] = income["订单ID/调整单ID"].astype(str).str.strip()
income["相关订单ID_key"] = income["相关订单 ID"].astype(str).str.strip()
income["join_order_key"] = income["订单ID_key"]
income.loc[income["join_order_key"].isin(["", "nan", "None"]), "join_order_key"] = income["相关订单ID_key"]
income_by_order = (
    income.groupby("join_order_key", dropna=False)
    .agg(
        settlement_myr=("结算总金额_num", "sum"),
        total_income_myr=("总收入_num", "sum"),
        total_fees_myr=("总费用_num", "sum"),
        customer_payment_myr=("客户付款_num", "sum"),
        customer_refund_myr=("客户退款_num", "sum"),
        tiktok_commission_myr=("TikTok Shop 佣金费_num", "sum"),
        transaction_fee_myr=("交易手续费_num", "sum"),
        actual_shipping_myr=("实际运费_num", "sum"),
        affiliate_commission_myr=("联盟佣金_num", "sum"),
        row_count=("join_order_key", "size"),
    )
    .reset_index()
)
order_amount = (
    valid_sales.groupby("订单编号_key", dropna=False)
    .agg(
        order_product_amount_rmb=("商品金额_num", "sum"),
        order_qty=("商品数量_num", "sum"),
        fx_rate=("汇率\n（原始货币）", lambda x: clean_num(x).dropna().iloc[0] if len(clean_num(x).dropna()) else np.nan),
    )
    .reset_index()
)
settled = merged.merge(order_amount, on="订单编号_key", how="left").merge(
    income_by_order, left_on="订单编号_key", right_on="join_order_key", how="left"
)
settled_order_match = order_amount.merge(income_by_order, left_on="订单编号_key", right_on="join_order_key", how="left")
print("SETTLEMENT_MATCHED_VALID_ORDERS", settled_order_match["settlement_myr"].notna().sum(), "of", len(settled_order_match))
print("SETTLEMENT_MATCHED_VALID_ORDER_PCT", round(settled_order_match["settlement_myr"].notna().mean() * 100, 2))

amount_share = settled["商品金额_num"] / settled["order_product_amount_rmb"].replace(0, np.nan)
qty_share = settled["商品数量_num"] / settled["order_qty"].replace(0, np.nan)
settled["line_share"] = amount_share.fillna(qty_share).fillna(0)
settled["settlement_cny_alloc"] = settled["settlement_myr"] * settled["fx_rate"] * settled["line_share"]
settled["fees_cny_alloc"] = settled["total_fees_myr"] * settled["fx_rate"] * settled["line_share"]
settled["refund_cny_alloc"] = settled["customer_refund_myr"] * settled["fx_rate"] * settled["line_share"]
settled["settlement_profit_cny"] = settled["settlement_cny_alloc"] - settled["商品成本人民币"]

settled_sku = (
    settled[settled["settlement_myr"].notna()]
    .groupby(["SKU_key", "商品中文名称"], dropna=False)
    .agg(
        order_count=("订单编号", lambda x: x.astype(str).str.strip().nunique()),
        qty=("商品数量_num", "sum"),
        product_amount=("商品金额_num", "sum"),
        cost_rmb=("商品成本人民币", "sum"),
        settlement_cny=("settlement_cny_alloc", "sum"),
        fees_cny=("fees_cny_alloc", "sum"),
        refund_cny=("refund_cny_alloc", "sum"),
        settlement_profit_cny=("settlement_profit_cny", "sum"),
    )
    .reset_index()
)
settled_sku["settlement_profit_margin"] = settled_sku["settlement_profit_cny"] / settled_sku["settlement_cny"].replace(0, np.nan)
show("TOP_SETTLEMENT_PROFIT_SKU_MATCHED_ORDERS", settled_sku.sort_values("settlement_profit_cny", ascending=False), 20)
show("LOW_SETTLEMENT_PROFIT_SKU_MATCHED_ORDERS", settled_sku[settled_sku["settlement_cny"].abs() >= 500].sort_values("settlement_profit_cny"), 20)


# Inventory table
inv = pd.read_excel(price_file, sheet_name="6月库存")
print("\nINV_SHAPE", inv.shape)
print("INV_COLUMNS", list(inv.columns))
for col in ["预测日销量(个)", "仓位库存", "当前可售天数", "在途量", "海外仓预调入量", "分仓调拨预调入量", "警戒量", "警戒天数", "未发货量", "可用库存量"]:
    if col in inv.columns:
        inv[col + "_num"] = clean_num(inv[col])

inv_view_cols = ["库存SKU编号", "中文名称", "商品状态", "活跃度", *([c for c in ("销量(7)", "销量(28)", "销量(42)") if c in inv.columns] or ["销量(7/28/42)"]), "预测日销量(个)", "仓位库存", "当前可售天数", "可用库存量"]
show("INV_TOP_STOCK_DAYS", inv.sort_values("当前可售天数_num", ascending=False)[inv_view_cols], 20)
normal_mask = inv["商品状态"].astype(str).str.contains("正常", na=False)
show("INV_LOW_STOCK_ACTIVE", inv[normal_mask & inv["当前可售天数_num"].notna()].sort_values("当前可售天数_num")[inv_view_cols], 20)


# Overdue stock table
overdue = pd.read_excel(overdue_file, sheet_name="6月分配 ", header=2)
print("\nOVERDUE_SHAPE", overdue.shape)
print("OVERDUE_COLUMNS", list(overdue.columns))
for col in [
    "销售成本",
    "当前库存",
    "日销量",
    "周转天数",
    "月预估超期库存",
    "月预估超期金额",
    "日销差距（50天）",
    "预计出清数量（50天）",
    "出清金额（3月）",
    "日销差距（90天）",
    "预计出清数量（90天）",
    "出清金额(6月）",
]:
    if col in overdue.columns:
        overdue[col + "_num"] = clean_num(overdue[col])

overdue_view_cols = [
    "主SKU",
    "商品名称",
    "国家",
    "品类",
    "三级分类",
    "销售成本",
    "当前库存",
    "日销量",
    "周转天数",
    "月预估超期库存",
    "月预估超期金额",
    "日销差距（50天）",
    "预计出清数量（50天）",
    "日销差距（90天）",
    "预计出清数量（90天）",
]
show("OVERDUE_TOP_AMOUNT", overdue.sort_values("月预估超期金额_num", ascending=False)[overdue_view_cols], 20)
print("OVERDUE_TOTAL_AMOUNT", overdue["月预估超期金额_num"].sum())
print("OVERDUE_TOTAL_STOCK", overdue["月预估超期库存_num"].sum())
show(
    "OVERDUE_BY_CATEGORY",
    overdue.groupby(["品类", "三级分类"], dropna=False)
    .agg(item_count=("主SKU", "count"), overdue_stock=("月预估超期库存_num", "sum"), overdue_amount=("月预估超期金额_num", "sum"))
    .reset_index()
    .sort_values("overdue_amount", ascending=False),
    20,
)


# Price adjustment records
adj = pd.read_excel(price_file, sheet_name="6月调整栏")
print("\nADJ_SHAPE", adj.shape)
print("ADJ_COLUMNS", list(adj.columns))
show("ADJ_REASON_COUNTS", adj["特殊原因"].fillna("(空)").astype(str).str.strip().value_counts().head(20))
show("ADJ_SAMPLE", adj.head(20), 20)
