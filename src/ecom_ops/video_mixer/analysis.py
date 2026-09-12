"""Local preprocessing plus structured multimodal analysis."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ecom_ops.core.settings import Settings, get_settings
from ecom_ops.video_mixer import media
from ecom_ops.video_mixer.ai_provider import OpenAIVideoProvider
from ecom_ops.video_mixer.domain import SALES_STAGES
from ecom_ops.video_mixer.repository import MixerRepository
from ecom_ops.video_mixer.segmenter import build_segments


def _scene_ranges(path: Path) -> list[dict[str, Any]]:
    try:
        from scenedetect import ContentDetector, detect

        return [
            {"start": start.get_seconds(), "end": end.get_seconds(), "text": ""}
            for start, end in detect(str(path), ContentDetector())
        ]
    except Exception:
        return []


def _transcript_for_range(
    transcript: list[dict[str, Any]], start: float, end: float
) -> str:
    return " ".join(
        str(item.get("text", "")).strip()
        for item in transcript
        if float(item.get("end", 0)) > start and float(item.get("start", 0)) < end
    ).strip()


def _fallback_analysis(text: str, position: float) -> dict[str, Any]:
    lowered = text.lower()
    if position < 0.12:
        stage = "hook"
    elif any(word in lowered for word in ("beli", "order", "sekarang", "diskaun")):
        stage = "cta"
    elif any(word in lowered for word in ("buka", "kotak", "unbox")):
        stage = "unboxing"
    elif any(word in lowered for word in ("fungsi", "boleh", "feature")):
        stage = "feature_intro"
    else:
        stage = "product_reveal"
    return {
        "visual_summary": "Pending cloud visual analysis",
        "on_screen_text": [],
        "selling_points": [],
        "stage": stage,
        "product_tags": [],
        "quality_issues": ["vision_not_analyzed"],
        "continuity_in": "",
        "continuity_out": "",
        "confidence": 0.45,
    }


class VideoAnalyzer:
    def __init__(
        self,
        repository: MixerRepository | None = None,
        provider: OpenAIVideoProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or MixerRepository(self.settings.sqlite_path)
        self.provider = provider or OpenAIVideoProvider(self.settings, self.repository)

    def analyze_asset(
        self,
        *,
        asset_id: str,
        product_id: str,
        video_id: str,
        source_path: Path,
        metric_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        work_dir = self.settings.processed_dir / "video_mixer" / product_id / video_id
        proxy = media.make_proxy(source_path, work_dir / "proxy.mp4")
        duration = media.probe_duration(proxy)
        transcript: list[dict[str, Any]] = []
        if self.provider.enabled and media.probe_has_audio(proxy):
            audio = media.extract_audio(proxy, work_dir / "audio.mp3")
            transcript = self.provider.transcribe(
                audio, product_id=product_id, video_id=video_id
            )
        scenes = _scene_ranges(proxy)
        boundary_source = scenes or transcript
        candidates = build_segments(
            proxy,
            duration,
            transcript=boundary_source,
            min_segment=1.2,
            max_segment=8.0,
            is_scenes=bool(scenes),
        )
        results: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            start = float(candidate["start"])
            end = float(candidate["end"])
            spoken = _transcript_for_range(transcript, start, end)
            frame_times = [start + 0.05, (start + end) / 2, max(start, end - 0.05)]
            frames = media.extract_keyframes(
                proxy, frame_times, work_dir / "frames" / f"segment_{index:03d}"
            )
            if self.provider.enabled and frames:
                try:
                    analysis = self.provider.analyze_segment(
                        product_id=product_id,
                        video_id=video_id,
                        transcript=spoken,
                        start_seconds=start,
                        end_seconds=end,
                        frames=frames,
                        metric_context=metric_context,
                    )
                except Exception as exc:
                    analysis = _fallback_analysis(spoken, start / max(duration, 0.01))
                    analysis["quality_issues"] = [
                        "structured_analysis_failed",
                        type(exc).__name__,
                    ]
            else:
                analysis = _fallback_analysis(spoken, start / max(duration, 0.01))
            stage = analysis.get("stage", "product_reveal")
            if stage not in SALES_STAGES:
                stage = "product_reveal"
            segment_id = hashlib.sha256(
                f"{asset_id}:{start:.3f}:{end:.3f}".encode("utf-8")
            ).hexdigest()[:32]
            item = {
                "segment_id": segment_id,
                "asset_id": asset_id,
                "product_id": product_id,
                "video_id": video_id,
                "start_seconds": start,
                "end_seconds": end,
                "safe_start_seconds": max(0, start - 0.12),
                "safe_end_seconds": min(duration, end + 0.12),
                "transcript": spoken,
                "evidence_frames": [str(frame) for frame in frames],
                **analysis,
                "stage": stage,
            }
            results.append(item)
        self.repository.save_segments(results)
        return results
