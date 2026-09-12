from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd

from ecom_ops.agents.common import Recommendation, clean_text, pct_change, priority_from_risk
from ecom_ops.core.database import create_run, finish_run, log_artifact, log_decision
from ecom_ops.core.excel import find_column, read_excel, write_workbook
from ecom_ops.core.logging import configure_logging
from ecom_ops.core.settings import Settings, get_settings


logger = logging.getLogger(__name__)


SALES_ALIASES = {
    "sku": ["sku", "SKU", "seller sku", "商家SKU", "商品SKU", "库存SKU编号", "子SKU", "变种SKU"],
    "product_name": ["product_name", "product name", "商品名称", "商品中文名称", "中文名称", "产品名称"],
    "date": ["date", "日期", "付款时间", "支付时间", "订单创建时间", "创建时间"],
    "quantity": ["quantity", "qty", "销量", "商品数量", "销售数量", "件数"],
    "sales_amount": ["sales_amount", "amount", "销售额", "商品金额", "订单总金额", "GMV", "付款金额"],
    "traffic": ["traffic", "visitors", "曝光", "访客", "点击", "浏览量", "PV", "UV"],
    "conversion_rate": ["conversion_rate", "转化率", "支付转化率", "成交转化率"],
    "stock": ["stock", "inventory", "库存", "可用库存量", "仓位库存", "当前库存"],
    "price": ["price", "售价", "销售价", "商品销售单价", "原价"],
    "image_click_rate": ["image_click_rate", "主图点击率", "点击率", "CTR"],
    "creator_material_count": ["creator_material_count", "素材数量", "达人素材数", "短视频素材数"],
}


@dataclass
class SalesAnalysis:
    daily_sales_report: pd.DataFrame
    coupon_application_list: pd.DataFrame
    creator_material_demand_list: pd.DataFrame
    high_risk_product_list: pd.DataFrame
    markdown_summary: str


@dataclass
class SalesRunResult:
    run_id: str
    report_path: Path
    markdown_path: Path
    analysis: SalesAnalysis


def _num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _optional_num(df: pd.DataFrame, column: str | None, default: float = 0.0) -> pd.Series:
    if column and column in df.columns:
        return _num(df[column], default)
    return pd.Series(default, index=df.index)


def _optional_text(df: pd.DataFrame, column: str | None, default: str = "") -> pd.Series:
    if column and column in df.columns:
        return df[column].map(lambda value: clean_text(value, default))
    return pd.Series(default, index=df.index)


def _column_map(df: pd.DataFrame) -> dict[str, str | None]:
    return {
        key: find_column(df, aliases, required=key in {"sku", "date", "quantity"})
        for key, aliases in SALES_ALIASES.items()
    }


def _prepare_sales(df: pd.DataFrame) -> pd.DataFrame:
    columns = _column_map(df)
    prepared = pd.DataFrame(index=df.index)
    prepared["sku"] = _optional_text(df, columns["sku"], "UNKNOWN-SKU")
    prepared["product_name"] = _optional_text(df, columns["product_name"], "").where(
        lambda value: value.astype(str).str.len() > 0,
        prepared["sku"],
    )
    prepared["date"] = pd.to_datetime(df[columns["date"]], errors="coerce").dt.normalize()  # type: ignore[index]
    prepared["quantity"] = _optional_num(df, columns["quantity"])
    prepared["sales_amount"] = _optional_num(df, columns["sales_amount"])
    prepared["traffic"] = _optional_num(df, columns["traffic"])
    prepared["conversion_rate"] = _optional_num(df, columns["conversion_rate"])
    prepared["stock"] = _optional_num(df, columns["stock"], default=float("nan"))
    prepared["price"] = _optional_num(df, columns["price"], default=float("nan"))
    prepared["image_click_rate"] = _optional_num(df, columns["image_click_rate"], default=float("nan"))
    prepared["creator_material_count"] = _optional_num(df, columns["creator_material_count"], default=float("nan"))
    prepared = prepared.dropna(subset=["date"])
    prepared = prepared[prepared["sku"].astype(str).str.len() > 0]
    if prepared.empty:
        raise ValueError("No usable sales rows after reading SKU, date, and quantity columns.")
    return prepared


