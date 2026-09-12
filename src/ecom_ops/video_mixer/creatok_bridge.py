"""Optional enrichment: use the creatok CLI to analyze a TikTok video URL."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_transcript(data: dict) -> list[dict]:
    """Best-effort extraction of timestamped transcript segments."""
    payload = data.get("data", data)
    for key in ("transcript", "transcript_segments", "segments", "captions"):
        raw = payload.get(key)
        if isinstance(raw, dict):
            raw = raw.get("segments")
        if isinstance(raw, list):
            segments: list[dict] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("content") or ""
                start = item.get("start") or item.get("start_time") or item.get("from")
                end = item.get("end") or item.get("end_time") or item.get("to")
                if text:
                    segments.append(
                        {
                            "start": float(start) if start is not None else 0.0,
                            "end": float(end) if end is not None else 0.0,
                            "text": str(text),
                        }
                    )
            if segments:
                if any(seg["start"] > 1000 or seg["end"] > 1000 for seg in segments):
                    for seg in segments:
                        seg["start"] /= 1000.0
                        seg["end"] /= 1000.0
                return segments
    return []


def _parse_vision_scenes(data: dict) -> list[dict]:
    payload = data.get("data", data)
    raw = payload.get("vision") or {}
    scenes = raw.get("scenes") if isinstance(raw, dict) else None
    if not isinstance(scenes, list):
        return []
    out: list[dict] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        start = scene.get("start")
        end = scene.get("end")
        text = " ".join(
            str(scene.get(k) or "")
            for k in ("title", "shot_type", "visual_desc", "sound_desc")
        ).strip()
        if text and start is not None and end is not None:
            out.append({"start": float(start), "end": float(end), "text": text})
    return out


def _parse_download_url(data: dict) -> str | None:
    payload = data.get("data", data)
    return payload.get("video", {}).get("download_url") if isinstance(payload.get("video"), dict) else None


def _parse_labeled_sections(data: dict) -> list[dict]:
    """Parse the AI response's section labels + time ranges (Hook/CTA/etc.)."""
    payload = data.get("data", data)
    content = payload.get("response", {}).get("content") or ""
    if not isinstance(content, str):
        return []
    label_map = {
        "hook": "hook",
        "intro": "intro",
        "demo": "demo",
        "product": "showcase",
        "value": "intro",
        "proposition": "intro",
        "social": "social",
        "proof": "social",
        "emotional": "social",
        "cta": "cta",
        "outro": "cta",
        "call": "cta",
        "resolution": "resolution",
        "color": "color",
        "gaming": "gaming",
        "movie": "movie",
        "detail": "detail",
    }
    sections: list[dict] = []
    pattern = re.compile(
        r"\*{1,2}([^\n*]+?)\*{1,2}\s*\((\d+(?:\.\d+)?)s\s*-\s*(\d+(?:\.\d+)?)s\)"
    )
    for match in pattern.finditer(content):
        raw_label = match.group(1).strip().lower()
        start = float(match.group(2))
        end = float(match.group(3))
        if end <= start:
            continue
        label = "other"
        for key, value in label_map.items():
            if key in raw_label:
                label = value
                break
        sections.append({"label": label, "start": start, "end": end})
    return sections


def analyze_tiktok(url: str, out_dir: Path, timeout: int = 180) -> dict | None:
    """Run `creatok analyze` and return {transcript, raw} or None on failure."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "result.json"
    if result_path.exists():
        try:
            cached = json.loads(result_path.read_text(encoding="utf-8"))
            parsed = _from_result(cached)
            if parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    creatok_bin = shutil.which("creatok")
    if not creatok_bin:
        logger.info("creatok CLI 不可用，跳过 AI 视频分析")
        return None
    if not os.getenv("CREATOK_API_KEY"):
        logger.info("CREATOK_API_KEY 未设置，跳过 AI 视频分析")
        return None
    try:
        invocation = (
            ["cmd", "/c", "creatok", "analyze", "--url", url, "--out", str(out_dir)]
            if creatok_bin.lower().endswith((".cmd", ".bat"))
            else [creatok_bin, "analyze", "--url", url, "--out", str(out_dir)]
        )
        result = subprocess.run(
            invocation,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("creatok analyze 运行失败: %s", exc)
        return None
    data: dict = {}
    if result_path.exists():
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    if not data and result.stdout:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            data = {}
    if not data:
        logger.warning("creatok analyze 无返回数据 (exit=%s)", result.returncode)
        return None
    return _from_result(data)


def _from_result(data: dict) -> dict:
    return {
        "transcript": _parse_transcript(data),
        "vision_scenes": _parse_vision_scenes(data),
        "labeled_sections": _parse_labeled_sections(data),
        "download_url": _parse_download_url(data),
        "raw": data,
    }
