"""Stable data contracts shared by analysis, planning, API and UI."""

from __future__ import annotations

from typing import Literal, TypedDict


SalesStage = Literal[
    "hook",
    "pain_point",
    "product_reveal",
    "unboxing",
    "feature_intro",
    "feature_proof",
    "detail",
    "use_case",
    "social_proof",
    "offer",
    "cta",
]

SALES_STAGES: tuple[SalesStage, ...] = (
    "hook",
    "pain_point",
    "product_reveal",
    "unboxing",
    "feature_intro",
    "feature_proof",
    "detail",
    "use_case",
    "social_proof",
    "offer",
    "cta",
)

SALES_STAGE_CN: dict[str, str] = {
    "hook": "开头钩子",
    "pain_point": "痛点",
    "product_reveal": "产品亮相",
    "unboxing": "开箱展示",
    "feature_intro": "功能介绍",
    "feature_proof": "功能证明",
    "detail": "细节特写",
    "use_case": "使用场景",
    "social_proof": "社会证明",
    "offer": "优惠信息",
    "cta": "引导下单",
}

SEGMENT_SOURCE_CN: dict[str, str] = {
    "ai": "AI 分析",
    "legacy": "历史数据",
    "human": "人工调整",
    "human_split": "人工分割",
    "codex_multimodal_manual_validation": "Codex 人工智能分析",
}

SEGMENT_STATUS_CN: dict[str, str] = {
    "active": "可使用",
    "superseded": "已被分割",
    "disabled": "已停用",
}


class SegmentAnalysis(TypedDict, total=False):
    segment_id: str
    product_id: str
    video_id: str
    start_seconds: float
    end_seconds: float
    safe_start_seconds: float
    safe_end_seconds: float
    visual_summary: str
    transcript: str
    on_screen_text: list[str]
    selling_points: list[str]
    stage: SalesStage
    product_tags: list[str]
    quality_issues: list[str]
    continuity_in: str
    continuity_out: str
    confidence: float
    evidence_frames: list[str]
    quality_score: float


class TimelineClip(TypedDict, total=False):
    segment_id: str
    product_id: str
    video_id: str
    source_path: str
    source_start: float
    source_end: float
    timeline_start: float
    timeline_end: float
    stage: SalesStage
    label: str
    confidence: float


class Timeline(TypedDict, total=False):
    product_id: str
    duration: float
    aspect_ratio: str
    language: str
    audio_mode: str
    clips: list[TimelineClip]
    script: str
    subtitles: list[dict]
    warnings: list[str]
