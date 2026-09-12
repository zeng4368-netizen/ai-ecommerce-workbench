"""Download videos from the table's links, preferring watermark-free streams."""

from __future__ import annotations

import logging
import json
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path
import re

import yt_dlp

from ecom_ops.video_mixer.media import get_ffmpeg
from ecom_ops.video_mixer.media import probe_has_video

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
TIKWM_API = "https://www.tikwm.com/api/"


class DownloadPaused(RuntimeError):
    """A human-verification or platform-throttling condition stopped the job."""


def _must_pause(error: object) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "captcha",
            "two-factor",
            "2fa",
            "login required",
            "sign in",
            "http error 403",
            "http error 429",
            "too many requests",
        )
    )


def _is_local_source(url: str) -> bool:
    return url.startswith("file://") or "://" not in url and Path(url).exists()


def _copy_local(url: str, out_dir: Path) -> Path:
    if url.startswith("file://"):
        parsed = urllib.parse.urlparse(url)
        src = Path(urllib.request.url2pathname(parsed.path))
    else:
        src = Path(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / src.name
    if not target.exists() or target.stat().st_size != src.stat().st_size:
        shutil.copy2(src, target)
    return target


def _use_manual_video(row_key: str, out_dir: Path, manual_dir: Path) -> Path | None:
    """Reuse a user-provided video named <row_key>.<ext> (e.g. from sucps.com)."""
    if not manual_dir.exists():
        return None
    candidates = [p for p in manual_dir.iterdir() if p.is_file() and p.stem == row_key]
    videos = [p for p in candidates if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}]
    if not videos:
        return None
    videos.sort(key=lambda p: p.stat().st_size, reverse=True)
    src = videos[0]
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"manual_{src.name}"
    if not target.exists() or target.stat().st_size != src.stat().st_size:
        shutil.copy2(src, target)
    return target if probe_has_video(target) else None


def _pick_video_file(target_dir: Path) -> Path | None:
    """Choose the file that actually contains video, preferring merged mp4."""
    video_exts = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".ts"}
    audio_exts = {".m4a", ".mp3", ".aac", ".wav", ".ogg", ".opus", ".flac", ".mka"}
    candidates = [p for p in target_dir.glob("*") if p.is_file()]
    videos = [p for p in candidates if p.suffix.lower() in video_exts]
    if videos:
        videos.sort(key=lambda p: p.stat().st_size, reverse=True)
        return videos[0]
    non_audio = [p for p in candidates if p.suffix.lower() not in audio_exts]
    if non_audio:
        non_audio.sort(key=lambda p: p.stat().st_size, reverse=True)
        return non_audio[0]
    return candidates[0] if candidates else None


def _run_download(options: dict, url: str, target_dir: Path) -> Path:
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(url, download=True)
    path = _pick_video_file(target_dir)
    if path is None:
        raise RuntimeError(f"未找到下载文件: {url}")
    return path


def _tikwm_parse(url: str, timeout: float = 30) -> tuple[str | None, list[str]]:
    """Resolve a TikTok URL via the tikwm public API.

    Returns ``(play_url, image_urls)``. ``play_url`` is the watermark-free video
    link; a non-empty ``image_urls`` with no ``play_url`` means a slideshow post.
    """
    api_url = f"{TIKWM_API}?{urllib.parse.urlencode({'url': url})}"
    request = urllib.request.Request(api_url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise RuntimeError(f"tikwm 解析失败: {payload.get('msg', payload)}")
    data = payload.get("data") or {}
    return data.get("play"), data.get("images") or []


def download_tikwm(url: str, out_dir: Path, row_key: str, overwrite: bool = False) -> Path:
    """Download a watermark-free TikTok video via the tikwm API."""
    target_dir = out_dir / _safe_key(row_key)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "tikwm_video.mp4"
    if target.exists() and not overwrite and probe_has_video(target):
        return target
    last_error: Exception | None = None
    play_url: str | None = None
    image_urls: list[str] = []
    for attempt in range(3):
        try:
            play_url, image_urls = _tikwm_parse(url)
            break
        except Exception as exc:  # noqa: BLE001 - transient network issues
            last_error = exc
            time.sleep(2 * (attempt + 1))
    if play_url is None:
        if image_urls:
            raise RuntimeError("下载结果没有视频流（可能是图文帖/纯音频）") from last_error
        raise RuntimeError(f"tikwm 解析失败: {last_error}") from last_error
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                play_url,
                headers={"User-Agent": _UA, "Referer": "https://www.tiktok.com/"},
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                with target.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            break
        except Exception as exc:  # noqa: BLE001 - transient network issues
            last_error = exc
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"tikwm 视频下载失败: {last_error}") from last_error
    if not probe_has_video(target):
        target.unlink(missing_ok=True)
        raise RuntimeError("下载结果没有视频流（可能是图文帖/纯音频）")
    return target


