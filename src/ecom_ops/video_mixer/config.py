"""Configuration for the automatic video mashup pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ecom_ops.core.settings import get_settings


def _default_metric_weights() -> dict[str, float]:
    return {
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


def _default_llm() -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    return {
        "enabled": bool(api_key),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        "api_key": api_key,
        "model": os.getenv("MIXER_VISION_MODEL", "gpt-5-mini").strip(),
    }


@dataclass
class VideoMixerConfig:
    """Pipeline settings. Paths default to the project data directories."""

    table_path: Path
    ad_table: Path | None = None
    product_id: str | None = None
    url_column: str | None = None
    metric_weights: dict[str, float] = field(default_factory=_default_metric_weights)
    min_score: float = 60.0
    top_videos: int = 10
    top_segments: int = 8
    target_duration: float = 30.0
    min_segment: float = 1.5
    max_segment: float = 12.0
    download_dir: Path = field(
        default_factory=lambda: Path(get_settings().raw_dir) / "videos"
    )
    manual_videos_dir: Path = field(
        default_factory=lambda: Path(get_settings().raw_dir) / "manual_videos"
    )
    segments_dir: Path = field(
        default_factory=lambda: Path(get_settings().processed_dir) / "segments"
    )
    clips_dir: Path = field(
        default_factory=lambda: Path(get_settings().processed_dir) / "clips"
    )
    output_dir: Path = field(
        default_factory=lambda: Path(get_settings().output_dir) / "mashup"
    )
    overwrite: bool = False
    use_creatok_analysis: bool = False
    cookies_file: str | None = None
    cookies_from_browser: str | None = None
    crop_watermark: bool = False
    watermark_crop: tuple[float, float] = (0.10, 0.10)
    llm: dict[str, Any] = field(default_factory=_default_llm)

    def ensure_dirs(self) -> None:
        for path in (self.download_dir, self.segments_dir, self.clips_dir, self.output_dir):
            path.mkdir(parents=True, exist_ok=True)
