from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class Recommendation:
    product_name: str
    sku: str
    data_reason: str
    risk_level: str
    recommended_action: str
    priority_level: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def clean_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    try:
        if math.isnan(value):  # type: ignore[arg-type]
            return default
    except TypeError:
        pass
    text = str(value).strip()
    return text if text and text.lower() != "nan" else default


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 1.0 if current > 0 else 0.0
    return (current - previous) / abs(previous)


def risk_from_score(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 45:
        return "Medium"
    return "Low"


def priority_from_risk(risk_level: str) -> str:
    return {"High": "P1", "Medium": "P2", "Low": "P3"}.get(risk_level, "P3")
