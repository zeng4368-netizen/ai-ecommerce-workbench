from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd

from ecom_ops.agents.common import clean_text
from ecom_ops.core.database import create_run, finish_run, log_artifact, log_decision
from ecom_ops.core.excel import find_column, read_excel, write_workbook
from ecom_ops.core.logging import configure_logging
from ecom_ops.core.settings import Settings, get_settings


logger = logging.getLogger(__name__)


COMPLAINT_ALIASES = {
    "case_id": ["case_id", "ticket_id", "工单号", "投诉编号", "售后单号"],
    "order_id": ["order_id", "订单号", "订单编号", "订单ID"],
    "sku": ["sku", "SKU", "商家SKU", "商品SKU", "库存SKU编号"],
    "product_name": ["product_name", "商品名称", "产品名称", "商品中文名称"],
    "complaint_text": ["complaint_text", "message", "问题描述", "投诉内容", "买家留言", "客户反馈", "售后原因"],
    "requested_action": ["requested_action", "诉求", "买家诉求", "退款退货类型", "处理方式"],
}


CATEGORY_KEYWORDS = {
    "Logistics damage": ["logistics damage", "shipping damage", "damaged in transit", "物流破损", "运输破损", "包裹破损", "外箱破", "快递压坏"],
    "Missing parts": ["missing part", "missing accessory", "少件", "缺件", "漏发", "少配件", "没有螺丝", "配件缺失"],
    "Usage problem": ["cannot use", "how to use", "不会用", "无法使用", "使用问题", "操作问题", "不会操作"],
    "Installation problem": ["install", "assembly", "安装", "组装", "装不上", "不会安装", "安装问题"],
    "Quality issue": ["quality", "broken", "defective", "not working", "坏了", "破损", "质量", "故障", "不能用", "开裂", "断裂"],
    "Description mismatch": ["not as described", "wrong color", "wrong size", "mismatch", "描述不符", "颜色不符", "尺寸不符", "货不对版", "发错"],
    "Return/refund": ["refund", "return", "退货", "退款", "仅退款", "退回"],
    "Delivery delay": ["late delivery", "delay", "not received", "物流慢", "延迟", "超时", "未收到", "还没到"],
    "Customer mistaken purchase": ["wrong purchase", "ordered by mistake", "changed mind", "买错", "拍错", "不想要", "不需要"],
    "Malicious or unclear complaint": ["scam", "fake", "恶意", "威胁", "不清楚", "无理由", "乱写", "unknown"],
}


CONDITION_GOOD_KEYWORDS = ["unopened", "unused", "good condition", "未拆封", "未使用", "完好", "买错", "拍错", "不想要"]


@dataclass
class ComplaintAnalysis:
    complaint_registration: pd.DataFrame
    category_summary: pd.DataFrame
    good_or_suspected_good_products: pd.DataFrame
    defective_products: pd.DataFrame
    human_review_list: pd.DataFrame


@dataclass
class ComplaintRunResult:
    run_id: str
    report_path: Path
    analysis: ComplaintAnalysis


def _contains_any(text: str, keywords: list[str]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def classify_complaint(text: str, requested_action: str = "") -> tuple[str, str, float]:
    combined = f"{text} {requested_action}".strip()
    if not combined:
        return "Malicious or unclear complaint", "No complaint text was provided.", 0.35

    matched: list[tuple[str, int]] = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in combined.lower())
        if score:
            matched.append((category, score))

    if not matched:
        return "Other", "No rule keyword matched; needs operator judgement.", 0.45

    priority = {
        "Logistics damage": 100,
        "Missing parts": 95,
        "Quality issue": 90,
        "Description mismatch": 85,
        "Installation problem": 80,
        "Usage problem": 75,
        "Delivery delay": 70,
        "Customer mistaken purchase": 65,
        "Return/refund": 60,
        "Malicious or unclear complaint": 50,
    }
    matched.sort(key=lambda item: (item[1], priority.get(item[0], 0)), reverse=True)
    category, score = matched[0]
    reason = f"Matched {score} keyword rule(s) for {category}."
    confidence = min(0.95, 0.55 + score * 0.15)
    return category, reason, confidence


def classify_product_condition(category: str, text: str) -> tuple[str, str]:
    if category == "Malicious or unclear complaint":
        return "Needs human review", "Complaint is unclear or may be malicious."
    if category == "Other":
        return "Needs human review", "No reliable rule matched the complaint."
    if _contains_any(text, CONDITION_GOOD_KEYWORDS):
        return "Good product", "Customer reason indicates the item may be unopened, unused, or bought by mistake."
    if category in {"Usage problem", "Installation problem", "Delivery delay", "Customer mistaken purchase", "Return/refund"}:
        return "Suspected good product", f"{category} does not prove product defect by itself."
    if category in {"Logistics damage", "Missing parts", "Quality issue", "Description mismatch"}:
        return "Defective product", f"{category} can affect resale or requires supplier/logistics review."
    return "Needs human review", "Fallback condition classification."


