"""End-to-end mixer orchestration used by API, worker and Streamlit."""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

from ecom_ops.core.settings import Settings, get_settings
from ecom_ops.video_mixer import media
from ecom_ops.video_mixer.ai_provider import OpenAIVideoProvider
from ecom_ops.video_mixer.analysis import VideoAnalyzer
from ecom_ops.video_mixer.downloader import DownloadPaused, download_video
from ecom_ops.video_mixer.planner import InsufficientMaterialError, generate_variants
from ecom_ops.video_mixer.repository import MixerRepository


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


class MixerWorkflow:
    def __init__(
        self,
        repository: MixerRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or MixerRepository(self.settings.sqlite_path)
        self.provider = OpenAIVideoProvider(self.settings, self.repository)
        self.analyzer = VideoAnalyzer(self.repository, self.provider, self.settings)

    def estimate_analysis_cost(self, product_id: str) -> dict[str, Any]:
        count = min(15, len(self.repository.product_videos(product_id, 30)))
        estimate = round(count * 0.08, 2)
        return {"videos": count, "estimated_cost_usd": estimate}

    def queue_analysis(self, product_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        product = self.repository.product(product_id)
        if not product:
            raise KeyError(product_id)
        if int(product["material_count"]) < 6:
            raise InsufficientMaterialError(
                "This product has fewer than 6 materials and requires a human decision."
            )
        estimate = self.estimate_analysis_cost(product_id)
        projected_cost = self.repository.estimated_cost_today() + estimate["estimated_cost_usd"]
        over_cap = (
            self.settings.mixer_daily_budget > 0
            and projected_cost > self.settings.mixer_daily_budget
        )
        requires_confirmation = over_cap and not confirmed
        return self.repository.create_job(
            "analyze_product",
            {"product_id": product_id, "projected_daily_cost_usd": projected_cost},
            estimated_cost=estimate["estimated_cost_usd"],
            requires_confirmation=requires_confirmation,
        )

    def analyze_product(
        self, product_id: str, heartbeat: Callable[[], None] | None = None
    ) -> dict[str, Any]:
        videos = self.repository.product_videos(product_id, 30)
        if len(videos) < 6:
            raise InsufficientMaterialError("Fewer than 6 product materials are available.")
        output_dir = self.settings.raw_dir / "videos" / product_id
        seen_sha = {item["sha256"] for item in self.repository.product_assets(product_id) if item["sha256"]}
        seen_phash = {
            item["perceptual_hash"]
            for item in self.repository.product_assets(product_id)
            if item["perceptual_hash"]
        }
        seen_audio = {
            item["audio_fingerprint"]
            for item in self.repository.product_assets(product_id)
            if item.get("audio_fingerprint")
        }
        analyzed = 0
        duplicates = 0
        errors: list[dict[str, str]] = []
        all_segments: list[dict[str, Any]] = []
        for video in videos:
            if heartbeat:
                heartbeat()
            if analyzed >= 15:
                break
            try:
                path, info = download_video(
                    video["url"],
                    output_dir,
                    video["video_id"],
                    cookies_file=self.settings.mixer_cookies_file or None,
                    cookies_from_browser=self.settings.mixer_cookies_from_browser or None,
                    manual_videos_dir=self.settings.raw_dir / "manual_videos",
                    use_tikwm_fallback=self.settings.mixer_use_tikwm_fallback,
                )
                checksum = media.sha256_file(path)
                image_hash = media.perceptual_hash(path)
                audio_hash = media.audio_fingerprint(path)
                if (
                    checksum in seen_sha
                    or any(_hamming(image_hash, old) <= 5 for old in seen_phash)
                    or (audio_hash and audio_hash in seen_audio)
                ):
                    duplicates += 1
                    continue
                seen_sha.add(checksum)
                seen_phash.add(image_hash)
                if audio_hash:
                    seen_audio.add(audio_hash)
                width, height = media.probe_dimensions(path)
                asset_id = self.repository.save_asset(
                    video_id=video["video_id"],
                    product_id=product_id,
                    path=path,
                    source=str(info.get("source", video["url"])),
                    sha256=checksum,
                    perceptual_hash=image_hash,
                    audio_fingerprint=audio_hash,
                    duration=media.probe_duration(path),
                    width=width,
                    height=height,
                )
                segments = self.analyzer.analyze_asset(
                    asset_id=asset_id,
                    product_id=product_id,
                    video_id=video["video_id"],
                    source_path=path,
                    metric_context={
                        "quality_score": video["latest_score"],
                        "tier": video["latest_tier"],
                    },
                )
                all_segments.extend(segments)
                analyzed += 1
            except DownloadPaused:
                raise
            except Exception as exc:
                errors.append({"video_id": video["video_id"], "error": str(exc)})
        if analyzed == 0:
            raise RuntimeError("No authorized video could be downloaded and analyzed.")

        current_taxonomy = self.repository.latest_taxonomy(product_id)
        taxonomy = current_taxonomy
        if not current_taxonomy:
            tags = sorted(
                {
                    tag
                    for segment in all_segments
                    for tag in segment.get("product_tags", [])
                    if tag
                }
            )
            taxonomy = self.repository.save_taxonomy(
                product_id,
                {
                    "stage_order": [
                        "hook",
                        "pain_point",
                        "product_reveal",
                        "feature_intro",
                        "feature_proof",
                        "use_case",
                        "offer",
                        "cta",
                    ],
                    "product_tags": tags,
                    "recommended_structure": "hook > product > proof > offer > cta",
                },
                approved=False,
            )
        return {
            "product_id": product_id,
            "downloaded_and_analyzed": analyzed,
            "duplicates": duplicates,
            "segments": len(all_segments),
            "taxonomy": taxonomy,
            "errors": errors,
        }

    def create_projects(
        self,
        product_id: str,
        *,
        target_duration: float = 30,
        language: str = "ms",
        audio_mode: str = "voiceover",
    ) -> list[dict[str, Any]]:
        taxonomy = self.repository.latest_taxonomy(product_id)
        if not taxonomy or taxonomy["status"] != "approved":
            raise ValueError("The first product taxonomy must be approved before mixing.")
        timelines = generate_variants(
            product_id,
            self.repository.product_segments(product_id),
            target_duration=target_duration,
            language=language,
            audio_mode=audio_mode,
        )
        projects = []
        for timeline in timelines:
            if self.provider.enabled:
                timeline["script"] = self.provider.write_malay_script(
                    product_id, timeline["clips"], float(timeline["duration"])
                )
            project = self.repository.create_project(
                product_id,
                target_duration=target_duration,
                language=language,
                audio_mode=audio_mode,
            )
            version = self.repository.save_timeline(project["id"], timeline, source="ai")
            projects.append({**project, "timeline_version": version["version"], "timeline": timeline})
        return projects

    def render_project(
        self, project_id: str, heartbeat: Callable[[], None] | None = None
    ) -> dict[str, Any]:
        project = self.repository.project(project_id)
        version = self.repository.latest_timeline(project_id)
        if not project or not version:
            raise KeyError(project_id)
        timeline = version["timeline"]
        if any(clip["product_id"] != project["product_id"] for clip in timeline["clips"]):
            raise ValueError("Cross-product timeline rejected.")
        render_id = self.repository.create_render(project_id)
        out_dir = self.settings.output_dir / "mashup" / project_id / render_id
        clip_dir = self.settings.processed_dir / "clips" / project_id / render_id
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            clips = []
            for index, clip in enumerate(timeline["clips"]):
                if heartbeat:
                    heartbeat()
                target = clip_dir / f"{index:03d}_{clip['segment_id']}.mp4"
                media.cut_segment(
                    Path(clip["source_path"]),
                    float(clip["source_start"]),
                    float(clip["source_end"]),
                    target,
                    vertical=True,
                )
                clips.append(target)
            original = media.concat_clips(clips, out_dir / "original_audio.mp4")
            subtitle = self._write_srt(timeline, out_dir / "subtitles.srt")
            cover = media.extract_thumbnail(original, 0.2, out_dir / "cover.jpg")
            voiceover_path = ""
            if self.provider.enabled and timeline.get("script"):
                voice = self.provider.synthesize(
                    timeline["script"], out_dir / "voiceover.mp3", product_id=project["product_id"]
                )
                voiceover = out_dir / "voiceover.mp4"
                duration = float(timeline["duration"])
                result = media.run_ffmpeg(
                    [
                        "-y", "-i", str(original), "-i", str(voice),
                        "-filter_complex", "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,apad[a]",
                        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                        "-t", f"{duration:.3f}", "-movflags", "+faststart", str(voiceover),
                    ]
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr[-1200:])
                voiceover_path = str(voiceover)
            manifest = {
                "render_id": render_id,
                "project_id": project_id,
                "product_id": project["product_id"],
                "duration": timeline["duration"],
                "resolution": "1080x1920",
                "timeline_version": version["version"],
                "original_audio": str(original),
                "voiceover": voiceover_path,
                "subtitle": str(subtitle),
                "cover": str(cover),
                "sources": [
                    {
                        "video_id": clip["video_id"],
                        "segment_id": clip["segment_id"],
                        "source_path": clip["source_path"],
                    }
                    for clip in timeline["clips"]
                ],
            }
            manifest_path = out_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (out_dir / "timeline.json").write_text(
                json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.repository.finish_render(
                render_id,
                status="completed",
                original_audio_path=str(original),
                voiceover_path=voiceover_path,
                subtitle_path=str(subtitle),
                cover_path=str(cover),
                manifest_path=str(manifest_path),
            )
            return manifest
        except Exception as exc:
            self.repository.finish_render(render_id, status="failed", error_message=str(exc))
            raise

    def run_next_job(self, worker_id: str = "local-worker") -> dict[str, Any] | None:
        self.repository.recover_expired_jobs()
        job = self.repository.claim_job(worker_id)
        if not job:
            return None
        try:
            if job["job_type"] == "analyze_product":
                result = self.analyze_product(
                    job["payload"]["product_id"],
                    heartbeat=lambda: self.repository.heartbeat(job["id"]),
                )
            elif job["job_type"] == "render_project":
                result = self.render_project(
                    job["payload"]["project_id"],
                    heartbeat=lambda: self.repository.heartbeat(job["id"]),
                )
            else:
                raise ValueError(f"Unsupported job type: {job['job_type']}")
            self.repository.complete_job(job["id"], result)
            return result
        except DownloadPaused as exc:
            self.repository.fail_job(job["id"], str(exc), pause=True)
            raise
        except Exception as exc:
            self.repository.fail_job(job["id"], str(exc))
            raise

    @staticmethod
    def _write_srt(timeline: dict[str, Any], path: Path) -> Path:
        lines = []
        index = 1
        for clip in timeline["clips"]:
            text = str(clip.get("transcript", "")).strip()
            if not text:
                continue
            lines.extend(
                [
                    str(index),
                    f"{_srt_time(float(clip['timeline_start']))} --> "
                    f"{_srt_time(float(clip['timeline_end']))}",
                    text,
                    "",
                ]
            )
            index += 1
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
