from __future__ import annotations

import json
import math
import os
from datetime import datetime
from html import escape
from pathlib import Path
from uuid import uuid4

import pandas as pd
from flask import Flask, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from ecommerce_analyzer import analyze_files, discover_default_files, write_excel_report


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
REPORT_DIR = BASE_DIR / "reports"

UPLOAD_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024


FILE_FIELDS = {
    "sales": "销售数据表",
    "income": "结算收入表",
    "price": "控价/成本/库存表",
    "overdue": "超期库存表",
}


FILTER_LABELS = {
    "shop": "店铺",
    "sku": "SKU",
    "keyword": "产品关键词",
    "category1": "一级类目",
    "category2": "二级类目",
    "category3": "三级类目",
}


def _is_percentage_name(name: str) -> bool:
    return "率" in name or "比例" in name or "占比" in name or name in {"标价利润", "到账利润", "去除邮局"}


def _fmt(value, metric_name: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M") if not pd.isna(value) else "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    try:
        if pd.isna(value):
            return "-"
    except TypeError:
        pass
    if isinstance(value, (int, float)):
        if _is_percentage_name(metric_name):
            return f"{value * 100:,.2f}%"
        if abs(value) >= 1000:
            return f"{value:,.2f}"
        return f"{value:.2f}"
    return str(value)


def _session_dir(session_id: str) -> Path:
    return UPLOAD_DIR / session_id


def _manifest_path(session_id: str) -> Path:
    return _session_dir(session_id) / "manifest.json"


def _save_uploads(session_id: str) -> tuple[dict[str, Path], dict[str, str]]:
    session_dir = _session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    defaults = discover_default_files(BASE_DIR)
    files: dict[str, Path] = {}
    sources: dict[str, str] = {}

    for field, label in FILE_FIELDS.items():
        upload = request.files.get(field)
        if upload and upload.filename:
            original_name = upload.filename
            suffix = Path(original_name).suffix or ".xlsx"
            safe_stem = secure_filename(Path(original_name).stem) or field
            filename = f"{field}_{safe_stem}{suffix}"
            path = session_dir / filename
            upload.save(path)
            files[field] = path
            sources[field] = f"上传：{original_name}"
        elif defaults.get(field):
            files[field] = defaults[field]
            sources[field] = f"默认：{defaults[field].name}"
        else:
            raise ValueError(f"缺少{label}，请上传对应 Excel 文件。")

    return files, sources


def _write_manifest(session_id: str, files: dict[str, Path], sources: dict[str, str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files": {key: str(path) for key, path in files.items()},
        "sources": sources,
    }
    _manifest_path(session_id).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_manifest(session_id: str) -> dict[str, object]:
    path = _manifest_path(session_id)
    if not path.exists():
        raise FileNotFoundError("找不到这次分析会话，请重新上传表格。")
    return json.loads(path.read_text(encoding="utf-8"))


def _get_filters() -> dict[str, str]:
    return {
        key: request.args.get(key, "").strip()
        for key in FILTER_LABELS
        if request.args.get(key, "").strip()
    }


def _filter_summary(filters: dict[str, str]) -> list[str]:
    return [f"{FILTER_LABELS.get(key, key)}：{value}" for key, value in filters.items()]


def _table_html(df: pd.DataFrame) -> str:
    view = df.copy()
    for col in view.columns:
        if pd.api.types.is_float_dtype(view[col]):
            if _is_percentage_name(str(col)):
                view[col] = view[col].map(lambda x: "-" if pd.isna(x) else f"{x * 100:,.2f}%")
            else:
                view[col] = view[col].map(lambda x: "-" if pd.isna(x) else f"{x:,.2f}")
        elif pd.api.types.is_integer_dtype(view[col]):
            view[col] = view[col].map(lambda x: "-" if pd.isna(x) else f"{x:,}")
        elif pd.api.types.is_datetime64_any_dtype(view[col]):
            view[col] = view[col].dt.strftime("%Y-%m-%d").fillna("-")
    return view.to_html(index=False, classes="data-table", border=0, escape=True)


CHART_COLORS = [
    "#176b57",
    "#0f4c81",
    "#9b5b2e",
    "#6f5aa7",
    "#c47a2c",
    "#547a45",
    "#b65f5b",
    "#506d8a",
    "#8f6b35",
]


def _short_text(value: object, limit: int = 22) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _chart_series(df: pd.DataFrame, label_col: str, value_col: str, limit: int = 8) -> list[dict[str, object]]:
    if df is None or df.empty or label_col not in df.columns or value_col not in df.columns:
        return []
    series_df = df[[label_col, value_col]].copy()
    series_df[value_col] = pd.to_numeric(series_df[value_col], errors="coerce").fillna(0)
    series_df = series_df[series_df[value_col] > 0]
    if series_df.empty:
        return []
    series_df = series_df.groupby(label_col, dropna=False)[value_col].sum().reset_index()
    series_df = series_df.sort_values(value_col, ascending=False)
    top = series_df.head(limit).copy()
    remainder = series_df.iloc[limit:][value_col].sum()
    if remainder > 0:
        top = pd.concat([top, pd.DataFrame([{label_col: "其他", value_col: remainder}])], ignore_index=True)
    return [{"label": str(row[label_col]), "value": float(row[value_col])} for _, row in top.iterrows()]


def _format_chart_value(value: float) -> str:
    if abs(value) >= 10000:
        return f"{value / 10000:,.1f}万"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _bar_chart_svg(items: list[dict[str, object]], value_label: str = "") -> str:
    if not items:
        return '<div class="chart-empty">暂无可视化数据</div>'
    width = 1040
    row_h = 34
    top_pad = 16
    left_w = 360
    bar_w = 500
    height = top_pad * 2 + row_h * len(items)
    max_value = max(float(item["value"]) for item in items) or 1
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart-svg">']
    for index, item in enumerate(items):
        value = float(item["value"])
        y = top_pad + index * row_h
        bar_len = max(2, value / max_value * bar_w)
        color = CHART_COLORS[index % len(CHART_COLORS)]
        label = escape(_short_text(item["label"], 44))
        value_text = escape(_format_chart_value(value) + (f" {value_label}" if value_label else ""))
        parts.append(f'<text x="8" y="{y + 20}" class="chart-label">{label}</text>')
        parts.append(f'<rect x="{left_w}" y="{y + 5}" width="{bar_w}" height="18" rx="4" class="bar-bg"></rect>')
        parts.append(f'<rect x="{left_w}" y="{y + 5}" width="{bar_len:.2f}" height="18" rx="4" fill="{color}"></rect>')
        parts.append(f'<text x="{left_w + bar_w + 16}" y="{y + 20}" class="chart-value">{value_text}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _pie_slice_path(cx: float, cy: float, radius: float, start_angle: float, end_angle: float) -> str:
    x1 = cx + radius * math.cos(start_angle)
    y1 = cy + radius * math.sin(start_angle)
    x2 = cx + radius * math.cos(end_angle)
    y2 = cy + radius * math.sin(end_angle)
    large_arc = 1 if end_angle - start_angle > math.pi else 0
    return f"M {cx} {cy} L {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large_arc} 1 {x2:.2f} {y2:.2f} Z"


def _pie_chart_svg(items: list[dict[str, object]]) -> str:
    if not items:
        return '<div class="chart-empty">暂无可视化数据</div>'
    width = 760
    height = 300
    cx = 142
    cy = 150
    radius = 112
    total = sum(float(item["value"]) for item in items)
    if total <= 0:
        return '<div class="chart-empty">暂无可视化数据</div>'
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart-svg">']
    start = -math.pi / 2
    if len(items) == 1:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{CHART_COLORS[0]}"></circle>')
    else:
        for index, item in enumerate(items):
            value = float(item["value"])
            end = start + value / total * math.tau
            path = _pie_slice_path(cx, cy, radius, start, end)
            color = CHART_COLORS[index % len(CHART_COLORS)]
            parts.append(f'<path d="{path}" fill="{color}"></path>')
            start = end
    legend_x = 310
    for index, item in enumerate(items):
        y = 48 + index * 26
        color = CHART_COLORS[index % len(CHART_COLORS)]
        pct = float(item["value"]) / total * 100
        label = escape(_short_text(item["label"], 24))
        value_text = escape(f"{_format_chart_value(float(item['value']))} / {pct:.1f}%")
        parts.append(f'<rect x="{legend_x}" y="{y - 12}" width="13" height="13" rx="3" fill="{color}"></rect>')
        parts.append(f'<text x="{legend_x + 22}" y="{y}" class="chart-label">{label}</text>')
        parts.append(f'<text x="{legend_x + 250}" y="{y}" class="chart-value">{value_text}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _daily_sales_series(df: pd.DataFrame) -> list[dict[str, object]]:
    if df is None or df.empty or "日期" not in df.columns or "日销量" not in df.columns:
        return []
    daily = df[["日期", "日销量"]].copy()
    daily["日销量"] = pd.to_numeric(daily["日销量"], errors="coerce").fillna(0)
    daily = daily.groupby("日期", dropna=False)["日销量"].sum().reset_index().sort_values("日期")
    daily = daily.tail(31)
    return [{"label": str(row["日期"])[:10], "value": float(row["日销量"])} for _, row in daily.iterrows()]


def _build_charts(result) -> list[dict[str, str]]:
    tables = result.tables
    charts: list[dict[str, str]] = []

    store_items = _chart_series(tables.get("店铺表现"), "店铺名", "商品金额MYR", limit=8)
    if store_items:
        charts.append({"title": "店铺销售额排名", "kind": "条形图", "html": _bar_chart_svg(store_items, "MYR")})

    sku_items = _chart_series(tables.get("销售额Top SKU"), "SKU商品", "商品金额MYR", limit=10)
    if sku_items:
        charts.append({"title": "SKU 销售额 Top", "kind": "条形图", "html": _bar_chart_svg(sku_items, "MYR")})

    daily_items = _chart_series(tables.get("产品日销分析"), "SKU商品", "全周期日均销量", limit=10)
    if daily_items:
        charts.append({"title": "产品日均销量 Top", "kind": "条形图", "html": _bar_chart_svg(daily_items, "件/天")})

    trend_items = _daily_sales_series(tables.get("每日销量明细"))
    if trend_items:
        charts.append({"title": "每日销量走势", "kind": "条形图", "html": _bar_chart_svg(trend_items, "件")})

    cod_items = _chart_series(tables.get("COD分析"), "是否COD", "商品金额MYR", limit=4)
    if cod_items:
        charts.append({"title": "COD / 非 COD 销售额占比", "kind": "饼图", "html": _pie_chart_svg(cod_items)})

    category_table = tables.get("销售额Top品类")
    if category_table is not None and not category_table.empty:
        category_view = category_table.copy()
        category_view["类目"] = category_view["二级类目"].astype(str) + " / " + category_view["三级类目"].astype(str)
        category_items = _chart_series(category_view, "类目", "商品金额MYR", limit=8)
        if category_items:
            charts.append({"title": "品类销售额占比", "kind": "饼图", "html": _pie_chart_svg(category_items)})

    overdue_items = _chart_series(tables.get("超期金额Top品类"), "三级分类", "超期金额", limit=8)
    if overdue_items:
        charts.append({"title": "超期金额占比", "kind": "饼图", "html": _pie_chart_svg(overdue_items)})

    return charts


def _build_report(session_id: str, filters: dict[str, str]):
    manifest = _read_manifest(session_id)
    file_paths = {key: Path(path) for key, path in manifest["files"].items()}
    result = analyze_files(
        sales_file=file_paths["sales"],
        income_file=file_paths["income"],
        price_file=file_paths["price"],
        overdue_file=file_paths["overdue"],
        filters=filters,
    )

    suffix = "filtered" if filters else "all"
    report_name = f"ecommerce_report_{session_id}_{suffix}_{datetime.now().strftime('%H%M%S')}.xlsx"
    write_excel_report(result, REPORT_DIR / report_name)

    primary_metrics = [
        "非作废订单数",
        "非作废SKU数",
        "非作废销量",
        "总收入MYR",
        "结算总金额MYR",
        "货品成本MYR",
        "标价利润",
        "到账利润",
        "去除邮局",
        "退货退款占比",
        "退包成本MYR",
        "退款金额MYR",
        "退款成本MYR",
        "月预估超期金额",
        "结算匹配订单率",
        "成本匹配行覆盖率",
    ]
    metrics = [
        {"name": name, "value": _fmt(result.metrics.get(name), name)}
        for name in primary_metrics
        if name in result.metrics
    ]

    sections = []
    for title in [
        "店铺表现",
        "COD分析",
        "销售额Top品类",
        "销售额Top SKU",
        "产品日销分析",
        "每日销量明细",
        "标价利润Top SKU",
        "低标价利润或亏损SKU",
        "零金额疑似样品赠品",
        "到账利润SKU_匹配订单",
        "高库存长可售天数",
        "正常销售库存紧张",
        "超期金额Top产品",
        "超期金额Top品类",
        "控价调整原因",
        "控价调整明细",
        "成本表重复SKU",
    ]:
        df = result.tables.get(title)
        if df is not None and not df.empty:
            sections.append({"title": title, "rows": len(df), "html": _table_html(df)})

    return {
        "metrics": metrics,
        "charts": _build_charts(result),
        "notes": result.notes,
        "sources": manifest["sources"],
        "sections": sections,
        "report_name": report_name,
        "filter_options": result.filter_options,
        "filters": filters,
        "filter_summary": _filter_summary(filters),
    }


@app.get("/")
def index():
    defaults = discover_default_files(BASE_DIR)
    return render_template("index.html", defaults=defaults, file_fields=FILE_FIELDS)


@app.post("/analyze")
def analyze():
    try:
        session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        files, sources = _save_uploads(session_id)
        _write_manifest(session_id, files, sources)
        return redirect(url_for("report", session_id=session_id))
    except Exception as exc:
        return (
            render_template(
                "index.html",
                defaults=discover_default_files(BASE_DIR),
                file_fields=FILE_FIELDS,
                error=str(exc),
            ),
            400,
        )


@app.get("/report/<session_id>")
def report(session_id: str):
    try:
        filters = _get_filters()
        context = _build_report(session_id, filters)
        return render_template(
            "report.html",
            session_id=session_id,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **context,
        )
    except Exception as exc:
        return (
            render_template(
                "index.html",
                defaults=discover_default_files(BASE_DIR),
                file_fields=FILE_FIELDS,
                error=str(exc),
            ),
            400,
        )


@app.get("/download/<path:filename>")
def download(filename: str):
    return send_from_directory(REPORT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
