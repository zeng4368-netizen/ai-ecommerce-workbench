"""Unit tests for the video mashup pipeline (pure logic, no network)."""

from __future__ import annotations

import json

import pandas as pd

from ecom_ops.video_mixer.labels import LABEL_CN
from ecom_ops.video_mixer.downloader import tiktok_video_id
from ecom_ops.video_mixer.creatok_bridge import (
    _parse_labeled_sections,
    _parse_transcript,
    _parse_vision_scenes,
)
from ecom_ops.video_mixer.scoring import score_table
from ecom_ops.video_mixer.segmenter import _merge_ranges, build_segments
from ecom_ops.video_mixer.pipeline import _categorize_error
from ecom_ops.video_mixer.table_loader import (
    detect_metric_columns,
    detect_product_column,
    detect_url_column,
)


def test_detect_url_column() -> None:
    df = pd.DataFrame(
        {
            "商品名称": ["显示器", "键盘"],
            "视频链接": [
                "https://www.tiktok.com/@x/video/123",
                "file:///d:/tmp/a.mp4",
            ],
        }
    )
    assert detect_url_column(df) == "视频链接"


def test_detect_metric_columns() -> None:
    df = pd.DataFrame(
        columns=[
            "GMV",
            "转化率",
            "点击率",
            "曝光率",
            "3秒转化率",
            "3秒点击率",
        ]
    )
    mapping = detect_metric_columns(df)
    assert mapping["gmv"] == "GMV"
    assert mapping["conversion_rate"] == "转化率"
    assert mapping["ctr"] == "点击率"
    assert mapping["impression_rate"] == "曝光率"
    assert mapping["conversion_seconds"] == ["3秒转化率"]
    assert mapping["ctr_seconds"] == ["3秒点击率"]


def test_score_table_ranks_and_tiers() -> None:
    df = pd.DataFrame(
        {
            "SKU": ["A", "B", "C"],
            "GMV": [100, 200, 300],
            "转化率": [1.0, 2.0, 3.0],
        }
    )
    mapping = {"gmv": "GMV", "conversion_rate": "转化率", "url_column": "SKU"}
    weights = {"gmv": 0.5, "conversion_rate": 0.5}
    scored = score_table(df, mapping, weights)
    assert list(scored.sort_values("quality_score", ascending=False)["SKU"]) == ["C", "B", "A"]
    assert scored.loc[scored["SKU"] == "C", "tier"].iloc[0] == "S"


def test_merge_ranges() -> None:
    assert _merge_ranges([(0.0, 1.0), (1.1, 2.0), (5.0, 6.0)]) == [(0.0, 2.0), (5.0, 6.0)]


def test_split_long_ranges() -> None:
    from ecom_ops.video_mixer.segmenter import _split_long_ranges

    split = _split_long_ranges([(0.0, 20.0), (20.0, 30.0)], max_segment=8.0)
    assert all(end - start <= 8.0 + 1e-6 for start, end in split)
    assert abs(sum(end - start for start, end in split) - 30.0) < 1e-6
    assert len(split) >= 4


def test_build_segments_uses_transcript_and_labels() -> None:
    segments = build_segments(
        "unused.mp4",
        duration=20.0,
        transcript=[
            {"start": 0.0, "end": 3.0, "text": "先别划走"},
            {"start": 5.0, "end": 9.0, "text": "这是一款4K显示器"},
            {"start": 12.0, "end": 16.0, "text": "现在下单立减"},
        ],
    )
    assert len(segments) == 3
    assert segments[0]["label"] == "hook"
    assert segments[1]["label"] == "resolution"
    assert segments[2]["label"] == "cta"
    assert LABEL_CN[segments[2]["label"]] == "诱导下单/结尾CTA"


def test_build_segments_empty_transcript_raises_nothing() -> None:
    segments = build_segments(
        "unused.mp4", duration=0.5, transcript=[{"start": 0.0, "end": 0.2, "text": "x"}]
    )
    assert isinstance(segments, list)


