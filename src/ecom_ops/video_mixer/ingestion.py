"""Incremental Excel/CSV ingestion for large video metric histories."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from ecom_ops.video_mixer.config import _default_metric_weights
from ecom_ops.video_mixer.repository import MixerRepository
from ecom_ops.video_mixer.scoring import parse_metric, score_table
from ecom_ops.video_mixer.table_loader import (
    detect_metric_columns,
    detect_product_column,
    extract_video_id,
    join_ad_metrics,
    load_ad_table,
    load_table,
    normalize_identifier,
)


def _find_column(df: pd.DataFrame, patterns: tuple[str, ...]) -> str | None:
    normalized = [(str(column), str(column).lower().replace(" ", "")) for column in df.columns]
    for pattern in patterns:
        needle = pattern.lower().replace(" ", "")
        for original, lowered in normalized:
            if needle in lowered:
                return original
    return None


def _json_value(value: object) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class MixerImporter:
    def __init__(self, repository: MixerRepository | None = None) -> None:
        self.repository = repository or MixerRepository()

    def import_file(
        self,
        source_path: Path,
        *,
        ad_source_path: Path | None = None,
        url_column: str | None = None,
        product_column: str | None = None,
    ) -> dict[str, Any]:
        source_path = Path(source_path)
        import_id = self.repository.create_import(source_path, ad_source_path)
        try:
            df, mapping = load_table(source_path, url_column)
            url_col = str(mapping["url_column"])
            product_col = detect_product_column(df, product_column)
            if not product_col:
                raise ValueError("Cannot detect Product ID. Specify product_column.")

            df = df.copy()
            df["_product_id"] = df[product_col].map(normalize_identifier)
            explicit_video_col = _find_column(df, ("视频 id", "video id"))
            if explicit_video_col:
                df["_video_id"] = df[explicit_video_col].map(normalize_identifier)
            else:
                df["_video_id"] = df[url_col].map(extract_video_id)
            df["_url"] = df[url_col].map(normalize_identifier)
            df = df[
                (df["_product_id"] != "")
                & (df["_video_id"] != "")
                & (df["_url"].str.match(r"^(?:https?://|file://|/|[A-Za-z]:\\)", na=False))
            ].copy()
            df = df.drop_duplicates(subset=["_product_id", "_video_id"], keep="last")

            ad_joined = False
            if ad_source_path:
                ad_df = load_ad_table(Path(ad_source_path))
                ad_df = ad_df.copy()
                revenue_col = _find_column(ad_df, ("gross revenue", "gmv"))
                cost_col = _find_column(ad_df, ("cost", "spend"))
                if revenue_col and cost_col:
                    revenue = ad_df[revenue_col].map(parse_metric)
                    cost = ad_df[cost_col].map(parse_metric)
                    ad_df["ROAS"] = revenue / cost.replace(0, math.nan)
                df, _ = join_ad_metrics(df, ad_df, url_col)
                ad_joined = True

            mapping = {"url_column": url_col, **detect_metric_columns(df)}
            product_name_col = _find_column(df, ("商品名称", "product name"))
            title_col = _find_column(df, ("视频标题", "video title"))
            creator_col = _find_column(df, ("达人名称", "tiktok account", "creator"))

            records: list[dict[str, Any]] = []
            for product_id, group in df.groupby("_product_id", sort=False):
                scored = score_table(
                    group,
                    mapping,
                    _default_metric_weights(),
                    enforce_sample_tiers=True,
                )
                for _, row in scored.iterrows():
                    excluded = {"quality_score", "tier", "risk_penalty", "low_sample"}
                    metrics = {
                        str(key): _json_value(value)
                        for key, value in row.items()
                        if key not in excluded and not str(key).startswith("_")
                    }
                    records.append(
                        {
                            "product_id": str(product_id),
                            "video_id": str(row["_video_id"]),
                            "url": str(row["_url"]),
                            "metrics": metrics,
                            "quality_score": float(row["quality_score"]),
                            "tier": str(row["tier"]),
                            "evidence_confidence": float(row["evidence_confidence"]),
                            "low_sample": bool(row["low_sample"]),
                            "product_name": (
                                normalize_identifier(row[product_name_col])
                                if product_name_col
                                else ""
                            ),
                            "title": normalize_identifier(row[title_col]) if title_col else "",
                            "creator_name": (
                                normalize_identifier(row[creator_col]) if creator_col else ""
                            ),
                        }
                    )
            self.repository.save_scored_videos(import_id, records)
            persisted = len(records)
            self.repository.refresh_product_counts()
            product_count = int(df["_product_id"].nunique())
            self.repository.finish_import(
                import_id,
                status="completed",
                row_count=persisted,
                product_count=product_count,
            )
            return {
                "import_id": import_id,
                "status": "completed",
                "rows": persisted,
                "products": product_count,
                "ad_joined": ad_joined,
                "metric_columns": mapping,
            }
        except Exception as exc:
            self.repository.finish_import(import_id, status="failed", error_message=str(exc))
            raise
