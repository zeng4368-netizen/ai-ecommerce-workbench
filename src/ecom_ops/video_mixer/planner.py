"""Constraint-first beam planner for coherent ecommerce mashups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ecom_ops.video_mixer.domain import SALES_STAGES, Timeline


class InsufficientMaterialError(ValueError):
    pass


STAGE_INDEX = {stage: index for index, stage in enumerate(SALES_STAGES)}
PRODUCT_VISIBLE = {
    "product_reveal",
    "unboxing",
    "feature_intro",
    "feature_proof",
    "detail",
    "use_case",
}


@dataclass(frozen=True)
class _State:
    score: float
    duration: float
    ids: tuple[str, ...]


def _duration(segment: dict[str, Any]) -> float:
    return float(segment["end_seconds"]) - float(segment["start_seconds"])


def _quality(segment: dict[str, Any]) -> float:
    video = float(segment.get("video_score", segment.get("quality_score", 50))) / 100
    confidence = float(segment.get("confidence", 0))
    issues = len(segment.get("quality_issues", []))
    return 0.62 * video + 0.38 * confidence - 0.08 * issues


def _transition(previous: dict[str, Any], current: dict[str, Any]) -> float:
    previous_stage = STAGE_INDEX.get(previous.get("stage", "detail"), 6)
    current_stage = STAGE_INDEX.get(current.get("stage", "detail"), 6)
    order = 0.18 if current_stage >= previous_stage else -0.22
    diversity = 0.10 if previous.get("video_id") != current.get("video_id") else -0.04
    continuity = 0.0
    if previous.get("continuity_out") and previous.get("continuity_out") == current.get("continuity_in"):
        continuity = 0.08
    return order + diversity + continuity


def _to_timeline(
    product_id: str,
    selected: list[dict[str, Any]],
    *,
    language: str,
    audio_mode: str,
    warnings: list[str] | None = None,
) -> Timeline:
    cursor = 0.0
    clips = []
    script_parts = []
    for item in selected:
        length = _duration(item)
        clips.append(
            {
                "segment_id": item["segment_id"],
                "product_id": product_id,
                "video_id": item["video_id"],
                "source_path": item["source_path"],
                "source_start": float(item["start_seconds"]),
                "source_end": float(item["end_seconds"]),
                "timeline_start": cursor,
                "timeline_end": cursor + length,
                "stage": item["stage"],
                "label": item.get("visual_summary", ""),
                "confidence": float(item.get("confidence", 0)),
                "transcript": item.get("transcript", ""),
            }
        )
        if item.get("transcript"):
            script_parts.append(str(item["transcript"]))
        cursor += length
    return {
        "product_id": product_id,
        "duration": round(cursor, 3),
        "aspect_ratio": "9:16",
        "language": language,
        "audio_mode": audio_mode,
        "clips": clips,
        "script": " ".join(script_parts),
        "subtitles": [],
        "warnings": warnings or [],
    }


def _beam_plan(
    candidates: list[dict[str, Any]],
    *,
    hook_id: str | None,
    min_duration: float,
    max_duration: float,
    target_duration: float,
    beam_width: int = 80,
) -> list[dict[str, Any]] | None:
    by_id = {item["segment_id"]: item for item in candidates}
    non_cta = [item for item in candidates if item.get("stage") != "cta"]
    ctas = sorted(
        [item for item in candidates if item.get("stage") == "cta"],
        key=_quality,
        reverse=True,
    )
    seeds = [by_id[hook_id]] if hook_id and hook_id in by_id else non_cta[:3]
    states = [
        _State(score=_quality(seed), duration=_duration(seed), ids=(seed["segment_id"],))
        for seed in seeds
        if _duration(seed) <= max_duration
    ]
    for _ in range(min(14, len(non_cta))):
        expanded = list(states)
        for state in states:
            previous = by_id[state.ids[-1]]
            for item in non_cta:
                segment_id = item["segment_id"]
                length = _duration(item)
                if segment_id in state.ids or state.duration + length > max_duration:
                    continue
                expanded.append(
                    _State(
                        score=state.score + _quality(item) + _transition(previous, item),
                        duration=state.duration + length,
                        ids=state.ids + (segment_id,),
                    )
                )
        dedup: dict[tuple[str, ...], _State] = {}
        for state in expanded:
            dedup[state.ids] = max(state, dedup.get(state.ids, state), key=lambda x: x.score)
        states = sorted(
            dedup.values(),
            key=lambda state: state.score + min(state.duration, min_duration) * 0.04,
            reverse=True,
        )[:beam_width]

    finals: list[tuple[float, list[dict[str, Any]]]] = []
    for state in states:
        selected = [by_id[item_id] for item_id in state.ids]
        duration = state.duration
        cta = next(
            (
                item
                for item in ctas
                if item["segment_id"] not in state.ids
                and duration + _duration(item) <= max_duration
            ),
            None,
        )
        if cta:
            selected.append(cta)
            duration += _duration(cta)
        if duration < min_duration:
            continue
        if not any(item.get("stage") in PRODUCT_VISIBLE for item in selected):
            continue
        finals.append((state.score - abs(duration - target_duration) * 0.025, selected))
    return max(finals, key=lambda item: item[0])[1] if finals else None


def generate_variants(
    product_id: str,
    segments: list[dict[str, Any]],
    *,
    count: int = 3,
    min_duration: float = 20,
    max_duration: float = 35,
    target_duration: float = 30,
    language: str = "ms",
    audio_mode: str = "voiceover",
) -> list[Timeline]:
    """Generate distinct, product-isolated timelines under deterministic constraints."""
    if len(segments) < 6:
        raise InsufficientMaterialError("At least 6 analyzed segments are required.")
    if any(str(item.get("product_id")) != str(product_id) for item in segments):
        raise ValueError("Cross-product segments are forbidden.")
    candidates = [
        item
        for item in segments
        if float(item.get("confidence", 0)) >= 0.55
        and 1.2 <= _duration(item) <= 8.0
    ]
    if len(candidates) < 6:
        raise InsufficientMaterialError("Fewer than 6 segments have safe AI boundaries.")
    candidates.sort(key=_quality, reverse=True)
    hooks = [item["segment_id"] for item in candidates if item.get("stage") == "hook"]
    hooks.extend(item["segment_id"] for item in candidates if item["segment_id"] not in hooks)

    variants: list[Timeline] = []
    source_orders: set[tuple[str, ...]] = set()
    for hook_id in hooks:
        selected = _beam_plan(
            candidates,
            hook_id=hook_id,
            min_duration=min_duration,
            max_duration=max_duration,
            target_duration=target_duration,
        )
        if not selected:
            continue
        source_order = tuple(item["video_id"] for item in selected)
        if source_order in source_orders:
            continue
        source_orders.add(source_order)
        variants.append(
            _to_timeline(
                product_id,
                selected,
                language=language,
                audio_mode=audio_mode,
            )
        )
        if len(variants) >= count:
            break
    if len(variants) < count:
        raise InsufficientMaterialError(
            f"Only {len(variants)} distinct valid timelines could be generated."
        )
    return variants
