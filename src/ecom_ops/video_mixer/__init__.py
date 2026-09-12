"""Automatic video mashup pipeline for e-commerce operations.

Reads a metrics table (video links + conversion/CTR/impression/GMV columns),
downloads watermark-free videos, scores material quality, labels segments by
AI script analysis, and assembles a logical mashup from the best segments.
"""

from ecom_ops.video_mixer.config import VideoMixerConfig
from ecom_ops.video_mixer.pipeline import run_mashup_pipeline

__all__ = ["VideoMixerConfig", "run_mashup_pipeline"]
