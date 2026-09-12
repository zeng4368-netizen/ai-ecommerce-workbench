from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from ecom_ops.core.database import connect
from ecom_ops.video_mixer import media
from ecom_ops.video_mixer.downloader import _must_pause
from ecom_ops.video_mixer.evaluation import evaluate_gold_set
from ecom_ops.video_mixer.ingestion import MixerImporter
from ecom_ops.video_mixer.planner import generate_variants
from ecom_ops.video_mixer.repository import MixerRepository
from ecom_ops.video_mixer.scoring import parse_metric, score_table


def test_metric_parser_handles_currency_percent_and_blanks() -> None:
    assert parse_metric("RM 1,234.50") == 1234.5
    assert parse_metric("(RM 20.00)") == -20
    assert parse_metric("12.5%", percent=True) == 0.125
    assert parse_metric(2, percent=True) == 0.02
    assert pd.isna(parse_metric("-"))


def test_missing_metric_weights_are_renormalized() -> None:
    frame = pd.DataFrame({"gmv": ["RM 10", "RM 50", "RM 100"]})
    scored = score_table(
        frame,
        {"gmv": "gmv"},
        {"net_gmv": 0.2, "orders": 0.8},
    )
    assert scored["quality_score"].max() == pytest.approx(100)
    assert scored["quality_score"].min() == pytest.approx(100 / 3)


def test_low_sample_product_never_receives_s_tier() -> None:
    frame = pd.DataFrame(
        {"gmv": list(range(1, 10)), "impressions": [100_000] * 9}
    )
    scored = score_table(
        frame,
        {"gmv": "gmv", "impressions": "impressions"},
        {"net_gmv": 1},
        enforce_sample_tiers=True,
    )
    assert scored["low_sample"].all()
    assert "S" not in set(scored["tier"])


def test_incremental_import_deduplicates_product_video(tmp_path: Path) -> None:
    source = tmp_path / "videos.xlsx"
    rows = [
        {
            "商品 ID": "000123",
            "视频 ID": str(7000 + index),
            "视频链接": f"https://example.com/video/{7000 + index}",
            "联盟视频归因 GMV": f"RM {index * 10}",
            "归因于视频的订单数": index,
            "视频商品曝光次数": 1000 + index,
        }
        for index in range(12)
    ]
    rows.append(rows[-1].copy())
    pd.DataFrame(rows).to_excel(source, index=False)
    repository = MixerRepository(tmp_path / "mixer.sqlite3")
    importer = MixerImporter(repository)
    first = importer.import_file(source)
    second = importer.import_file(source)
    assert first["rows"] == 12
    assert second["rows"] == 12
    assert repository.products()[0]["material_count"] == 12
    assert repository.products()[0]["product_id"] == "000123"
    assert len(repository.product_videos("000123", 30)) == 12


def test_job_lease_recovery_and_timeline_versions(tmp_path: Path) -> None:
    repository = MixerRepository(tmp_path / "mixer.sqlite3")
    job = repository.create_job("test", {"value": 1})
    claimed = repository.claim_job("worker", lease_seconds=30)
    assert claimed and claimed["id"] == job["id"]
    with connect(repository.db_path) as conn:
        conn.execute(
            "UPDATE mixer_jobs SET lease_until=? WHERE id=?",
            ((datetime.now() - timedelta(seconds=2)).isoformat(timespec="seconds"), job["id"]),
        )
    assert repository.recover_expired_jobs() == 1
    assert repository.job(job["id"])["status"] == "queued"

    with connect(repository.db_path) as conn:
        conn.execute(
            """INSERT INTO mixer_products
               (product_id, product_name, material_count, updated_at)
               VALUES ('P1', '', 6, ?)""",
            (datetime.now().isoformat(timespec="seconds"),),
        )
    project = repository.create_project("P1")
    assert repository.save_timeline(project["id"], {"clips": []}, source="ai")["version"] == 1
    assert repository.save_timeline(project["id"], {"clips": []}, source="human")["version"] == 2
    assert repository.latest_timeline(project["id"])["version"] == 2


def _seed_segment_library(tmp_path: Path) -> tuple[MixerRepository, str]:
    repository = MixerRepository(tmp_path / "segments.sqlite3")
    import_id = repository.create_import(tmp_path / "source.xlsx")
    repository.save_scored_video(
        import_id,
        product_id="P1",
        video_id="V1",
        url="",
        metrics={},
        quality_score=92,
        tier="S",
        evidence_confidence=0.9,
        low_sample=False,
        product_name="测试商品",
    )
    repository.finish_import(import_id, status="completed", row_count=1, product_count=1)
    asset_id = repository.save_asset(
        video_id="P1:V1",
        product_id="P1",
        path=tmp_path / "video.mp4",
        source="local",
        sha256="abc",
        duration=10,
        width=1080,
        height=1920,
    )
    repository.save_segments(
        [
            {
                "segment_id": "S1",
                "asset_id": asset_id,
                "video_id": "P1:V1",
                "product_id": "P1",
                "start_seconds": 1.0,
                "end_seconds": 5.0,
                "safe_start_seconds": 1.0,
                "safe_end_seconds": 5.0,
                "stage": "feature_intro",
                "confidence": 0.8,
                "visual_summary": "AI 初始摘要",
                "product_tags": ["installation"],
                "analysis_source": "ai",
            }
        ]
    )
    return repository, asset_id


