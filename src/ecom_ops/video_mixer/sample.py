"""Create local test videos and a sample metrics table for offline smoke tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ecom_ops.video_mixer import media


def _make_video(out: Path, video_source: str, seconds: int, freq: int) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    media.run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            video_source,
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:sample_rate=44100",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(out),
        ]
    )
    return out


def make_sample(video_dir: Path, download_dir: Path) -> list[Path]:
    """Generate 3 short test videos + sample xlsx. Returns video paths."""
    specs = [
        ("red_tv.mp4", "testsrc2=size=720x1280:rate=30", 8, 440),
        ("blue_monitor.mp4", "smptebars=size=720x1280:rate=30", 6, 550),
        ("green_game.mp4", "color=green:size=720x1280:rate=30", 10, 660),
    ]
    paths: list[Path] = []
    for name, video_source, seconds, freq in specs:
        paths.append(_make_video(video_dir / name, video_source, seconds, freq))
    resolved = [p.resolve() for p in paths]
    rows = [
        {
            "商品名称": "显示器A",
            "SKU": "SKU-MON-A",
            "视频链接": resolved[0].as_uri(),
            "GMV": 12800,
            "转化率": 3.2,
            "点击率": 5.1,
            "曝光率": 8.4,
            "3秒转化率": 2.1,
            "3秒点击率": 4.2,
        },
        {
            "商品名称": "显示器B",
            "SKU": "SKU-MON-B",
            "视频链接": resolved[1].as_uri(),
            "GMV": 8600,
            "转化率": 2.4,
            "点击率": 3.8,
            "曝光率": 6.1,
            "3秒转化率": 1.5,
            "3秒点击率": 3.0,
        },
        {
            "商品名称": "游戏外设C",
            "SKU": "SKU-GAME-C",
            "视频链接": resolved[2].as_uri(),
            "GMV": 19200,
            "转化率": 4.1,
            "点击率": 6.4,
            "曝光率": 9.8,
            "3秒转化率": 3.0,
            "3秒点击率": 5.5,
        },
    ]
    table_path = video_dir / "mashup_sample.xlsx"
    pd.DataFrame(rows).to_excel(table_path, index=False)
    return paths