def test_tiktok_video_id() -> None:
    assert (
        tiktok_video_id("https://www.tiktok.com/@user/video/6718335390845095173")
        == "6718335390845095173"
    )
    assert tiktok_video_id("https://example.com/x") is None


def test_creatok_parsers_handle_nested_structures() -> None:
    envelope = {
        "data": {
            "transcript": {"segments": [{"start": 3, "end": 5, "content": "la la la"}]},
            "vision": {
                "scenes": [
                    {
                        "start": 0,
                        "end": 1,
                        "title": "hook",
                        "visual_desc": "product shown",
                    }
                ]
            },
        }
    }
    assert _parse_transcript(envelope)[0]["text"] == "la la la"
    assert len(_parse_vision_scenes(envelope)) == 1


def test_creatok_parse_labeled_sections() -> None:
    envelope = {
        "data": {
            "response": {
                "content": (
                    "#### **Hook** (0.0s - 1.7s)\n"
                    "#### **Product Demo** (1.7s - 2.7s)\n"
                    "#### **Value Proposition** (2.7s - 5.7s)"
                )
            }
        }
    }
    sections = _parse_labeled_sections(envelope)
    assert [(s["label"], s["start"], s["end"]) for s in sections] == [
        ("hook", 0.0, 1.7),
        ("demo", 1.7, 2.7),
        ("intro", 2.7, 5.7),
    ]


def test_build_segments_keeps_touching_scenes_separate() -> None:
    scenes = [
        {"start": 0.0, "end": 1.0, "text": "scene a"},
        {"start": 1.0, "end": 2.0, "text": "scene b"},
        {"start": 2.0, "end": 3.0, "text": "scene c"},
    ]
    segments = build_segments("unused.mp4", 3.0, transcript=scenes, is_scenes=True)
    assert len(segments) == 3
    assert segments[0]["end"] == 1.0


def test_build_segments_applies_label_hints() -> None:
    scenes = [
        {"start": 0.0, "end": 1.0, "text": "scene a"},
        {"start": 1.0, "end": 2.0, "text": "scene b"},
    ]
    hints = [{"label": "cta", "start": 1.0, "end": 2.0}]
    segments = build_segments(
        "unused.mp4", 2.0, transcript=scenes, is_scenes=True, label_hints=hints
    )
    assert segments[0]["label"] == "hook"
    assert segments[1]["label"] == "cta"


def test_categorize_error_reasons() -> None:
    assert _categorize_error(RuntimeError("下载结果没有视频流")) == "图文帖/纯音频"
    assert _categorize_error(RuntimeError("Your IP address is blocked from accessing this post")) == "IP被封"
    assert _categorize_error(RuntimeError("Unable to extract universal data for rehydration")) == "TikTok提取失败(风控)"
    assert _categorize_error(RuntimeError("unknown problem")) == "其他"


def test_detect_product_column() -> None:
    df = pd.DataFrame({"商品 ID": ["1", "2"], "链接": ["a", "b"]})
    assert detect_product_column(df) == "商品 ID"


def test_cookies_json_to_netscape(tmp_path) -> None:
    from ecom_ops.video_mixer.cookie_tools import cookies_json_to_netscape

    payload = json.dumps(
        [
            {
                "domain": ".tiktok.com",
                "hostOnly": False,
                "httpOnly": True,
                "name": "sessionid",
                "path": "/",
                "secure": True,
                "session": False,
                "expirationDate": 1893456000,
                "value": "abc123",
            },
            {
                "domain": "127.0.0.1",
                "hostOnly": True,
                "name": "local",
                "path": "/",
                "secure": False,
                "session": True,
                "value": "x",
            },
        ]
    )
    output = tmp_path / "cookies.txt"
    count = cookies_json_to_netscape(payload, output)
    assert count == 2
    text = output.read_text(encoding="utf-8")
    assert ".tiktok.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tabc123" in text
    assert "127.0.0.1\tFALSE\t/\tFALSE\t0\tlocal\tx" in text