def download_direct(
    url: str, out_dir: Path, row_key: str, overwrite: bool = False
) -> Path:
    """Download a direct mp4 URL (e.g. the CDN URL returned by creatok analyze)."""
    target_dir = out_dir / _safe_key(row_key)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "creatok_video.mp4"
    if target.exists() and not overwrite and probe_has_video(target):
        return target
    try:
        from curl_cffi import requests

        response = requests.get(
            url,
            impersonate="chrome",
            headers={"Referer": "https://www.tiktok.com/"},
            stream=True,
            timeout=180,
        )
        response.raise_for_status()
        try:
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    if chunk:
                        handle.write(chunk)
        finally:
            response.close()
    except ImportError:
        urllib.request.urlretrieve(url, target)  # type: ignore[attr-defined]
    if not probe_has_video(target):
        target.unlink(missing_ok=True)
        raise RuntimeError("直链下载结果没有视频流")
    return target


def download_video(
    url: str,
    out_dir: Path,
    row_key: str,
    overwrite: bool = False,
    cookies_file: str | None = None,
    cookies_from_browser: str | None = None,
    crop_watermark: bool = False,
    watermark_crop: tuple[float, float] = (0.10, 0.10),
    manual_videos_dir: Path | None = None,
    use_tikwm_fallback: bool = False,
) -> tuple[Path, dict]:
    """Download one video. Returns (local path, info)."""
    target_dir = out_dir / _safe_key(row_key)
    target_dir.mkdir(parents=True, exist_ok=True)

    manual = _use_manual_video(row_key, target_dir, manual_videos_dir or out_dir.parent / "manual_videos")
    if manual:
        return manual, {"id": manual.stem, "title": manual.stem, "duration": None, "source": "manual"}

    if _is_local_source(url):
        copied = _copy_local(url, target_dir)
        return copied, {"id": copied.stem, "title": copied.stem, "duration": None, "source": url}

    existing = sorted(target_dir.glob("*"))
    if existing and not overwrite:
        video = _pick_video_file(target_dir)
        if video and probe_has_video(video):
            return video, {"id": video.stem, "title": video.stem, "duration": None, "source": url}

    path_suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if path_suffix in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        try:
            path = download_direct(url, out_dir, row_key, overwrite=overwrite)
            return path, {
                "id": path.stem,
                "title": path.stem,
                "duration": None,
                "source": "authorized_direct",
            }
        except Exception as exc:  # noqa: BLE001
            if _must_pause(exc):
                raise DownloadPaused(str(exc)) from exc
            logger.info("Direct download failed; trying yt-dlp: %s", exc)

    options = {
        "format": "download_addr/bv*+ba/b",
        "outtmpl": str(target_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "ffmpeg_location": get_ffmpeg(),
        "retries": 2,
        "socket_timeout": 30,
    }
    if cookies_file and Path(cookies_file).exists():
        options["cookiefile"] = cookies_file
    if cookies_from_browser:
        options["cookiesfrombrowser"] = (cookies_from_browser, None, None)
    if overwrite:
        options["overwrites"] = True
    path: Path | None = None
    last_error: Exception | None = None
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            path = _run_download(options, url, target_dir)
            if probe_has_video(path):
                break
            if options.get("format") != "b":
                logger.info("未检测到视频流，改用最佳画质: %s", url)
                options["format"] = "b"
            elif attempt >= 1:
                break
        except Exception as exc:  # noqa: BLE001 - retry transient failures
            last_error = exc
            if _must_pause(exc):
                raise DownloadPaused(str(exc)) from exc
            logger.warning("下载尝试 %d/%d 失败: %s", attempt + 1, max_attempts, exc)
            time.sleep(2 * (attempt + 1))
    if path is None or not probe_has_video(path):
        if use_tikwm_fallback and "tiktok.com" in url:
            logger.warning("Using explicitly enabled public-parser fallback for %s", url)
            try:
                path = download_tikwm(url, out_dir, row_key, overwrite=overwrite)
                return path, {
                    "id": path.stem,
                    "title": path.stem,
                    "duration": None,
                    "source": "tikwm_fallback",
                }
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError(f"下载结果没有视频流（可能是图文帖/纯音频）: {url}") from last_error
    if crop_watermark and "tiktok.com" in url:
        path = _crop_tiktok_watermark(path, target_dir, watermark_crop)
    return path, {
        "id": path.stem,
        "title": path.stem,
        "duration": None,
        "source": url,
    }


def tiktok_video_id(url: str) -> str | None:
    """Extract the numeric video id from a TikTok URL."""
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else None


def _crop_tiktok_watermark(
    src: Path, out_dir: Path, fractions: tuple[float, float]
) -> Path:
    """Last-resort watermark removal: crop the bottom-right corner."""
    right, bottom = fractions
    target = out_dir / f"{src.stem}_crop.mp4"
    from ecom_ops.video_mixer.media import run_ffmpeg

    result = run_ffmpeg(
        [
            "-y",
            "-i",
            str(src),
            "-vf",
            f"crop=iw*{1 - right:.2f}:ih*{1 - bottom:.2f}:0:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        logger.warning("水印裁剪失败，保留原文件: %s", result.stderr[-400:])
        return src
    return target


def _safe_key(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    return (cleaned or "video")[:80]
