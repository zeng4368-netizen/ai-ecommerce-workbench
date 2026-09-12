"""Select the best segments and assemble the final mashup video."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ecom_ops.video_mixer import media
from ecom_ops.video_mixer.config import VideoMixerConfig
from ecom_ops.video_mixer.labels import LABEL_ORDER, LOGICAL_FLOW
from ecom_ops.video_mixer.llm import chat_completion

logger = logging.getLogger(__name__)


def _llm_plan(pool: list[dict[str, Any]], cfg: VideoMixerConfig) -> list[dict[str, Any]] | None:
    """Let the LLM order the best segments; returns None on failure."""
    candidates = [
        {
            "index": i,
            "video": item["video_key"],
            "label": item.get("label_cn", item.get("label", "")),
            "score": round(item["segment_score"], 3),
            "range": f"{item['start']:.1f}-{item['end']:.1f}s",
        }
        for i, item in enumerate(pool)
    ]
    system = (
        "你是短视频电商混剪导演。根据候选片段的标签、素材评分与时长，挑选并按"
        "「钩子→介绍→展示→演示→画质→诱导下单」的逻辑顺序排列最多 %d 段，总时长不超过 %.0f 秒。"
        "只输出 JSON 数组，元素为候选 index。不要解释。"
    ) % (cfg.top_segments, cfg.target_duration)
    content = chat_completion(
        cfg.llm, system, json.dumps(candidates, ensure_ascii=False), timeout=120
    )
    if not content:
        return None
    try:
        indexes = json.loads(content)
    except json.JSONDecodeError:
        import re

        match = re.search(r"\[.*\]", content, flags=re.DOTALL)
        if not match:
            return None
        try:
            indexes = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    plan: list[dict[str, Any]] = []
    budget = cfg.target_duration
    for raw in indexes:
        if not isinstance(raw, int) or raw < 0 or raw >= len(pool):
            continue
        item = pool[raw]
        length = item["end"] - item["start"]
        if length > budget + 0.01:
            continue
        plan.append(item)
        budget -= length
        if len(plan) >= cfg.top_segments or budget <= cfg.min_segment:
            break
    return plan or None


def _segment_score(segment: dict, video_score: float) -> float:
    priority = LABEL_ORDER.get(segment.get("label"), 99)
    priority_norm = 1.0 - min(priority, 12) / 12.0
    return 0.6 * (video_score / 100.0) + 0.25 * float(segment.get("confidence", 0.0)) + 0.15 * priority_norm


def plan_sequence(
    video_records: list[dict[str, Any]], cfg: VideoMixerConfig
) -> list[dict[str, Any]]:
    """Pick segments in a logical flow from high-quality material."""
    ranked = sorted(video_records, key=lambda r: r.get("quality_score", 0.0), reverse=True)
    qualified = [r for r in ranked if r.get("quality_score", 0.0) >= cfg.min_score]
    pool: list[dict[str, Any]] = []
    for record in qualified or ranked[: cfg.top_videos]:
        video_score = float(record.get("quality_score", 0.0) or 0.0)
        for segment in record.get("segments", []):
            item = {
                "video_key": record["row_key"],
                "video_path": str(record["path"]),
                "video_score": video_score,
                "tier": record.get("tier", "C"),
                **segment,
                "segment_score": _segment_score(segment, video_score),
            }
            pool.append(item)
    pool.sort(key=lambda item: item["segment_score"], reverse=True)

    if cfg.llm.get("enabled"):
        llm_plan = _llm_plan(pool, cfg)
        if llm_plan is not None:
            logger.info("混剪规划(AI): %d 段", len(llm_plan))
            return llm_plan
        logger.info("AI 规划失败，使用规则规划")

    used: set[tuple[str, str]] = set()
    plan: list[dict[str, Any]] = []
    budget = cfg.target_duration

    def take(label: str) -> dict[str, Any] | None:
        for item in pool:
            key = (item["video_key"], item["id"])
            if item.get("label") == label and key not in used:
                length = item["end"] - item["start"]
                if length <= budget + 0.01:
                    used.add(key)
                    return item
        return None

    for label in LOGICAL_FLOW:
        if budget <= cfg.min_segment:
            break
        item = take(label)
        if item:
            plan.append(item)
            budget -= item["end"] - item["start"]

    for item in pool:  # fill remaining budget with the best leftover segments
        if budget <= cfg.min_segment:
            break
        key = (item["video_key"], item["id"])
        if key in used:
            continue
        length = item["end"] - item["start"]
        if length <= budget + 0.01:
            used.add(key)
            plan.append(item)
            budget -= length

    plan = plan[: cfg.top_segments]
    logger.info(
        "混剪规划: %d 段, 总时长 %.1fs, 标签分布 %s",
        len(plan),
        sum(item["end"] - item["start"] for item in plan),
        sorted(set(item.get("label", "") for item in plan)),
    )
    return plan


def assemble(
    plan: list[dict[str, Any]],
    cfg: VideoMixerConfig,
    run_id: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Cut planned segments and concat them into the final mashup."""
    run_dir = cfg.clips_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for index, item in enumerate(plan):
        label = item.get("label", "other")
        clip_name = f"{index + 1:02d}_{item['video_key']}_{label}_{item['id']}.mp4"
        clip = media.cut_segment(
            Path(item["video_path"]),
            item["start"],
            item["end"],
            run_dir / clip_name,
        )
        clips.append(clip)

    output = cfg.output_dir / f"{run_id}_mashup.mp4"
    media.concat_clips(clips, output)
    manifest = {
        "run_id": run_id,
        "output": str(output),
        "clip_count": len(clips),
        "duration": round(sum(item["end"] - item["start"] for item in plan), 3),
        "sources": sources,
        "sequence": plan,
    }
    (cfg.output_dir / f"{run_id}_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
