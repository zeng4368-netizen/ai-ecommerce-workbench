from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd
from flask import Flask, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ecom_ops.agents.complaints import ComplaintAgent  # noqa: E402
from ecom_ops.agents.sales import SalesAgent  # noqa: E402
from ecom_ops.core.settings import get_settings  # noqa: E402


settings = get_settings()
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024


AGENT_LABELS = {
    "complaints": "投诉登记 Agent",
    "sales": "销售分析 Agent",
}

SHEET_LABELS = {
    "complaint_registration": "投诉登记明细",
    "category_summary": "投诉分类汇总",
    "good_suspected_good": "良品/疑似良品",
    "defective_products": "不良品清单",
    "human_review_list": "人工复核清单",
    "daily_sales_report": "每日销售报告",
    "coupon_application_list": "优惠券申请清单",
    "creator_material_demand": "达人素材需求",
    "high_risk_product_list": "高风险商品",
}

COLUMN_LABELS = {
    "case_id": "投诉编号",
    "order_id": "订单号",
    "product_name": "商品名称",
    "sku": "SKU",
    "complaint_text": "投诉内容",
    "requested_action": "客户诉求",
    "complaint_category": "投诉分类",
    "product_condition": "商品状态",
    "confidence": "置信度",
    "data_reason": "数据原因",
    "risk_level": "风险等级",
    "recommended_action": "建议动作",
    "priority_level": "优先级",
    "requires_human_confirmation": "需人工确认",
    "date": "日期",
    "quantity": "销量",
    "sales_amount": "销售额",
    "traffic": "流量",
    "conversion_rate": "转化率",
    "stock": "库存",
    "price": "价格",
    "image_click_rate": "主图点击率",
    "creator_material_count": "素材数",
}


def _safe_filename(file_name: str, fallback: str) -> str:
    path = Path(file_name or fallback)
    stem = secure_filename(path.stem) or fallback
    suffix = path.suffix if path.suffix.lower() in {".xlsx", ".xls"} else ".xlsx"
    return f"{stem}{suffix}"


def _save_upload(agent: str) -> Path:
    upload = request.files.get("file")
    if not upload or not upload.filename:
        raise ValueError("请选择一个 Excel 文件。")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = _safe_filename(upload.filename, agent)
    target = settings.raw_dir / f"{agent}_{stamp}_{filename}"
    upload.save(target)
    return target


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_runs(limit: int = 8) -> list[dict[str, Any]]:
    if not settings.sqlite_path.exists():
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, agent, status, started_at, ended_at, input_path, output_path
            FROM runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _run_by_id(run_id: str) -> dict[str, Any] | None:
    if not settings.sqlite_path.exists():
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, agent, status, started_at, ended_at, input_path, output_path, notes
            FROM runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    return dict(row) if row else None


def _artifact_paths(run_id: str) -> list[dict[str, Any]]:
    if not settings.sqlite_path.exists():
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT artifact_type, path, created_at
            FROM artifacts
            WHERE run_id = ?
            ORDER BY created_at
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _display_df(df: pd.DataFrame, rows: int = 80) -> pd.DataFrame:
    view = df.head(rows).copy()
    view = view.rename(columns={col: COLUMN_LABELS.get(str(col), str(col)) for col in view.columns})
    for col in view.columns:
        if pd.api.types.is_bool_dtype(view[col]):
            view[col] = view[col].map(lambda value: "是" if value else "否")
        elif pd.api.types.is_float_dtype(view[col]):
            view[col] = view[col].map(lambda value: "" if pd.isna(value) else f"{value:.4g}")
        else:
            view[col] = view[col].fillna("")
    return view


def _sheet_previews(report_path: str | Path | None) -> list[dict[str, Any]]:
    if not report_path:
        return []
    path = Path(report_path)
    if not path.exists() or path.suffix.lower() not in {".xlsx", ".xls"}:
        return []
    sheets = pd.read_excel(path, sheet_name=None)
    previews: list[dict[str, Any]] = []
    for name, df in sheets.items():
        previews.append(
            {
                "name": name,
                "label": SHEET_LABELS.get(name, name),
                "row_count": len(df),
                "html": _display_df(df).to_html(index=False, classes="ops-table", border=0, escape=True),
            }
        )
    return previews


def _markdown_preview(artifacts: list[dict[str, Any]]) -> str:
    for artifact in artifacts:
        path = Path(artifact["path"])
        if path.suffix.lower() == ".md" and path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def _ensure_output_path(raw_path: str) -> Path:
    path = Path(raw_path).resolve()
    output_root = settings.output_dir.resolve()
    if not path.is_file() or output_root not in path.parents:
        raise FileNotFoundError("文件不存在或不允许下载。")
    return path


@app.get("/")
def index():
    return render_template(
        "ops_dashboard.html",
        active_agent="complaints",
        agent_labels=AGENT_LABELS,
        runs=_latest_runs(),
        error=request.args.get("error", ""),
    )


@app.post("/run/<agent>")
def run_agent(agent: str):
    try:
        input_path = _save_upload(agent)
        if agent == "complaints":
            result = ComplaintAgent(settings).run(input_path)
        elif agent == "sales":
            result = SalesAgent(settings).run(input_path)
        else:
            raise ValueError("未知 Agent。")
        return redirect(url_for("run_detail", run_id=result.run_id))
    except Exception as exc:
        return redirect(url_for("index", error=str(exc)))


@app.get("/runs/<run_id>")
def run_detail(run_id: str):
    run = _run_by_id(run_id)
    if not run:
        return redirect(url_for("index", error="找不到这次运行记录。"))
    artifacts = _artifact_paths(run_id)
    return render_template(
        "ops_dashboard.html",
        active_agent=run["agent"],
        agent_labels=AGENT_LABELS,
        runs=_latest_runs(),
        current_run=run,
        artifacts=artifacts,
        previews=_sheet_previews(run.get("output_path")),
        markdown_preview=_markdown_preview(artifacts),
        error="",
    )


@app.get("/download")
def download():
    path = _ensure_output_path(request.args.get("path", ""))
    return send_file(path, as_attachment=True, download_name=path.name)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
