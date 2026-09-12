"""Thin ffmpeg helpers: probe, silence detection, cut, and concat."""

from __future__ import annotations

import re
import subprocess
import hashlib
from pathlib import Path

import imageio_ffmpeg


def get_ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [get_ffmpeg(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def probe_duration(path: Path) -> float:
    """Return video duration in seconds parsed from `ffmpeg -i` output."""
    result = run_ffmpeg(["-i", str(path)])
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", result.stderr or "")
    if not match:
        raise ValueError(f"无法解析视频时长: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def probe_has_video(path: Path) -> bool:
    """Return True when the file contains at least one video stream."""
    result = run_ffmpeg(["-i", str(path)])
    return bool(re.search(r"Stream #.*: Video:", result.stderr or ""))


def probe_has_audio(path: Path) -> bool:
    """Return True when the file contains at least one audio stream."""
    result = run_ffmpeg(["-i", str(path)])
    return bool(re.search(r"Stream #.*: Audio:", result.stderr or ""))


def probe_dimensions(path: Path) -> tuple[int, int]:
    result = run_ffmpeg(["-i", str(path)])
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", result.stderr or "")
    if not match:
        raise ValueError(f"Cannot determine video dimensions: {path}")
    return int(match.group(1)), int(match.group(2))


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def perceptual_hash(path: Path) -> str:
    """Compute a compact dHash from the middle frame for near-duplicate detection."""
    from PIL import Image

    thumb = path.with_suffix(".hash.jpg")
    extract_thumbnail(path, probe_duration(path) / 2, thumb)
    with Image.open(thumb) as image:
        gray = image.convert("L").resize((9, 8))
        pixels = list(gray.getdata())
    bits = []
    for row in range(8):
        offset = row * 9
        bits.extend(pixels[offset + col] > pixels[offset + col + 1] for col in range(8))
    value = sum(int(bit) << index for index, bit in enumerate(bits))
    thumb.unlink(missing_ok=True)
    return f"{value:016x}"


def audio_fingerprint(path: Path) -> str:
    """Hash normalized mono PCM audio; blank denotes a silent/no-audio asset."""
    if not probe_has_audio(path):
        return ""
    pcm = path.with_suffix(".fingerprint.wav")
    result = run_ffmpeg(
        [
            "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
            "-c:a", "pcm_s16le", str(pcm),
        ]
    )
    if result.returncode != 0 or not pcm.exists():
        return ""
    fingerprint = sha256_file(pcm)
    pcm.unlink(missing_ok=True)
    return fingerprint


def make_proxy(src: Path, out: Path, width: int = 540) -> Path:
    """Create a low-bitrate analysis proxy while retaining the source audio."""
    out.parent.mkdir(parents=True, exist_ok=True)
    result = run_ffmpeg(
        [
            "-y", "-i", str(src),
            "-vf", f"scale={width}:-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
            "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out),
        ]
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"Proxy generation failed: {result.stderr[-1200:]}")
    return out


def extract_audio(src: Path, out: Path) -> Path:
    """Extract mono 16 kHz audio for speech recognition."""
    out.parent.mkdir(parents=True, exist_ok=True)
    result = run_ffmpeg(
        ["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "mp3", str(out)]
    )
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-1200:]}")
    return out


def extract_keyframes(src: Path, times: list[float], out_dir: Path) -> list[Path]:
    """Extract deterministic evidence frames for one candidate segment."""
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, at in enumerate(times):
        target = out_dir / f"frame_{index:03d}_{max(0, at):.3f}.jpg"
        result = run_ffmpeg(
            [
                "-y", "-ss", f"{max(0, at):.3f}", "-i", str(src),
                "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", str(target),
            ]
        )
        if result.returncode == 0 and target.exists() and target.stat().st_size:
            outputs.append(target)
    return outputs


def detect_silence(
    path: Path, noise_db: float = -30.0, min_silence: float = 0.5
) -> list[tuple[float, float]]:
    """Return [(start, end)] silent ranges using ffmpeg silencedetect."""
    result = run_ffmpeg(
        [
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f",
            "null",
            "-",
        ]
    )
    starts = re.findall(r"silence_start:\s*([\d.]+)", result.stderr or "")
    ends = re.findall(r"silence_end:\s*([\d.]+)", result.stderr or "")
    pairs: list[tuple[float, float]] = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else None
        pairs.append((float(start), float(end) if end is not None else float(start)))
    return pairs


def speech_ranges(
    path: Path, noise_db: float = -30.0, min_silence: float = 0.5
) -> list[tuple[float, float]]:
    """Invert silence detection into speech segments."""
    duration = probe_duration(path)
    silences = detect_silence(path, noise_db, min_silence)
    if not silences:
        return [(0.0, duration)]
    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in silences:
        if start - cursor >= 0.3:
            ranges.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= 0.3:
        ranges.append((cursor, duration))
    return ranges


def cut_segment(
    src: Path,
    start: float,
    end: float,
    out: Path,
    crf: int = 20,
    fps: int = 30,
    vertical: bool = False,
) -> Path:
    """Cut [start, end) into a normalized MP4 (x264 + aac, always has audio)."""
    duration = max(0.1, end - start)
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src),
    ]
    if probe_has_audio(src):
        args += ["-map", "0:v:0", "-map", "0:a:0?"]
    else:
        args += [
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map", "0:v:0", "-map", "1:a:0",
        ]
    args += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-r",
        str(fps),
    ]
    if vertical:
        args += [
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        ]
    args += [
        "-pix_fmt",
        "yuv420p",
        "-af",
        (
            "loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d=0.04,afade=t=out:st={max(0, duration - 0.04):.3f}:d=0.04"
        ),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    result = run_ffmpeg(args)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"片段切割失败: {out}\n{result.stderr[-1200:]}")
    return out


def concat_clips(clips: list[Path], out: Path) -> Path:
    """Concat normalized clips (identical encode settings) via the concat demuxer."""
    out.parent.mkdir(parents=True, exist_ok=True)
    list_file = out.with_suffix(".concat.txt")
    lines = [f"file '{clip.resolve().as_posix()}'" for clip in clips]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = run_ffmpeg(
        ["-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out)]
    )
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"混剪拼接失败: {out}\n{result.stderr[-1200:]}")
    return out


def extract_thumbnail(src: Path, at: float, out: Path) -> Path:
    """Extract one frame as a jpeg thumbnail for the review board."""
    out.parent.mkdir(parents=True, exist_ok=True)
    result = run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-1",
            str(out),
        ]
    )
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        return out  # return path anyway; caller may show a placeholder
    return out