def test_segment_versions_preserve_human_preference_and_search(tmp_path: Path) -> None:
    repository, asset_id = _seed_segment_library(tmp_path)
    updated = repository.update_segment(
        "S1",
        {
            "start_seconds": 1.4,
            "end_seconds": 4.6,
            "stage": "feature_proof",
            "visual_summary": "人工确认后的功能证明",
            "product_tags": ["rotation"],
        },
    )
    assert updated["active_version"] == 2
    assert updated["human_verified"] == 1
    assert updated["stage_cn"] == "功能证明"
    assert updated["tags"] == ["旋转功能"]

    repository.save_segments(
        [
            {
                "segment_id": "S1",
                "asset_id": asset_id,
                "video_id": "P1:V1",
                "product_id": "P1",
                "start_seconds": 0.5,
                "end_seconds": 5.5,
                "safe_start_seconds": 0.5,
                "safe_end_seconds": 5.5,
                "stage": "feature_intro",
                "confidence": 0.95,
                "visual_summary": "AI 再次分析",
                "product_tags": ["installation"],
                "analysis_source": "ai",
            }
        ]
    )
    preferred = repository.segment("S1")
    assert preferred["start_seconds"] == pytest.approx(1.4)
    assert preferred["stage"] == "feature_proof"
    assert len(
        repository.search_segments(
            "P1", stage="feature_proof", tag="旋转功能", duration_min=3, duration_max=4
        )
    ) == 1


def test_segment_split_and_timeline_usage_are_versioned(tmp_path: Path) -> None:
    repository, _ = _seed_segment_library(tmp_path)
    children = repository.split_segment("S1", 3.0)
    assert len(children) == 2
    assert [row["duration_seconds"] for row in children] == [2.0, 2.0]
    assert all(row["parent_segment_id"] == "S1" for row in children)
    assert repository.segment("S1")["status"] == "superseded"

    project = repository.create_project("P1")
    child = children[0]
    repository.save_timeline(
        project["id"],
        {
            "product_id": "P1",
            "clips": [
                {
                    "segment_id": child["id"],
                    "product_id": "P1",
                    "video_id": child["video_id"],
                    "source_path": child["source_path"],
                    "source_start": child["start_seconds"],
                    "source_end": child["end_seconds"],
                    "stage": child["stage"],
                }
            ],
        },
        source="human",
    )
    usage = repository.segment_usage(child["id"])
    assert len(usage) == 1
    assert usage[0]["project_id"] == project["id"]


def _segments(product_id: str = "P1") -> list[dict]:
    stages = [
        "hook",
        "hook",
        "hook",
        "pain_point",
        "product_reveal",
        "feature_intro",
        "feature_proof",
        "detail",
        "use_case",
        "social_proof",
        "offer",
        "cta",
    ]
    return [
        {
            "segment_id": f"S{index}",
            "product_id": product_id,
            "video_id": f"V{index}",
            "source_path": f"C:/video/{index}.mp4",
            "start_seconds": 0.0,
            "end_seconds": 3.0,
            "stage": stage,
            "confidence": 0.9,
            "video_score": 95 - index,
            "quality_issues": [],
            "visual_summary": stage,
            "transcript": f"Malay line {index}",
        }
        for index, stage in enumerate(stages)
    ]


def test_planner_generates_three_isolated_valid_variants() -> None:
    variants = generate_variants("P1", _segments())
    assert len(variants) == 3
    assert len({tuple(clip["video_id"] for clip in item["clips"]) for item in variants}) == 3
    for timeline in variants:
        assert 20 <= timeline["duration"] <= 35
        assert all(clip["product_id"] == "P1" for clip in timeline["clips"])
        assert sum(clip["stage"] == "cta" for clip in timeline["clips"]) <= 1
        if any(clip["stage"] == "cta" for clip in timeline["clips"]):
            assert timeline["clips"][-1]["stage"] == "cta"


def test_planner_rejects_cross_product_segments() -> None:
    segments = _segments()
    segments[-1]["product_id"] = "P2"
    with pytest.raises(ValueError, match="Cross-product"):
        generate_variants("P1", segments)


def test_cut_segment_retains_audio(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    result = media.run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=blue:size=360x640:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ]
    )
    assert result.returncode == 0
    output = media.cut_segment(source, 0.2, 1.4, tmp_path / "clip.mp4")
    assert media.probe_has_audio(output)
    assert media.probe_duration(output) == pytest.approx(1.2, abs=0.15)


def test_download_pause_detection() -> None:
    assert _must_pause("HTTP Error 429: Too Many Requests")
    assert _must_pause("Login required, captcha")
    assert not _must_pause("temporary connection reset")


def test_gold_evaluator_enforces_dataset_and_quality_thresholds() -> None:
    gold = [
        {
            "segment_id": f"S{index}",
            "product_id": f"P{index % 5}",
            "start_seconds": float(index),
            "end_seconds": float(index + 2),
            "stage": "hook" if index % 2 else "feature_intro",
            "product_tags": ["feature"],
        }
        for index in range(50)
    ]
    metrics = evaluate_gold_set(gold, [dict(item) for item in gold])
    assert metrics["dataset_ready"]
    assert metrics["passed"]
    assert metrics["macro_stage_f1"] == 1
