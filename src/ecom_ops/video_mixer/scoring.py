"""Product-local material scoring with robust commerce metric parsing."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

import numpy as np
import pandas as pd


DEFAULT_WEIGHTS = {
    "net_gmv": 0.20,
    "orders": 0.10,
    "gmv_per_mille": 0.15,
    "ctr": 0.10,
    "ad_efficiency": 0.15,
    "watch_rates": 0.10,
    "completion_rate": 0.10,
    "engagement": 0.05,
    "evidence_confidence": 0.05,
}


def parse_metric(value: object, *, percent: bool = False) -> float:
    """Parse currency, percentage, comma-separated and blank spreadsheet values."""
    if value is None or pd.isna(value):
        return math.nan
    if isinstance(value, (int, float, np.number)):
        number = float(value)
        return number / 100.0 if percent and abs(number) >= 1 else number
    text = str(value).strip()
    if not text or text.lower() in {"-", "--", "n/a", "na", "none", "null"}:
        return math.nan
    negative = text.startswith("(") and text.endswith(")")
    had_percent = "%" in text
    cleaned = re.sub(r"(?i)\b(?:rm|myr|usd|sgd|cny|rmb)\b", "", text)
    cleaned = cleaned.replace(",", "").replace("%", "").strip(" ()")
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", cleaned)
    if not match:
        return math.nan
    number = float(match.group(0))
    if negative:
        number = -abs(number)
    if had_percent or (percent and abs(number) >= 1):
        number /= 100.0
    return number


def metric_series(series: pd.Series, *, percent: bool = False) -> pd.Series:
    return series.map(lambda value: parse_metric(value, percent=percent)).astype(float)


def _empty(index: pd.Index) -> pd.Series:
    return pd.Series(math.nan, index=index, dtype=float)


def _column(
    df: pd.DataFrame,
    column_map: Mapping[str, str | list[str]],
    metric: str,
    *,
    percent: bool = False,
) -> pd.Series:
    column = column_map.get(metric)
    if not isinstance(column, str) or column not in df:
        return _empty(df.index)
    return metric_series(df[column], percent=percent)


def _combined_columns(
    df: pd.DataFrame,
    column_map: Mapping[str, str | list[str]],
    metric: str,
    *,
    percent: bool = True,
) -> pd.Series:
    columns = column_map.get(metric)
    if not isinstance(columns, list):
        return _empty(df.index)
    available = [metric_series(df[col], percent=percent) for col in columns if col in df]
    return pd.concat(available, axis=1).mean(axis=1) if available else _empty(df.index)


def _percentile_rank(series: pd.Series, *, log_scale: bool = False) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if log_scale:
        numeric = np.log1p(numeric.clip(lower=0))
    if numeric.notna().sum() == 0:
        return _empty(series.index)
    return numeric.rank(pct=True, method="average")


def _smoothed_rate(
    numerator: pd.Series,
    denominator: pd.Series,
    fallback_rate: pd.Series,
    *,
    prior_strength: float,
) -> pd.Series:
    if denominator.notna().sum() == 0:
        return fallback_rate
    raw = numerator / denominator.replace(0, math.nan)
    observed = raw.where(raw.notna(), fallback_rate)
    valid = observed[(observed >= 0) & np.isfinite(observed)]
    prior = float(valid.median()) if not valid.empty else 0.0
    count = denominator.fillna(0).clip(lower=0)
    successes = numerator.where(numerator.notna(), observed * count).fillna(0).clip(lower=0)
    return (successes + prior * prior_strength) / (count + prior_strength)


def _available(component: pd.Series) -> bool:
    return bool(component.notna().any())


def score_table(
    df: pd.DataFrame,
    column_map: Mapping[str, str | list[str]],
    weights: Mapping[str, float] | None = None,
    *,
    enforce_sample_tiers: bool = False,
) -> pd.DataFrame:
    """Score rows within one product and normalize weights for missing metrics."""
    out = df.copy()
    selected_weights = dict(weights or DEFAULT_WEIGHTS)

    gmv = _column(out, column_map, "gmv")
    refunds = _column(out, column_map, "refund_amount").fillna(0)
    net_gmv = gmv - refunds
    orders = _column(out, column_map, "orders")
    impressions = _column(out, column_map, "impressions")
    plays = _column(out, column_map, "plays")
    clicks = _column(out, column_map, "clicks")
    raw_ctr = _column(out, column_map, "ctr", percent=True)
    raw_conversion = _column(out, column_map, "conversion_rate", percent=True)
    roas = _column(out, column_map, "roas")
    gmv_per_mille = _column(out, column_map, "gmv_per_mille")
    if not _available(gmv_per_mille) and _available(gmv) and _available(impressions):
        gmv_per_mille = gmv / impressions.replace(0, math.nan) * 1000

    exposure = impressions.where(impressions.notna(), plays)
    smoothed_ctr = _smoothed_rate(clicks, exposure, raw_ctr, prior_strength=500)
    smoothed_conversion = _smoothed_rate(orders, clicks, raw_conversion, prior_strength=50)
    ad_efficiency_raw = pd.concat(
        [_percentile_rank(smoothed_conversion), _percentile_rank(roas, log_scale=True)],
        axis=1,
    ).mean(axis=1)
    watch = pd.concat(
        [
            _combined_columns(out, column_map, "watch_seconds"),
            _combined_columns(out, column_map, "conversion_seconds"),
        ],
        axis=1,
    ).mean(axis=1)
    completion = _column(out, column_map, "completion_rate", percent=True)
    engagement = _column(out, column_map, "engagement", percent=True)
    confidence = 1 - np.exp(-exposure.fillna(0).clip(lower=0) / 1000.0)

    components: dict[str, pd.Series] = {
        "net_gmv": _percentile_rank(net_gmv, log_scale=True),
        "orders": _percentile_rank(orders, log_scale=True),
        "gmv_per_mille": _percentile_rank(gmv_per_mille, log_scale=True),
        "ctr": _percentile_rank(smoothed_ctr),
        "ad_efficiency": ad_efficiency_raw,
        "watch_rates": _percentile_rank(watch),
        "completion_rate": _percentile_rank(completion),
        "engagement": _percentile_rank(engagement),
        "evidence_confidence": confidence,
        "gmv": _percentile_rank(gmv, log_scale=True),
        "conversion_rate": _percentile_rank(smoothed_conversion),
        "ctr_seconds": _percentile_rank(_combined_columns(out, column_map, "ctr_seconds")),
    }

    weighted: list[pd.Series] = []
    active_weight = 0.0
    for metric, weight in selected_weights.items():
        component = components.get(metric)
        if component is None or weight <= 0 or not _available(component):
            continue
        out[f"pct_{metric}"] = component
        weighted.append(component.fillna(0) * float(weight))
        active_weight += float(weight)
    if active_weight:
        out["quality_score"] = (
            pd.concat(weighted, axis=1).sum(axis=1) / active_weight * 100
        ).clip(0, 100)
    else:
        out["quality_score"] = 50.0

    refund_risk = (refunds / gmv.replace(0, math.nan)).fillna(0).clip(0, 1)
    out["risk_penalty"] = refund_risk * 20
    out["quality_score"] = (out["quality_score"] - out["risk_penalty"]).clip(0, 100)
    out["evidence_confidence"] = confidence.clip(0, 1)
    out["low_sample"] = len(out) < 10

    if enforce_sample_tiers:
        ranks = out["quality_score"].rank(ascending=False, method="first")
        percent = ranks / max(len(out), 1)
        out["tier"] = "C"
        out.loc[percent <= 0.50, "tier"] = "B"
        out.loc[percent <= 0.20, "tier"] = "A"
        eligible_s = (len(out) >= 10) & (out["evidence_confidence"] >= 0.7)
        out.loc[(percent <= 0.05) & eligible_s, "tier"] = "S"
    else:
        out["tier"] = pd.cut(
            out["quality_score"],
            bins=[-1, 55, 70, 85, 101],
            labels=["C", "B", "A", "S"],
        ).astype(str)
    return out