def _latest_and_previous_dates(dates_source: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp | None]:
    dates = sorted(pd.to_datetime(dates_source.dropna()).unique())
    latest = pd.Timestamp(dates[-1])
    previous = pd.Timestamp(dates[-2]) if len(dates) >= 2 else None
    return latest, previous


def _build_daily_report(prepared: pd.DataFrame) -> pd.DataFrame:
    daily = (
        prepared.groupby(["date", "sku", "product_name"], dropna=False)
        .agg(
            quantity=("quantity", "sum"),
            sales_amount=("sales_amount", "sum"),
            traffic=("traffic", "sum"),
            conversion_rate=("conversion_rate", "mean"),
            stock=("stock", "last"),
            price=("price", "mean"),
            image_click_rate=("image_click_rate", "mean"),
            creator_material_count=("creator_material_count", "last"),
        )
        .reset_index()
        .sort_values(["date", "quantity"], ascending=[False, False])
    )
    daily["date"] = pd.to_datetime(daily["date"]).dt.date.astype(str)
    return daily


def _product_summary(prepared: pd.DataFrame) -> pd.DataFrame:
    daily = _build_daily_report(prepared)
    daily["_date"] = pd.to_datetime(daily["date"])
    latest_date, previous_date = _latest_and_previous_dates(daily["_date"])
    latest = daily[daily["_date"] == latest_date][["sku", "quantity", "sales_amount", "traffic"]].rename(
        columns={
            "quantity": "latest_quantity",
            "sales_amount": "latest_sales_amount",
            "traffic": "latest_traffic",
        }
    )
    if previous_date is not None:
        previous = daily[daily["_date"] == previous_date][["sku", "quantity", "traffic"]].rename(
            columns={"quantity": "previous_quantity", "traffic": "previous_traffic"}
        )
    else:
        previous = pd.DataFrame({"sku": latest["sku"], "previous_quantity": 0.0, "previous_traffic": 0.0})

    summary = (
        prepared.groupby(["sku", "product_name"], dropna=False)
        .agg(
            total_quantity=("quantity", "sum"),
            total_sales_amount=("sales_amount", "sum"),
            avg_daily_quantity=("quantity", "mean"),
            avg_conversion_rate=("conversion_rate", "mean"),
            avg_image_click_rate=("image_click_rate", "mean"),
            avg_price=("price", "mean"),
            latest_stock=("stock", "last"),
            creator_material_count=("creator_material_count", "last"),
        )
        .reset_index()
    )
    summary = summary.merge(latest, on="sku", how="left").merge(previous, on="sku", how="left")
    for column in ["latest_quantity", "latest_sales_amount", "latest_traffic", "previous_quantity", "previous_traffic"]:
        summary[column] = summary[column].fillna(0)
    summary["quantity_change"] = summary["latest_quantity"] - summary["previous_quantity"]
    summary["quantity_change_pct"] = [
        pct_change(current, previous)
        for current, previous in zip(summary["latest_quantity"], summary["previous_quantity"], strict=False)
    ]
    summary["traffic_change_pct"] = [
        pct_change(current, previous)
        for current, previous in zip(summary["latest_traffic"], summary["previous_traffic"], strict=False)
    ]
    summary["stock_days"] = summary["latest_stock"] / summary["avg_daily_quantity"].replace(0, pd.NA)
    return summary


def _rec(product: pd.Series, reason: str, risk: str, action: str) -> Recommendation:
    return Recommendation(
        product_name=clean_text(product.get("product_name"), clean_text(product.get("sku"), "UNKNOWN-SKU")),
        sku=clean_text(product.get("sku"), "UNKNOWN-SKU"),
        data_reason=reason,
        risk_level=risk,
        recommended_action=action,
        priority_level=priority_from_risk(risk),
    )


