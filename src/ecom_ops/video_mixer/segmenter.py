"""Segment a video and label each segment with a script-analysis label."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ecom_ops.video_mixer import media
from ecom_ops.video_mixer.labels import (
    KEYWORD_HINTS,
    LABEL_CN,
    LABEL_IDS,
    SEGMENT_LABELS,
)
from ecom_ops.video_mixer.llm import chat_completion

logger = logging.getLogger(__name__)


def _merge_ranges(
    ranges: list[tuple[float, float]], min_gap: float = 0.3
) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(ranges):
        if start < 0:
            start = 0.0
        if end <= start:
            continue
        gap = start - merged[-1][1] if merged else None
        if gap is not None and 0 < gap <= min_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _boundaries(
    duration: float,
    transcript: list[dict] | None,
    video_path: Path,
    min_segment: float,
    max_segment: float,
    is_scenes: bool = False,
) -> list[tuple[float, float]]:
    if transcript:
        ranges = [
            (max(0.0, seg.get("start", 0.0)), min(duration, seg.get("end", 0.0) or seg.get("start", 0.0)))
            for seg in transcript
        ]
        merged = _merge_ranges(
            [(s, e) for s, e in ranges if e > s],
            min_gap=-1.0 if is_scenes else 0.3,
        )
        if merged:
            return merged
    try:
        speech = _merge_ranges(media.speech_ranges(video_path))
        if speech:
            return speech
    except Exception as exc:  # noqa: BLE001
        logger.info("静音检测失败，使用固定分块: %s", exc)
    chunk = 4.0
    return [(i * chunk, min(duration, (i + 1) * chunk)) for i in range(int(duration / chunk) + 1)]


def _split_long_ranges(
    ranges: list[tuple[float, float]], max_segment: float
) -> list[tuple[float, float]]:
    """Split ranges longer than ``max_segment`` into evenly sized chunks."""
    split: list[tuple[float, float]] = []
    for start, end in ranges:
        length = end - start
        if length <= max_segment:
            split.append((start, end))
            continue
        count = int(length / max_segment) + 1
        step = length / count
        for i in range(count):
            chunk_start = start + i * step
            chunk_end = chunk_start + step if i < count - 1 else end
            split.append((chunk_start, chunk_end))
    return split


def _heuristic_label(text: str, position: float) -> tuple[str, float]:
    """Label by keywords first, then by position. Returns (label, confidence)."""
    lowered = (text or "").lower()
    for label, keywords in KEYWORD_HINTS:
        if any(keyword in lowered for keyword in keywords):
            return label, 0.7
    if position < 0.12:
        return "hook", 0.45
    if position > 0.85:
        return "cta", 0.45
    return "showcase", 0.3


def _llm_label_segments(
    llm: dict[str, Any], segments: list[dict], taxonomy: list[tuple[str, str, int]]
) -> list[str] | None:
    labels_desc = ", ".join(f"{label_id}({cn})" for label_id, cn, _ in taxonomy)
    system = (
        "你是短视频电商运营专家，负责把视频脚本片段归类。"
        f"可选标签: {labels_desc}。只输出 JSON 数组，每个元素是片段的标签 id。"
    )
    user = json.dumps(
        [
            {
                "index": i,
                "time_range": f"{seg['start']:.1f}-{seg['end']:.1f}",
                "text": seg.get("text", ""),
            }
            for i, seg in enumerate(segments)
        ],
        ensure_ascii=False,
    )
    content = chat_completion(llm, system, user)
    if not content:
        return None
    try:
        labels = json.loads(content)
    except json.JSONDecodeError:
        import re

        match = re.search(r"\[.*\]", content, flags=re.DOTALL)
        if not match:
            return None
        try:
            labels = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(labels, list):
        return None
    return [label if label in LABEL_IDS else "other" for label in labels]


def build_segments(
    video_path: Path,
    duration: float,
    transcript: list[dict] | None = None,
    llm: dict[str, Any] | None = None,
    min_segment: float = 1.5,
    max_segment: float = 12.0,
    is_scenes: bool = False,
    label_hints: list[dict] | None = None,
) -> list[dict]:
    """Build and label segments for one video."""
    raw = _boundaries(duration, transcript, video_path, min_segment, max_segment, is_scenes)
    effective_min = 0.4 if is_scenes else min_segment
    raw = _split_long_ranges(raw, max_segment)
    raw = [
        (start, end)
        for start, end in raw
        if (end - start) >= effective_min and (end - start) <= max_segment + 0.05
    ]
    segments = [
        {
            "id": f"seg{i:03d}",
            "start": round(start, 3),
            "end": round(end, 3),
            "text": transcript[i]["text"] if transcript and i < len(transcript) else "",
            "label": "",
            "label_cn": "",
            "confidence": 0.0,
        }
        for i, (start, end) in enumerate(raw)
    ]
    if not segments:
        return segments
    if llm and llm.get("enabled"):
        labels = _llm_label_segments(llm, segments, SEGMENT_LABELS)
        if labels:
            for seg, label in zip(segments, labels, strict=False):
                seg["label"] = label
                seg["label_cn"] = LABEL_CN.get(label, "其他")
                seg["confidence"] = 0.85
    for i, seg in enumerate(segments):
        if not seg["label"]:
            label, confidence = _heuristic_label(seg.get("text", ""), seg["start"] / max(duration, 0.01))
            seg["label"] = label
            seg["label_cn"] = LABEL_CN.get(label, "其他")
            seg["confidence"] = confidence
        if label_hints:
            midpoint = (seg["start"] + seg["end"]) / 2
            for hint in label_hints:
                if hint["start"] <= midpoint < hint["end"]:
                    seg["label"] = hint["label"]
                    seg["label_cn"] = LABEL_CN.get(hint["label"], "其他")
                    seg["confidence"] = 0.9
                    break
    return segments
