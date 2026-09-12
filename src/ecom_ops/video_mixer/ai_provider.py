"""Provider adapter for timestamped transcription, vision analysis and TTS."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from ecom_ops.core.settings import Settings, get_settings
from ecom_ops.video_mixer.domain import SALES_STAGES
from ecom_ops.video_mixer.repository import MixerRepository


PROMPT_VERSION = "segment-analysis-v1"
SEGMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "visual_summary": {"type": "string"},
        "on_screen_text": {"type": "array", "items": {"type": "string"}},
        "selling_points": {"type": "array", "items": {"type": "string"}},
        "stage": {"type": "string", "enum": list(SALES_STAGES)},
        "product_tags": {"type": "array", "items": {"type": "string"}},
        "quality_issues": {"type": "array", "items": {"type": "string"}},
        "continuity_in": {"type": "string"},
        "continuity_out": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "visual_summary",
        "on_screen_text",
        "selling_points",
        "stage",
        "product_tags",
        "quality_issues",
        "continuity_in",
        "continuity_out",
        "confidence",
    ],
}


def _hash_payload(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _image_data(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


class OpenAIVideoProvider:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: MixerRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.openai_api_key)

    @property
    def client(self) -> Any:
        if not self.enabled:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )
        return self._client

    def transcribe(
        self, audio_path: Path, *, product_id: str, video_id: str
    ) -> list[dict[str, Any]]:
        with audio_path.open("rb") as audio:
            result = self.client.audio.transcriptions.create(
                model=self.settings.mixer_transcription_model,
                file=audio,
                language="ms",
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        segments = [
            {
                "start": float(item.get("start", 0)),
                "end": float(item.get("end", 0)),
                "text": str(item.get("text", "")).strip(),
            }
            for item in payload.get("segments", [])
        ]
        self._trace(
            product_id=product_id,
            video_id=video_id,
            operation="transcription",
            model=self.settings.mixer_transcription_model,
            request={"audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest()},
            response={"segments": segments},
        )
        return segments

    def analyze_segment(
        self,
        *,
        product_id: str,
        video_id: str,
        transcript: str,
        start_seconds: float,
        end_seconds: float,
        frames: list[Path],
        metric_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_payload = {
            "product_id": product_id,
            "video_id": video_id,
            "range": [start_seconds, end_seconds],
            "transcript": transcript,
            "metric_context": metric_context or {},
            "frame_hashes": [hashlib.sha256(path.read_bytes()).hexdigest() for path in frames],
        }
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    "Analyze this Malaysian ecommerce video segment. Use Malay speech, "
                    "visible text and all evidence frames. Describe only supported facts. "
                    f"Transcript: {transcript or '[no speech]'}\n"
                    f"Business metrics: {json.dumps(metric_context or {}, default=str)}"
                ),
            }
        ]
        content.extend({"type": "input_image", "image_url": _image_data(path)} for path in frames)
        result = self.client.responses.create(
            model=self.settings.mixer_vision_model,
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "segment_analysis",
                    "schema": SEGMENT_SCHEMA,
                    "strict": True,
                }
            },
        )
        parsed = json.loads(result.output_text)
        self._trace(
            product_id=product_id,
            video_id=video_id,
            operation="segment_analysis",
            model=self.settings.mixer_vision_model,
            request=request_payload,
            response=parsed,
        )
        return parsed

    def synthesize(self, text: str, out: Path, *, product_id: str) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        with self.client.audio.speech.with_streaming_response.create(
            model=self.settings.mixer_tts_model,
            voice=self.settings.mixer_tts_voice,
            input=text,
            response_format="mp3",
        ) as response:
            response.stream_to_file(out)
        self._trace(
            product_id=product_id,
            operation="tts",
            model=self.settings.mixer_tts_model,
            request={"text": text, "voice": self.settings.mixer_tts_voice},
            response={"path": str(out)},
        )
        return out

    def write_malay_script(
        self, product_id: str, clips: list[dict[str, Any]], target_duration: float
    ) -> str:
        request = {
            "product_id": product_id,
            "target_duration": target_duration,
            "clips": [
                {
                    "stage": clip.get("stage"),
                    "transcript": clip.get("transcript", ""),
                    "label": clip.get("label", ""),
                }
                for clip in clips
            ],
        }
        result = self.client.responses.create(
            model=self.settings.mixer_vision_model,
            input=(
                "Tulis skrip iklan e-dagang Bahasa Melayu yang lancar untuk garis masa "
                f"{target_duration:.0f} saat ini. Kekalkan fakta yang disokong oleh klip, "
                "mulakan dengan hook, dan gunakan hanya satu CTA di hujung. "
                f"Data klip: {json.dumps(request['clips'], ensure_ascii=False)}"
            ),
        )
        script = result.output_text.strip()
        self._trace(
            product_id=product_id,
            operation="script",
            model=self.settings.mixer_vision_model,
            request=request,
            response={"script": script},
        )
        return script

    def submit_responses_batch(
        self,
        *,
        product_id: str,
        request_bodies: list[dict[str, Any]],
        output_dir: Path,
    ) -> dict[str, Any]:
        """Submit prepared Responses requests to the 24-hour Batch API."""
        output_dir.mkdir(parents=True, exist_ok=True)
        batch_file = output_dir / f"{product_id}_responses_batch.jsonl"
        lines = [
            json.dumps(
                {
                    "custom_id": f"{product_id}-{index:06d}",
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": body,
                },
                ensure_ascii=False,
            )
            for index, body in enumerate(request_bodies)
        ]
        batch_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with batch_file.open("rb") as handle:
            uploaded = self.client.files.create(file=handle, purpose="batch")
        batch = self.client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={"product_id": product_id, "workflow": "video_mixer"},
        )
        payload = batch.model_dump() if hasattr(batch, "model_dump") else dict(batch)
        self._trace(
            product_id=product_id,
            operation="batch_submit",
            model=self.settings.mixer_vision_model,
            request={"request_count": len(request_bodies), "path": str(batch_file)},
            response=payload,
        )
        return payload

    def batch_status(self, batch_id: str) -> dict[str, Any]:
        batch = self.client.batches.retrieve(batch_id)
        return batch.model_dump() if hasattr(batch, "model_dump") else dict(batch)

    def _trace(
        self,
        *,
        product_id: str,
        operation: str,
        model: str,
        request: dict[str, Any],
        response: dict[str, Any],
        video_id: str = "",
    ) -> None:
        if self.repository:
            self.repository.save_ai_trace(
                product_id=product_id,
                video_id=video_id,
                operation=operation,
                model=model,
                prompt_version=PROMPT_VERSION,
                input_hash=_hash_payload(request),
                request=request,
                response=response,
            )
