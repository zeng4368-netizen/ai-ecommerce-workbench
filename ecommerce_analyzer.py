from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd


FileLike = str | Path | BinaryIO


@dataclass
class AnalysisResult:
    metrics: dict[str, object]
    tables: dict[str, pd.DataFrame]
    notes: list[str]
    filter_options: dict[str, object] = field(default_factory=dict)
    active_filters: dict[str, str] = field(default_factory=dict)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _key(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def _first_numeric(series: pd.Series) -> float:
    values = _num(series).dropna()
    return float(values.iloc[0]) if len(values) else np.nan


def _read_excel(file: FileLike, sheet_name: str, **kwargs) -> pd.DataFrame:
    if hasattr(file, "seek"):
        file.seek(0)
    return pd.read_excel(file, sheet_name=sheet_name, **kwargs)


def _with_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col + "_num"] = _num(out[col])
    return out


def _numeric_or_zero(df: pd.DataFrame, column: str) -> pd.Series:
    numeric_column = column + "_num"
    if numeric_column in df.columns:
        return df[numeric_column].fillna(0)
    if column in df.columns:
        return _num(df[column]).fillna(0)
    return pd.Series(0.0, index=df.index)


def _safe_margin(profit: pd.Series, revenue: pd.Series) -> pd.Series:
    return profit / revenue.replace(0, np.nan)