def _recommendations(summary: pd.DataFrame) -> tuple[list[Recommendation], list[Recommendation], list[Recommendation]]:
    coupons: list[Recommendation] = []
    materials: list[Recommendation] = []
    high_risk: list[Recommendation] = []

    for _, product in summary.iterrows():
        latest_qty = float(product["latest_quantity"])
        previous_qty = float(product["previous_quantity"])
        qty_change_pct = float(product["quantity_change_pct"])
        traffic_change_pct = float(product["traffic_change_pct"])
        stock_days = product.get("stock_days")
        conversion = float(product.get("avg_conversion_rate") or 0)
        image_ctr = product.get("avg_image_click_rate")
        creator_count = product.get("creator_material_count")
        traffic = float(product.get("latest_traffic") or 0)

        is_rising = latest_qty >= max(previous_qty * 1.3, previous_qty + 2) and latest_qty > 0
        is_falling = previous_qty > 0 and latest_qty <= previous_qty * 0.7
        traffic_loss = product["previous_traffic"] > 0 and traffic_change_pct <= -0.25
        low_stock = pd.notna(stock_days) and float(stock_days) <= 7
        medium_stock = pd.notna(stock_days) and 7 < float(stock_days) <= 14
        low_conversion = traffic >= 100 and conversion > 0 and conversion < 0.02
        image_issue = traffic >= 100 and pd.notna(image_ctr) and float(image_ctr) < 0.01
        material_short = is_rising and (pd.isna(creator_count) or float(creator_count) <= 1)

        if is_falling or low_conversion:
            risk = "High" if is_falling and traffic >= 100 else "Medium"
            reason = (
                f"latest daily sales {latest_qty:.0f}, previous {previous_qty:.0f}, "
                f"change {qty_change_pct:.1%}; conversion {conversion:.2%}; traffic {traffic:.0f}"
            )
            action = "Prepare coupon test, review price ladder, and check competitor price before manual approval."
            coupons.append(_rec(product, reason, risk, action))

        if material_short:
            reason = (
                f"sales rising from {previous_qty:.0f} to {latest_qty:.0f}; "
                f"creator materials on record {0 if pd.isna(creator_count) else creator_count:.0f}"
            )
            action = "Prepare creator brief with selling points, SKU links, and short-video material request."
            materials.append(_rec(product, reason, "Medium", action))

        risk_reasons: list[str] = []
        actions: list[str] = []
        risk = "Low"
        if is_falling:
            risk = "High"
            risk_reasons.append(f"falling sales {previous_qty:.0f} -> {latest_qty:.0f}")
            actions.append("Review traffic source, coupon history, and listing changes today.")
        if traffic_loss:
            risk = "High"
            risk_reasons.append(f"traffic down {traffic_change_pct:.1%}")
            actions.append("Check ad status, search ranking, and platform traffic allocation.")
        if low_stock or medium_stock:
            stock_risk = "High" if low_stock else "Medium"
            risk = "High" if low_stock else risk
            risk_reasons.append(f"stock can cover {float(stock_days):.1f} days")
            actions.append("Prioritize replenishment or slow paid traffic until stock is confirmed.")
            if risk != "High":
                risk = stock_risk
        if image_issue:
            if risk != "High":
                risk = "Medium"
            risk_reasons.append(f"main image click rate {float(image_ctr):.2%} with traffic {traffic:.0f}")
            actions.append("Prepare alternate main image and compare click-through data.")
        if low_conversion:
            if risk != "High":
                risk = "Medium"
            risk_reasons.append(f"conversion {conversion:.2%} with traffic {traffic:.0f}")
            actions.append("Check price, reviews, coupons, and product detail page conversion blockers.")
        if is_rising and not risk_reasons:
            risk_reasons.append(f"rising sales {previous_qty:.0f} -> {latest_qty:.0f}")
            actions.append("Protect inventory and prepare creator materials while traffic is warm.")
            risk = "Low"
        if risk_reasons:
            high_risk.append(_rec(product, "; ".join(risk_reasons), risk, " ".join(dict.fromkeys(actions))))

    return coupons, materials, high_risk