def _risk_and_action(category: str, condition: str) -> tuple[str, str, str]:
    if condition == "Needs human review":
        return "High", "Manual review required before registering final responsibility or compensation.", "P1"
    if condition == "Defective product":
        return "High", "Register complaint evidence, photos, SKU batch, and supplier/logistics responsibility for manual follow-up.", "P1"
    if condition == "Suspected good product":
        return "Medium", "Register as suspected good product and confirm return condition after warehouse inspection.", "P2"
    if condition == "Good product":
        return "Low", "Register as good product candidate and keep evidence for resale/return handling.", "P3"
    return "Medium", f"Register complaint under {category} and ask operator to confirm next step.", "P2"


def _column_map(df: pd.DataFrame) -> dict[str, str | None]:
    return {
        key: find_column(df, aliases, required=key in {"complaint_text"})
        for key, aliases in COMPLAINT_ALIASES.items()
    }


def classify_complaints_dataframe(df: pd.DataFrame) -> ComplaintAnalysis:
    columns = _column_map(df)
    rows: list[dict[str, object]] = []
    for index, raw in df.iterrows():
        complaint_text = clean_text(raw.get(columns["complaint_text"], ""))  # type: ignore[arg-type]
        requested_action = clean_text(raw.get(columns["requested_action"], "")) if columns["requested_action"] else ""
        category, category_reason, confidence = classify_complaint(complaint_text, requested_action)
        condition, condition_reason = classify_product_condition(category, complaint_text)
        risk, action, priority = _risk_and_action(category, condition)
        sku = clean_text(raw.get(columns["sku"], ""), f"ROW-{index + 1}") if columns["sku"] else f"ROW-{index + 1}"
        product_name = clean_text(raw.get(columns["product_name"], ""), sku) if columns["product_name"] else sku
        rows.append(
            {
                "case_id": clean_text(raw.get(columns["case_id"], ""), f"CASE-{index + 1}") if columns["case_id"] else f"CASE-{index + 1}",
                "order_id": clean_text(raw.get(columns["order_id"], "")) if columns["order_id"] else "",
                "product_name": product_name,
                "sku": sku,
                "complaint_text": complaint_text,
                "requested_action": requested_action,
                "complaint_category": category,
                "product_condition": condition,
                "confidence": round(confidence, 2),
                "data_reason": f"{category_reason} {condition_reason}",
                "risk_level": risk,
                "recommended_action": action,
                "priority_level": priority,
                "requires_human_confirmation": True,
            }
        )

    registration = pd.DataFrame(rows)
    summary = (
        registration.groupby(["complaint_category", "product_condition", "risk_level"], dropna=False)
        .agg(count=("sku", "count"))
        .reset_index()
        .sort_values("count", ascending=False)
    )
    good = registration[registration["product_condition"].isin(["Good product", "Suspected good product"])].copy()
    defective = registration[registration["product_condition"] == "Defective product"].copy()
    review = registration[registration["product_condition"] == "Needs human review"].copy()
    return ComplaintAnalysis(registration, summary, good, defective, review)


class ComplaintAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def run(self, complaint_file: str | Path, output_dir: str | Path | None = None) -> ComplaintRunResult:
        input_path = Path(complaint_file)
        run_id = create_run(self.settings.sqlite_path, "complaints", input_path)
        configure_logging(self.settings, run_id)
        logger.info("Starting complaint registration for %s", input_path)
        try:
            df = read_excel(input_path)
            analysis = classify_complaints_dataframe(df)
            out_dir = Path(output_dir) if output_dir else self.settings.output_dir
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = out_dir / f"complaint_registration_{stamp}.xlsx"
            write_workbook(
                report_path,
                {
                    "complaint_registration": analysis.complaint_registration,
                    "category_summary": analysis.category_summary,
                    "good_suspected_good": analysis.good_or_suspected_good_products,
                    "defective_products": analysis.defective_products,
                    "human_review_list": analysis.human_review_list,
                },
            )
            for row in analysis.complaint_registration.itertuples(index=False):
                log_decision(
                    self.settings.sqlite_path,
                    run_id,
                    "complaint",
                    row.sku,
                    f"{row.complaint_category} / {row.product_condition}",
                    row.data_reason,
                    row.risk_level,
                    row.priority_level,
                )
            log_artifact(self.settings.sqlite_path, run_id, "excel_report", report_path)
            finish_run(self.settings.sqlite_path, run_id, "completed", report_path)
            return ComplaintRunResult(run_id, report_path, analysis)
        except Exception as exc:
            finish_run(self.settings.sqlite_path, run_id, "failed", notes=str(exc))
            logger.exception("Complaint registration failed")
            raise