def _unique_values(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns:
        return []
    values = _key(df[column]).replace({"": np.nan, "nan": np.nan}).dropna().unique()
    return sorted(str(v) for v in values)


def _normalize_filters(filters: dict[str, str] | None) -> dict[str, str]:
    filters = filters or {}
    allowed = ["shop", "sku", "keyword", "category1", "category2", "category3"]
    return {key: str(filters.get(key, "")).strip() for key in allowed if str(filters.get(key, "")).strip()}


def _text_contains(series: pd.Series, value: str) -> pd.Series:
    return series.astype(str).str.lower().str.contains(value.lower(), na=False)


def _apply_sales_filters(valid_sales: pd.DataFrame, filters: dict[str, str]) -> pd.DataFrame:
    filtered = valid_sales.copy()
    if filters.get("shop"):
        filtered = filtered[_key(filtered["店铺名"]) == filters["shop"]]
    if filters.get("category1"):
        filtered = filtered[_key(filtered["一级类目"]) == filters["category1"]]
    if filters.get("category2"):
        filtered = filtered[_key(filtered["二级类目"]) == filters["category2"]]
    if filters.get("category3"):
        filtered = filtered[_key(filtered["三级类目"]) == filters["category3"]]
    if filters.get("sku"):
        value = filters["sku"]
        filtered = filtered[
            _text_contains(filtered["SKU_key"], value)
            | _text_contains(filtered["商品中文名称"], value)
            | _text_contains(filtered.get("主SKU", pd.Series("", index=filtered.index)), value)
        ]
    if filters.get("keyword"):
        value = filters["keyword"]
        filtered = filtered[
            _text_contains(filtered["SKU_key"], value)
            | _text_contains(filtered["商品中文名称"], value)
            | _text_contains(filtered.get("主SKU", pd.Series("", index=filtered.index)), value)
        ]
    return filtered


def _filter_inventory(inventory: pd.DataFrame, filtered_sales: pd.DataFrame, filters: dict[str, str]) -> pd.DataFrame:
    if not filters:
        return inventory
    out = inventory.copy()
    mask = pd.Series(False, index=out.index)
    selected_skus = set(_key(filtered_sales["SKU_key"]).dropna()) if "SKU_key" in filtered_sales.columns else set()
    if selected_skus:
        mask |= _key(out["库存SKU编号"]).isin(selected_skus)
    else:
        if filters.get("category1") and "一级目录" in out.columns:
            mask |= _key(out["一级目录"]) == filters["category1"]
        if filters.get("category2") and "二级目录" in out.columns:
            mask |= _key(out["二级目录"]) == filters["category2"]
        if filters.get("category3") and "三级目录" in out.columns:
            mask |= _key(out["三级目录"]) == filters["category3"]
    if filters.get("sku") or filters.get("keyword"):
        text_value = filters.get("sku") or filters.get("keyword") or ""
        text_mask = _text_contains(out["库存SKU编号"], text_value) | _text_contains(out["中文名称"], text_value)
        mask |= text_mask
    return out[mask].copy()


def _filter_overdue(overdue: pd.DataFrame, filtered_sales: pd.DataFrame, filters: dict[str, str]) -> pd.DataFrame:
    if not filters:
        return overdue
    out = overdue.copy()
    mask = pd.Series(False, index=out.index)
    selected_main_skus = set(_key(filtered_sales["主SKU"]).dropna()) if "主SKU" in filtered_sales.columns else set()
    if selected_main_skus:
        mask |= _key(out["主SKU"]).isin(selected_main_skus)
    else:
        if filters.get("category1"):
            mask |= _key(out["品类"]) == filters["category1"]
        if filters.get("category3"):
            mask |= _key(out["三级分类"]) == filters["category3"]
    if filters.get("sku") or filters.get("keyword"):
        text_value = filters.get("sku") or filters.get("keyword") or ""
        text_mask = _text_contains(out["主SKU"], text_value) | _text_contains(out["商品名称"], text_value)
        mask |= text_mask
    return out[mask].copy()


def analyze_files(
    sales_file: FileLike,
    income_file: FileLike,
    price_file: FileLike,
    overdue_file: FileLike,
    filters: dict[str, str] | None = None,
) -> AnalysisResult:
    notes: list[str] = []
    active_filters = _normalize_filters(filters)

    sales = _read_excel(sales_file, sheet_name="Sheet1")
    sales = _with_numeric(
        sales,
        [
            "商品数量",
            "商品金额",
            "订单总金额",
            "订单实付金额（人民币）",
            "订单核算金额（人民币）",
            "汇率\n（原始货币）",
        ],
    )
    sales["订单编号_key"] = _key(sales["订单编号"])
    sales["SKU_key"] = _key(sales["SKU"])
    sales["付款时间_dt"] = pd.to_datetime(sales["付款时间"], errors="coerce")

    package = _read_excel(price_file, sheet_name="6月产品包")
    package = _with_numeric(package, ["销售成本人民币", "销售成本国家币", "仓存"])
    package["SKU_key"] = _key(package["SKU"])
    duplicate_package_skus = package[package["SKU_key"].duplicated(keep=False)].copy()
    package_unique = package.drop_duplicates("SKU_key", keep="last").copy()

    valid_sales_all = sales[sales["状态"].astype(str).str.strip() != "已作废"].copy()
    cancelled_sales = sales[sales["状态"].astype(str).str.strip() == "已作废"].copy()
    valid_sales_all = valid_sales_all.merge(
        package_unique[
            [
                "SKU_key",
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

    sku_options = (
        valid_sales_all[["SKU_key", "商品中文名称"]]
        .drop_duplicates()
        .sort_values("SKU_key")
        .assign(label=lambda df: df["SKU_key"] + " | " + df["商品中文名称"].astype(str))
    )
    filter_options = {
        "shops": _unique_values(valid_sales_all, "店铺名"),
        "categories1": _unique_values(valid_sales_all, "一级类目"),
        "categories2": _unique_values(valid_sales_all, "二级类目"),
        "categories3": _unique_values(valid_sales_all, "三级类目"),
        "skus": [{"value": row.SKU_key, "label": row.label} for row in sku_options.itertuples(index=False)],
    }

    valid_sales = _apply_sales_filters(valid_sales_all, active_filters)
    if active_filters:
        notes.append("当前报告已应用筛选条件，所有销售、毛利和结算匹配指标均按筛选后的订单重算。")
        notes.append("库存、超期、控价等板块会优先按筛选后的 SKU 或主 SKU 集合同步过滤。")

    valid_sales["付款日期"] = valid_sales["付款时间_dt"].dt.normalize()
    valid_sales["商品成本MYR"] = valid_sales["商品数量_num"] * valid_sales["销售成本国家币_num"]
    valid_sales["标价利润MYR"] = valid_sales["商品金额_num"] - valid_sales["商品成本MYR"]
    valid_sales["估算毛利MYR"] = valid_sales["标价利润MYR"]
    period_start = valid_sales_all["付款时间_dt"].dt.normalize().min()
    period_end = valid_sales_all["付款时间_dt"].dt.normalize().max()
    period_days = int((period_end - period_start).days + 1) if pd.notna(period_start) and pd.notna(period_end) else 0

    sales_amount = valid_sales["商品金额_num"].sum()
    gross_profit = valid_sales["标价利润MYR"].sum()
    metrics: dict[str, object] = {
        "销售开始": valid_sales["付款时间_dt"].min(),
        "销售结束": valid_sales["付款时间_dt"].max(),
        "销售表行数": len(sales),
        "筛选后非作废行数": len(valid_sales),
        "非作废行数": len(valid_sales),
        "作废行数": len(cancelled_sales),
        "非作废订单数": valid_sales["订单编号_key"].nunique(),
        "非作废SKU数": valid_sales["SKU_key"].nunique(),
        "非作废销量": valid_sales["商品数量_num"].sum(),
        "非作废商品金额MYR": sales_amount,
        "估算商品成本MYR": valid_sales["商品成本MYR"].sum(),
        "标价利润MYR": gross_profit,
        "标价利润率": gross_profit / sales_amount if sales_amount else np.nan,
        "估算毛利MYR": gross_profit,
        "估算毛利率": gross_profit / sales_amount if sales_amount else np.nan,
        "作废订单数": cancelled_sales["订单编号_key"].nunique(),
        "作废商品金额MYR": cancelled_sales["商品金额_num"].sum(),
        "成本匹配行覆盖率": valid_sales["销售成本国家币_num"].notna().mean() if len(valid_sales) else np.nan,
        "成本匹配SKU数": valid_sales.loc[valid_sales["销售成本国家币_num"].notna(), "SKU_key"].nunique(),
    }

    store_keys = ["店长", "店铺名", "财务编码"]
    store = (
        valid_sales.groupby(store_keys, dropna=False)
        .agg(
            订单数=("订单编号_key", "nunique"),
            SKU数=("SKU_key", "nunique"),
            销量=("商品数量_num", "sum"),
            商品金额MYR=("商品金额_num", "sum"),
            货品成本MYR=("商品成本MYR", "sum"),
            标价利润MYR=("标价利润MYR", "sum"),
        )
        .reset_index()
    )
    store["标价利润率"] = _safe_margin(store["标价利润MYR"], store["商品金额MYR"])

    cod = (
        valid_sales.groupby("是否COD", dropna=False)
        .agg(
            订单数=("订单编号_key", "nunique"),
            销量=("商品数量_num", "sum"),
            商品金额MYR=("商品金额_num", "sum"),
        )
        .reset_index()
    )

    category = (
        valid_sales.groupby(["一级类目", "二级类目", "三级类目"], dropna=False)
        .agg(
            SKU数=("SKU_key", "nunique"),
            订单数=("订单编号_key", "nunique"),
            销量=("商品数量_num", "sum"),
            商品金额MYR=("商品金额_num", "sum"),
            标价利润MYR=("标价利润MYR", "sum"),
        )
        .reset_index()
    )
    category["标价利润率"] = _safe_margin(category["标价利润MYR"], category["商品金额MYR"])

    sku = (
        valid_sales.groupby(["SKU_key", "商品中文名称"], dropna=False)
        .agg(
            订单数=("订单编号_key", "nunique"),
            销量=("商品数量_num", "sum"),
            商品金额MYR=("商品金额_num", "sum"),
            成本MYR=("商品成本MYR", "sum"),
            标价利润MYR=("标价利润MYR", "sum"),
            成本匹配行数=("销售成本国家币_num", lambda x: x.notna().sum()),
            行数=("SKU_key", "size"),
        )
        .reset_index()
    )
    sku["标价利润率"] = _safe_margin(sku["标价利润MYR"], sku["商品金额MYR"])
    sku["SKU商品"] = sku["SKU_key"] + " | " + sku["商品中文名称"].astype(str)
    sku["成本覆盖率"] = sku["成本匹配行数"] / sku["行数"]

    if valid_sales.empty:
        daily_detail = pd.DataFrame(
            columns=["日期", "SKU_key", "商品中文名称", "SKU商品", "订单数", "日销量", "日销售额MYR", "日标价利润MYR"]
        )
        product_daily = pd.DataFrame(
            columns=[
                "SKU_key",
                "商品中文名称",
                "SKU商品",
                "统计周期天数",
                "销售天数",
                "总订单数",
                "总销量",
                "总销售额MYR",
                "总标价利润MYR",
                "全周期日均销量",
                "有销量日均销量",
                "最高单日销量",
                "近7天销量",
                "近7天日均销量",
                "最近销售日期",
            ]
        )
    else:
        daily_detail = (
            valid_sales.groupby(["付款日期", "SKU_key", "商品中文名称"], dropna=False)
            .agg(
                订单数=("订单编号_key", "nunique"),
                日销量=("商品数量_num", "sum"),
                日销售额MYR=("商品金额_num", "sum"),
                日标价利润MYR=("标价利润MYR", "sum"),
            )
            .reset_index()
            .rename(columns={"付款日期": "日期"})
            .sort_values(["日期", "日销量"], ascending=[True, False])
        )
        daily_detail["SKU商品"] = daily_detail["SKU_key"] + " | " + daily_detail["商品中文名称"].astype(str)
        product_daily = (
            daily_detail.groupby(["SKU_key", "商品中文名称"], dropna=False)
            .agg(
                销售天数=("日期", "nunique"),
                总订单数=("订单数", "sum"),
                总销量=("日销量", "sum"),
                总销售额MYR=("日销售额MYR", "sum"),
                总标价利润MYR=("日标价利润MYR", "sum"),
                最高单日销量=("日销量", "max"),
                最近销售日期=("日期", "max"),
            )
            .reset_index()
        )
        product_daily["SKU商品"] = product_daily["SKU_key"] + " | " + product_daily["商品中文名称"].astype(str)
        last7_start = period_end - pd.Timedelta(days=6) if pd.notna(period_end) else None
        if last7_start is not None:
            last7 = (
                daily_detail[daily_detail["日期"] >= last7_start]
                .groupby(["SKU_key", "商品中文名称"], dropna=False)
                .agg(近7天销量=("日销量", "sum"))
                .reset_index()
            )
            product_daily = product_daily.merge(last7, on=["SKU_key", "商品中文名称"], how="left")
        else:
            product_daily["近7天销量"] = np.nan
        product_daily["近7天销量"] = product_daily["近7天销量"].fillna(0)
        product_daily["统计周期天数"] = period_days
        product_daily["全周期日均销量"] = product_daily["总销量"] / period_days if period_days else np.nan
        product_daily["有销量日均销量"] = product_daily["总销量"] / product_daily["销售天数"].replace(0, np.nan)
        product_daily["近7天日均销量"] = product_daily["近7天销量"] / 7
        product_daily = product_daily[
            [
                "SKU_key",
                "商品中文名称",
                "SKU商品",
                "统计周期天数",
                "销售天数",
                "总订单数",
                "总销量",
                "总销售额MYR",
                "总标价利润MYR",
                "全周期日均销量",
                "有销量日均销量",
                "最高单日销量",
                "近7天销量",
                "近7天日均销量",
                "最近销售日期",
            ]
        ].sort_values("全周期日均销量", ascending=False)

    zero_amount = valid_sales[
        (valid_sales["商品数量_num"] > 0) & (valid_sales["商品金额_num"].fillna(0) <= 0)
    ].copy()
    zero_amount["零售价成本MYR"] = zero_amount["商品数量_num"] * zero_amount["销售成本国家币_num"]
    zero_sku = (
        zero_amount.groupby(["SKU_key", "商品中文名称"], dropna=False)
        .agg(
            订单数=("订单编号_key", "nunique"),
            数量=("商品数量_num", "sum"),
            金额MYR=("商品金额_num", "sum"),
            成本占用MYR=("零售价成本MYR", "sum"),
        )
        .reset_index()
    )

    income = _read_excel(income_file, sheet_name="订单详情")
    income = _with_numeric(
        income,
        [
            "结算总金额",
            "总收入",
            "总费用",
            "交易手续费",
            "TikTok Shop 佣金费",
            "实际运费",
            "平台包邮运费",
            "买家支付运费",
            "实际退货运费",
            "客户付款",
            "客户退款",
            "享受商家折扣后的退款小计",
            "商家共同赞助优惠券折扣退款",
            "联盟佣金",
        ],
    )
    income["实际运费成本MYR"] = (-_numeric_or_zero(income, "实际运费")).clip(lower=0)
    income["平台包邮补贴MYR"] = _numeric_or_zero(income, "平台包邮运费").clip(lower=0)
    income["实际退货运费成本MYR"] = (-_numeric_or_zero(income, "实际退货运费")).clip(lower=0)
    income["退包成本MYR"] = (
        (income["实际运费成本MYR"] - income["平台包邮补贴MYR"]).clip(lower=0)
        + income["实际退货运费成本MYR"]
    )
    income["退款金额MYR"] = (
        _numeric_or_zero(income, "享受商家折扣后的退款小计").abs()
        - _numeric_or_zero(income, "客户退款").abs()
    ).clip(lower=0) + _numeric_or_zero(income, "商家共同赞助优惠券折扣退款").clip(lower=0)
    income["订单ID_key"] = _key(income["订单ID/调整单ID"])
    income["相关订单ID_key"] = _key(income["相关订单 ID"]) if "相关订单 ID" in income.columns else ""
    income["join_order_key"] = income["订单ID_key"]
    income.loc[income["join_order_key"].isin(["", "nan", "None"]), "join_order_key"] = income["相关订单ID_key"]

    selected_order_keys = set(_key(valid_sales["订单编号_key"]).dropna())
    income_for_metrics = income[income["join_order_key"].isin(selected_order_keys)].copy() if active_filters else income
    income_metrics = {
        "结算行数": len(income_for_metrics),
        "结算订单ID数": income_for_metrics["订单ID_key"].nunique(),
        "结算总金额MYR": income_for_metrics["结算总金额_num"].sum(),
        "总收入MYR": income_for_metrics["总收入_num"].sum(),
        "客户付款MYR": income_for_metrics["客户付款_num"].sum(),
        "客户退款MYR": income_for_metrics["客户退款_num"].sum(),
        "总费用MYR": income_for_metrics["总费用_num"].sum(),
        "佣金MYR": income_for_metrics["TikTok Shop 佣金费_num"].sum(),
        "交易手续费MYR": income_for_metrics["交易手续费_num"].sum(),
        "实际运费MYR": income_for_metrics["实际运费_num"].sum(),
        "退包成本MYR": income_for_metrics["退包成本MYR"].sum(),
        "退款金额MYR": income_for_metrics["退款金额MYR"].sum(),
        "联盟佣金MYR": income_for_metrics["联盟佣金_num"].sum(),
    }
    metrics.update(income_metrics)
    metrics["退款付款比例"] = (
        abs(metrics["客户退款MYR"]) / metrics["客户付款MYR"] if metrics["客户付款MYR"] else np.nan
    )
    metrics["费用付款比例"] = (
        abs(metrics["总费用MYR"]) / metrics["客户付款MYR"] if metrics["客户付款MYR"] else np.nan
    )

    income_by_order = (
        income.groupby("join_order_key", dropna=False)
        .agg(
            结算总金额MYR=("结算总金额_num", "sum"),
            总收入MYR=("总收入_num", "sum"),
            总费用MYR=("总费用_num", "sum"),
            客户付款MYR=("客户付款_num", "sum"),
            客户退款MYR=("客户退款_num", "sum"),
            佣金MYR=("TikTok Shop 佣金费_num", "sum"),
            交易手续费MYR=("交易手续费_num", "sum"),
            实际运费MYR=("实际运费_num", "sum"),
            退包成本MYR=("退包成本MYR", "sum"),
            退款金额MYR=("退款金额MYR", "sum"),
            联盟佣金MYR=("联盟佣金_num", "sum"),
        )
        .reset_index()
    )

    order_amount = (
        valid_sales.groupby("订单编号_key", dropna=False)
        .agg(
            订单商品金额MYR=("商品金额_num", "sum"),
            订单销量=("商品数量_num", "sum"),
            订单货品成本MYR=("商品成本MYR", "sum"),
        )
        .reset_index()
    )
    order_store = (
        valid_sales.groupby("订单编号_key", dropna=False)
        .agg(
            店长=("店长", "first"),
            店铺名=("店铺名", "first"),
            财务编码=("财务编码", "first"),
        )
        .reset_index()
    )
    matched_orders = (
        order_amount.merge(order_store, on="订单编号_key", how="left")
        .merge(income_by_order, left_on="订单编号_key", right_on="join_order_key", how="left")
    )
    metrics["结算匹配订单数"] = matched_orders["结算总金额MYR"].notna().sum()
    metrics["结算匹配订单率"] = matched_orders["结算总金额MYR"].notna().mean() if len(matched_orders) else np.nan
    metrics["筛选后匹配结算总金额MYR"] = matched_orders["结算总金额MYR"].sum()
    if metrics["结算匹配订单率"] < 0.8:
        notes.append("结算表只匹配到部分销售订单，净利润口径适合做参考，正式月报需上传完整结算周期数据。")

    settled = valid_sales.merge(order_amount, on="订单编号_key", how="left").merge(
        income_by_order, left_on="订单编号_key", right_on="join_order_key", how="left"
    )
    amount_share = settled["商品金额_num"] / settled["订单商品金额MYR"].replace(0, np.nan)
    qty_share = settled["商品数量_num"] / settled["订单销量"].replace(0, np.nan)
    settled["分摊比例"] = amount_share.fillna(qty_share).fillna(0)
    settled["标价收入MYR分摊"] = settled["总收入MYR"] * settled["分摊比例"]
    settled["到账金额MYR分摊"] = settled["结算总金额MYR"] * settled["分摊比例"]
    settled["到账利润MYR"] = settled["到账金额MYR分摊"] - settled["商品成本MYR"]

    matched_settlement = matched_orders[matched_orders["结算总金额MYR"].notna()].copy()
    settlement_sales_scope = valid_sales
    matched_store_names = _key(matched_settlement["店铺名"]).replace({"": np.nan, "nan": np.nan}).dropna().unique()
    if not active_filters and len(matched_store_names) == 1 and valid_sales["店铺名"].nunique() > 1:
        settlement_sales_scope = valid_sales[_key(valid_sales["店铺名"]) == matched_store_names[0]]
        notes.append(f"结算表当前只匹配到店铺 {matched_store_names[0]}，结算利润卡片按该店铺销售成本计算。")

    settlement_goods_cost = settlement_sales_scope["商品成本MYR"].sum()
    settlement_listed_income = metrics["总收入MYR"]
    settlement_received_income = metrics["结算总金额MYR"]
    settlement_return_package_cost = metrics["退包成本MYR"]
    refund_cost_orders = matched_settlement[
        (matched_settlement["客户退款MYR"].fillna(0) < 0) | (matched_settlement["退款金额MYR"].fillna(0) > 0)
    ]
    settlement_refund_cost = refund_cost_orders["订单货品成本MYR"].sum()

    metrics["货品成本MYR"] = settlement_goods_cost
    metrics["退款成本MYR"] = settlement_refund_cost
    metrics["标价利润MYR"] = settlement_listed_income - settlement_goods_cost
    metrics["到账利润MYR"] = settlement_received_income - settlement_goods_cost - settlement_return_package_cost
    metrics["去除邮局MYR"] = settlement_received_income - settlement_goods_cost + settlement_return_package_cost
    metrics["标价利润"] = metrics["标价利润MYR"] / settlement_listed_income if settlement_listed_income else np.nan
    metrics["标价利润率"] = metrics["标价利润"]
    metrics["到账金额MYR"] = settlement_received_income
    metrics["到账利润"] = metrics["到账利润MYR"] / settlement_received_income if settlement_received_income else np.nan
    metrics["到账利润率"] = metrics["到账利润"]
    metrics["去除邮局"] = metrics["去除邮局MYR"] / settlement_received_income if settlement_received_income else np.nan
    metrics["退货退款占比"] = (
        -(settlement_return_package_cost + metrics["退款金额MYR"] + settlement_refund_cost) / settlement_received_income
        if settlement_received_income
        else np.nan
    )

    store_settlement = (
        matched_settlement.groupby(store_keys, dropna=False)
        .agg(
            标价收入MYR=("总收入MYR", "sum"),
            到账收入MYR=("结算总金额MYR", "sum"),
            退包成本MYR=("退包成本MYR", "sum"),
            退款金额MYR=("退款金额MYR", "sum"),
            客户退款MYR=("客户退款MYR", "sum"),
        )
        .reset_index()
    )
    store_refund_cost = (
        refund_cost_orders.groupby(store_keys, dropna=False)
        .agg(退款成本MYR=("订单货品成本MYR", "sum"))
        .reset_index()
    )
    store_settlement = store_settlement.merge(store_refund_cost, on=store_keys, how="left")
    store_settlement["退款成本MYR"] = store_settlement["退款成本MYR"].fillna(0)

    if not active_filters and len(matched_store_names) == 1 and not store_settlement.empty:
        only_store_mask = _key(store_settlement["店铺名"]) == matched_store_names[0]
        store_settlement.loc[only_store_mask, "标价收入MYR"] = settlement_listed_income
        store_settlement.loc[only_store_mask, "到账收入MYR"] = settlement_received_income
        store_settlement.loc[only_store_mask, "退包成本MYR"] = settlement_return_package_cost
        store_settlement.loc[only_store_mask, "退款金额MYR"] = metrics["退款金额MYR"]
        store_settlement.loc[only_store_mask, "退款成本MYR"] = settlement_refund_cost

    store = store.merge(store_settlement, on=store_keys, how="left")
    for column in ["退包成本MYR", "退款金额MYR", "退款成本MYR", "客户退款MYR"]:
        if column in store.columns:
            store[column] = store[column].fillna(0)
    store["标价利润MYR"] = store["标价收入MYR"] - store["货品成本MYR"]
    store["到账利润MYR"] = store["到账收入MYR"] - store["货品成本MYR"] - store["退包成本MYR"]
    store["去除邮局MYR"] = store["到账收入MYR"] - store["货品成本MYR"] + store["退包成本MYR"]
    store["标价利润"] = _safe_margin(store["标价利润MYR"], store["标价收入MYR"])
    store["标价利润率"] = store["标价利润"]
    store["到账利润"] = _safe_margin(store["到账利润MYR"], store["到账收入MYR"])
    store["到账利润率"] = store["到账利润"]
    store["去除邮局"] = _safe_margin(store["去除邮局MYR"], store["到账收入MYR"])
    store["退货退款占比"] = -(
        store["退包成本MYR"] + store["退款金额MYR"] + store["退款成本MYR"]
    ) / store["到账收入MYR"].replace(0, np.nan)
    store = store.rename(columns={"财务编码": "店编"})
    settled_sku = (
        settled[settled["结算总金额MYR"].notna()]
        .groupby(["SKU_key", "商品中文名称"], dropna=False)
        .agg(
            订单数=("订单编号_key", "nunique"),
            销量=("商品数量_num", "sum"),
            商品金额MYR=("商品金额_num", "sum"),
            成本MYR=("商品成本MYR", "sum"),
            到账金额MYR=("到账金额MYR分摊", "sum"),
            到账利润MYR=("到账利润MYR", "sum"),
        )
        .reset_index()
    )
    settled_sku["到账利润率"] = _safe_margin(settled_sku["到账利润MYR"], settled_sku["到账金额MYR"])
    settled_sku["SKU商品"] = settled_sku["SKU_key"] + " | " + settled_sku["商品中文名称"].astype(str)

    inventory = _read_excel(price_file, sheet_name="6月库存")
    inventory = _with_numeric(inventory, ["预测日销量(个)", "仓位库存", "当前可售天数", "可用库存量"])
    inventory = _filter_inventory(inventory, valid_sales, active_filters)
    short_inventory = inventory[
        inventory["商品状态"].astype(str).str.contains("正常", na=False)
        & (inventory["预测日销量(个)_num"] > 0)
        & (inventory["当前可售天数_num"] <= 7)
    ].copy()

    overdue = _read_excel(overdue_file, sheet_name="6月分配 ", header=2)
    overdue = _with_numeric(
        overdue,
        [
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
        ],
    )
    overdue = _filter_overdue(overdue, valid_sales, active_filters)
    metrics["超期主SKU数"] = len(overdue)
    metrics["月预估超期库存"] = overdue["月预估超期库存_num"].sum()
    metrics["月预估超期金额"] = overdue["月预估超期金额_num"].sum()

    overdue_category = (
        overdue.groupby(["品类", "三级分类"], dropna=False)
        .agg(
            款数=("主SKU", "count"),
            超期库存=("月预估超期库存_num", "sum"),
            超期金额=("月预估超期金额_num", "sum"),
        )
        .reset_index()
    )

    adjustment = _read_excel(price_file, sheet_name="6月调整栏")
    selected_skus = set(_key(valid_sales["SKU_key"]).dropna()) if "SKU_key" in valid_sales.columns else set()
    if active_filters:
        adjustment_mask = pd.Series(False, index=adjustment.index)
        if selected_skus:
            adjustment_mask |= _key(adjustment["SKU"]).isin(selected_skus)
        if active_filters.get("sku") or active_filters.get("keyword"):
            text_value = active_filters.get("sku") or active_filters.get("keyword")
            adjustment_mask |= _text_contains(adjustment["SKU"], text_value) | _text_contains(adjustment["商品名称"], text_value)
        adjustment = adjustment[adjustment_mask].copy()
    adjustment_reason = (
        adjustment["特殊原因"]
        .fillna("(空)")
        .astype(str)
        .str.strip()
        .value_counts()
        .reset_index()
    )
    adjustment_reason.columns = ["特殊原因", "数量"]

    empty = pd.DataFrame()
    if active_filters:
        duplicate_package_skus = duplicate_package_skus[_key(duplicate_package_skus["SKU"]).isin(selected_skus)].copy()

    tables = {
        "店铺表现": store.sort_values("商品金额MYR", ascending=False),
        "COD分析": cod.sort_values("商品金额MYR", ascending=False),
        "销售额Top品类": category.sort_values("商品金额MYR", ascending=False),
        "销售额Top SKU": sku.sort_values("商品金额MYR", ascending=False),
        "产品日销分析": product_daily,
        "每日销量明细": daily_detail.sort_values(["日期", "日销量"], ascending=[False, False]),
        "标价利润Top SKU": sku.sort_values("标价利润MYR", ascending=False),
        "低标价利润或亏损SKU": sku[sku["商品金额MYR"] >= 1000].sort_values("标价利润MYR"),
        "零金额疑似样品赠品": zero_sku.sort_values("成本占用MYR", ascending=False),
        "到账利润SKU_匹配订单": settled_sku.sort_values("到账利润MYR", ascending=False),
        "高库存长可售天数": inventory.sort_values("当前可售天数_num", ascending=False)[
            ["库存SKU编号", "中文名称", "商品状态", "活跃度", "销量(7/28/42)", "预测日销量(个)", "仓位库存", "当前可售天数", "可用库存量"]
        ]
        if not inventory.empty
        else empty,
        "正常销售库存紧张": short_inventory.sort_values("当前可售天数_num")[
            ["库存SKU编号", "中文名称", "商品状态", "活跃度", "销量(7/28/42)", "预测日销量(个)", "仓位库存", "当前可售天数", "可用库存量"]
        ]
        if not short_inventory.empty
        else empty,
        "超期金额Top产品": overdue.sort_values("月预估超期金额_num", ascending=False)[
            [
                "主SKU",
                "商品名称",
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
            ]
        ]
        if not overdue.empty
        else empty,
        "超期金额Top品类": overdue_category.sort_values("超期金额", ascending=False),
        "控价调整原因": adjustment_reason,
        "控价调整明细": adjustment,
        "成本表重复SKU": duplicate_package_skus[
            ["SKU", "商品名称", "主SKU", "SKU状态", "销售成本人民币", "销售成本国家币"]
        ],
    }

    if not tables["零金额疑似样品赠品"].empty:
        notes.append("存在商品金额为 0 但有数量和成本的 SKU，建议在系统中单独标记为样品、赠品或配件包。")
    if not tables["低标价利润或亏损SKU"].empty:
        notes.append("发现销售额大于 1000 MYR 的低标价利润或亏损 SKU，建议复核售价、优惠券和成本。")
    if not tables["正常销售库存紧张"].empty:
        notes.append("存在正常销售但可售天数小于等于 7 天的 SKU，建议优先补货或限制投放。")
    if metrics["月预估超期金额"]:
        notes.append("超期金额较高，建议把超期金额、周转天数和毛利结合起来做清仓优先级。")

    return AnalysisResult(
        metrics=metrics,
        tables=tables,
        notes=notes,
        filter_options=filter_options,
        active_filters=active_filters,
    )


def write_excel_report(result: AnalysisResult, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_df = pd.DataFrame([{"指标": key, "数值": value} for key, value in result.metrics.items()])
    filters_df = pd.DataFrame([{"筛选项": key, "筛选值": value} for key, value in result.active_filters.items()])
    notes_df = pd.DataFrame({"经营提示": result.notes})
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        metrics_df.to_excel(writer, sheet_name="总览指标", index=False)
        filters_df.to_excel(writer, sheet_name="筛选条件", index=False)
        notes_df.to_excel(writer, sheet_name="经营提示", index=False)
        for sheet_name, df in result.tables.items():
            safe_name = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)
    return output_path


def discover_default_files(base_dir: str | Path = ".") -> dict[str, Path | None]:
    base = Path(base_dir)
    files = list(base.glob("*.xlsx"))
    return {
        "sales": next((p for p in files if "销售数据" in p.name), None),
        "income": next((p for p in files if "income_" in p.name), None),
        "price": next((p for p in files if "控价" in p.name), None),
        "overdue": next((p for p in files if "超期" in p.name), None),
    }