def _to_frame(items: list[Recommendation]) -> pd.DataFrame:
    columns = ["product_name", "sku", "data_reason", "risk_level", "recommended_action", "priority_level"]
    if not items:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([item.to_dict() for item in items], columns=columns)


def _markdown(summary: pd.DataFrame, coupons: pd.DataFrame, materials: pd.DataFrame, high_risk: pd.DataFrame) -> str:
    total_qty = summary["total_quantity"].sum()
    total_amount = summary["total_sales_amount"].sum()
    lines = [
        "# Daily Sales Operation Summary",
        "",
        f"- Products analyzed: {summary['sku'].nunique()}",
        f"- Total quantity: {total_qty:.0f}",
        f"- Total sales amount: {total_amount:.2f}",
        f"- Coupon candidates: {len(coupons)}",
        f"- Creator material requests: {len(materials)}",
        f"- Products needing attention: {len(high_risk)}",
        "",
        "## Priority Actions",
    ]
    if high_risk.empty:
        lines.append("- No high-risk product found from the available columns.")
    else:
        for item in high_risk.sort_values(["priority_level", "risk_level"]).head(20).itertuples(index=False):
            lines.append(
                f"- {item.product_name} / {item.sku}: {item.data_reason}. "
                f"Risk {item.risk_level}, priority {item.priority_level}. Action: {item.recommended_action}"
            )
    return "\n".join(lines) + "\n"


def analyze_sales_dataframe(df: pd.DataFrame) -> SalesAnalysis:
    prepared = _prepare_sales(df)
    daily_report = _build_daily_report(prepared)
    summary = _product_summary(prepared)
    coupons, materials, high_risk = _recommendations(summary)
    coupon_df = _to_frame(coupons)
    material_df = _to_frame(materials)
    high_risk_df = _to_frame(high_risk)
    return SalesAnalysis(
        daily_sales_report=daily_report,
        coupon_application_list=coupon_df,
        creator_material_demand_list=material_df,
        high_risk_product_list=high_risk_df,
        markdown_summary=_markdown(summary, coupon_df, material_df, high_risk_df),
    )


class SalesAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def run(self, sales_file: str | Path, output_dir: str | Path | None = None) -> SalesRunResult:
        input_path = Path(sales_file)
        run_id = create_run(self.settings.sqlite_path, "sales", input_path)
        configure_logging(self.settings, run_id)
        logger.info("Starting sales analysis for %s", input_path)
        try:
            df = read_excel(input_path)
            analysis = analyze_sales_dataframe(df)
            out_dir = Path(output_dir) if output_dir else self.settings.output_dir
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = out_dir / f"sales_agent_report_{stamp}.xlsx"
            markdown_path = out_dir / f"sales_agent_summary_{stamp}.md"
            write_workbook(
                report_path,
                {
                    "daily_sales_report": analysis.daily_sales_report,
                    "coupon_application_list": analysis.coupon_application_list,
                    "creator_material_demand": analysis.creator_material_demand_list,
                    "high_risk_product_list": analysis.high_risk_product_list,
                },
            )
            markdown_path.write_text(analysis.markdown_summary, encoding="utf-8")
            for table_name, table in {
                "coupon": analysis.coupon_application_list,
                "creator_material": analysis.creator_material_demand_list,
                "risk": analysis.high_risk_product_list,
            }.items():
                for row in table.itertuples(index=False):
                    log_decision(
                        self.settings.sqlite_path,
                        run_id,
                        table_name,
                        row.sku,
                        row.recommended_action,
                        row.data_reason,
                        row.risk_level,
                        row.priority_level,
                    )
            log_artifact(self.settings.sqlite_path, run_id, "excel_report", report_path)
            log_artifact(self.settings.sqlite_path, run_id, "markdown_summary", markdown_path)
            finish_run(self.settings.sqlite_path, run_id, "completed", report_path)
            return SalesRunResult(run_id, report_path, markdown_path, analysis)
        except Exception as exc:
            finish_run(self.settings.sqlite_path, run_id, "failed", notes=str(exc))
            logger.exception("Sales analysis failed")
            raise
