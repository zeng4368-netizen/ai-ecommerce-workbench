"""Read video and advertising metric tables without corrupting identifiers."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


URL_HINTS = ("url", "link", "链接", "视频")
METRIC_PATTERNS: list[tuple[str, str]] = [
    ("refund_amount", r"refund|退款"),
    ("gmv_per_mille", r"gmv.{0,8}(?:1000|mille)|千次.{0,5}gmv"),
    ("gmv", r"gmv|gross revenue|revenue|成交金额|销售额"),
    ("roas", r"roas|广告支出回报"),
    ("conversion_rate", r"conversion rate|转化率"),
    ("ctr", r"(?:^|\b)ctr(?:\b|$)|click rate|点击率"),
    ("impression_rate", r"impression rate|曝光率"),
    ("impressions", r"impressions?|曝光(?:量|数)?"),
    ("plays", r"video views?|play count|播放(?:量|数)?"),
    ("clicks", r"clicks?|点击(?:量|数)?"),
    ("completion_rate", r"100%.*view rate|completion|完播率"),
    ("engagement", r"engagement|互动率"),
    ("orders", r"sku orders|orders|订单数"),
]
SECOND_PATTERNS: list[tuple[str, str]] = [
    ("conversion", r"(\d+)\s*(?:秒|s|second).*转化率"),
    ("ctr", r"(\d+)\s*(?:秒|s|second).*点击率"),
    ("watch", r"(\d+)[-\s]*(?:秒|s|second).*(?:view rate|观看率)"),
]


def _looks_like_url(value: object) -> bool:
    return isinstance(value, str) and bool(
        re.match(r"^(https?://|www\.|file://|/|\.\.?/)", value.strip())
    )


def _non_empty_ratio(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.map(_looks_like_url).mean())


def detect_url_column(df: pd.DataFrame, hint: str | None = None) -> str:
    """Find the column holding video links, preferring an explicit hint."""
    if hint:
        for col in df.columns:
            if str(col).strip().lower() == hint.strip().lower():
                return str(col)
    for col in df.columns:
        lowered = str(col).lower()
        if any(token in lowered for token in URL_HINTS) and _non_empty_ratio(df[col]) > 0.3:
            return str(col)
    ratios = {str(col): _non_empty_ratio(df[col]) for col in df.columns}
    if ratios:
        best_col = max(ratios, key=ratios.get)
        if ratios[best_col] > 0.3:
            return best_col
    raise ValueError("Cannot detect the video URL column. Specify it explicitly.")


def detect_metric_columns(df: pd.DataFrame) -> dict[str, str | list[str]]:
    """Map normalized metric names to source column names."""
    mapping: dict[str, str | list[str]] = {}
    for metric, pattern in METRIC_PATTERNS:
        for col in df.columns:
            if re.search(pattern, str(col), flags=re.IGNORECASE):
                mapping[metric] = str(col)
                break

    second_map: dict[str, list[tuple[int, str]]] = {
        "conversion": [],
        "ctr": [],
        "watch": [],
    }
    for col in df.columns:
        for metric, pattern in SECOND_PATTERNS:
            match = re.search(pattern, str(col), flags=re.IGNORECASE)
            if match:
                second_map[metric].append((int(match.group(1)), str(col)))
    for metric, columns in second_map.items():
        if columns:
            columns.sort()
            mapping[f"{metric}_seconds"] = [col for _, col in columns]
    return mapping


def detect_product_column(df: pd.DataFrame, hint: str | None = None) -> str | None:
    """Find the product identifier used to isolate mixer jobs."""
    candidates = [str(c) for c in df.columns]
    if hint:
        for col in candidates:
            if col.strip().lower() == hint.strip().lower():
                return col
    for col in candidates:
        lowered = col.lower().replace(" ", "").replace("_", "")
        if "商品id" in lowered or "productid" in lowered or lowered in {"sku", "skuid"}:
            return col
    return None


def _read_excel_sheets(table_path: Path) -> list[pd.DataFrame]:
    sheets = pd.read_excel(table_path, sheet_name=None, dtype=object)
    return [frame for frame in sheets.values() if not frame.empty]


def load_table(
    table_path: Path, url_column: str | None = None
) -> tuple[pd.DataFrame, dict[str, str | list[str]]]:
    """Load Excel/CSV and return rows plus normalized column mappings."""
    suffix = table_path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        candidates = _read_excel_sheets(table_path)
    elif suffix == ".csv":
        candidates = [pd.read_csv(table_path, dtype=object)]
    else:
        raise ValueError(f"Unsupported table type: {suffix}")
    if not candidates:
        raise ValueError("The metrics table contains no rows.")

    selected: pd.DataFrame | None = None
    resolved_url = ""
    for frame in candidates:
        try:
            resolved_url = detect_url_column(frame, url_column)
            selected = frame
            break
        except ValueError:
            continue
    if selected is None:
        raise ValueError("No worksheet contains a detectable video URL column.")

    metric_map = detect_metric_columns(selected)
    return selected, {"url_column": resolved_url, **metric_map}


def load_ad_table(ad_path: Path) -> pd.DataFrame:
    """Load an ad report while preserving Video ID as an exact string."""
    frames = _read_excel_sheets(ad_path) if ad_path.suffix.lower() != ".csv" else [
        pd.read_csv(ad_path, dtype=object)
    ]
    if not frames:
        raise ValueError("The advertising report contains no rows.")
    df = frames[0]
    video_id_cols = [c for c in df.columns if str(c).strip().lower() == "video id"]
    if not video_id_cols:
        raise ValueError(
            "The advertising report must include Video ID before it can be joined."
        )
    df = df.copy()
    df["video_id"] = df[video_id_cols[0]].map(normalize_identifier)
    return df[~df["video_id"].isin({"", "N/A", "-"})]


def normalize_identifier(value: object) -> str:
    """Return spreadsheet identifiers without float/scientific-notation damage."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def extract_video_id(value: object) -> str:
    """Extract a stable platform video ID, falling back to the URL itself."""
    text = normalize_identifier(value)
    for pattern in (r"/video/(\d+)", r"[?&](?:video_id|item_id)=([^&]+)"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return text


def join_ad_metrics(
    video_df: pd.DataFrame, ad_df: pd.DataFrame, url_column: str
) -> tuple[pd.DataFrame, dict[str, str | list[str]]]:
    """Merge advertising metrics onto video rows by exact platform video ID."""
    sum_hints = ("cost", "orders", "revenue", "gmv", "impressions", "clicks")
    parts: list[pd.Series] = []
    for column in ad_df.columns:
        if column == "video_id":
            continue
        raw = ad_df[column]
        numeric = pd.to_numeric(
            raw.astype(str).str.replace(",", "", regex=False).str.replace("RM", "", regex=False),
            errors="coerce",
        )
        grouped = numeric.groupby(ad_df["video_id"])
        aggregate = grouped.sum() if any(h in str(column).lower() for h in sum_hints) else grouped.mean()
        aggregate.name = f"ad_{column}"
        parts.append(aggregate)
    ad_agg = pd.concat(parts, axis=1).reset_index() if parts else ad_df[["video_id"]].drop_duplicates()

    merged = video_df.copy()
    merged["video_id"] = merged[url_column].map(extract_video_id)
    merged = merged.merge(ad_agg, on="video_id", how="left")
    return merged, detect_metric_columns(merged)
