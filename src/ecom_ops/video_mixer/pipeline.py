"""End-to-end mashup pipeline: table -> download -> score -> label -> mix."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ecom_ops.video_mixer import media
from ecom_ops.video_mixer.config import VideoMixerConfig
from ecom_ops.video_mixer.creatok_bridge import analyze_tiktok
from ecom_ops.video_mixer.downloader import download_video
from ecom_ops.video_mixer.downloader import download_direct
from ecom_ops.video_mixer.mixer import assemble, plan_sequence
from ecom_ops.video_mixer.scoring import score_table
from ecom_ops.video_mixer.segmenter import build_segments
from ecom_ops.video_mixer.table_loader import (
    detect_metric_columns,
    detect_product_column,
    join_ad_metrics,
    load_ad_table,
    load_table,
)

logger = logging.getLogger(__name__)


def _row_key(row: Any, url: str, df_columns: list[str]) -> str:
    for candidate in ("SKU", "sku", "商品名称", "款号", "视频名称", "视频标题"):
        if candidate in df_columns and row.get(candidate):
            return re.sub(r"[^\w\-_.]", "_", str(row[candidate]))[:60]
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else re.sub(r"[^\w\-_.]", "_", url)[-50:]


def _categorize_error(exc: Exception) -> str:
    message = str(exc)
    if "没有视频流" in message or "video stream" in message:
        return "图文帖/纯音频"
    if "IP address is blocked" in message:
        return "IP被封"
    if "Unable to extract" in message or "rehydration" in message:
        return "TikTok提取失败(风控)"
    if "creatok" in message or "quota" in message or "auth" in message:
        return "CreatOK额度/鉴权"
    return "其他"


def run_mashup_pipeline(cfg: VideoMixerConfig) -> dict[str, Any]:
    """Run the full pipeline and return a summary dict."""
    cfg.ensure_dirs()
    df, column_map = load_table(cfg.table_path, cfg.url_column)
    url_column = column_map["url_column"]
    product_column = detect_product_column(df)
    if product_column:
        ids = df[product_column].astype(str).str.strip()
        if cfg.product_id:
            chosen = str(cfg.product_id).strip()
        else:
            chosen = ids.value_counts().idxmax()
            logger.info("未指定商品，自动选择素材最多的商品ID: %s", chosen)
        df = df[ids == chosen]
        logger.info("商品 %s 共 %d 条素材", chosen, len(df))
        if df.empty:
            raise RuntimeError(f"商品ID {chosen} 没有素材，请检查 --product-id。")
    if cfg.ad_table:
        ad_df = load_ad_table(cfg.ad_table)
        df, _ = join_ad_metrics(df, ad_df, url_column)
        column_map = {"url_column": url_column, **detect_metric_columns(df)}
        logger.info("已合并广告表: %d 行 -> %d 列", len(df), len(df.columns))
    scored = score_table(df, column_map, cfg.metric_weights)
    scored = scored.sort_values("quality_score", ascending=False)
    logger.info("表格 %s 共 %d 行, 链接列=%s, 指标映射=%s", cfg.table_path, len(scored), url_column, column_map)

    scan_budget = max(cfg.top_videos * 5, cfg.top_videos)
    candidates = scored.head(scan_budget)
    run_id = f"mashup_{cfg.table_path.stem[:20]}_{media_now()}"
    video_records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        if len(video_records) >= cfg.top_videos:
            break
        url = str(row.get(url_column, "")).strip()
        if not url:
            continue
        key = _row_key(row, url, list(scored.columns))
        try:
            path: Path | None = None
            info: dict[str, Any] = {}
            transcript = None
            vision_scenes = None
            analysis = None
            if cfg.use_creatok_analysis and "tiktok.com" in url:
                analysis = analyze_tiktok(url, cfg.segments_dir / key)
                if analysis:
                    transcript = analysis.get("transcript") or None
                    vision_scenes = analysis.get("vision_scenes") or None
                    download_url = analysis.get("download_url")
                    if download_url:
                        try:
                            path = download_direct(
                                download_url, cfg.download_dir, key, cfg.overwrite
                            )
                            info = {"id": path.stem, "title": path.stem, "duration": None}
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("creatok 直链下载失败，回退 yt-dlp: %s", exc)
            if path is None:
                path, info = download_video(
                    url,
                    cfg.download_dir,
                    key,
                    cfg.overwrite,
                    cookies_file=cfg.cookies_file,
                    cookies_from_browser=cfg.cookies_from_browser,
                    crop_watermark=cfg.crop_watermark,
                    watermark_crop=cfg.watermark_crop,
                    manual_videos_dir=cfg.manual_videos_dir,
                )
            duration = info.get("duration") or media.probe_duration(path)
            if transcript:
                segment_source = transcript
                is_scenes = False
            elif vision_scenes:
                segment_source = vision_scenes
                is_scenes = True
            else:
                segment_source = None
                is_scenes = False
            segments = build_segments(
                path,
                duration,
                transcript=segment_source,
                llm=cfg.llm,
                min_segment=cfg.min_segment,
                max_segment=cfg.max_segment,
                is_scenes=is_scenes,
                label_hints=analysis.get("labeled_sections") if analysis else None,
            )
            seg_path = cfg.segments_dir / key / "segments.json"
            seg_path.parent.mkdir(parents=True, exist_ok=True)
            seg_path.write_text(
                json.dumps(
                    {"video": str(path), "duration": duration, "segments": segments},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            record = {
                "row_key": key,
                "path": path,
                "url": url,
                "quality_score": float(row.get("quality_score", 0.0)),
                "tier": str(row.get("tier", "C")),
                "duration": duration,
                "segments": segments,
            }
            video_records.append(record)
            sources.append(
                {
                    "row_key": key,
                    "url": url,
                    "path": str(path),
                    "quality_score": record["quality_score"],
                    "tier": record["tier"],
                    "segment_count": len(segments),
                    "metrics": {
                        metric: (
                            None
                            if isinstance(column, list)
                            else (None if pd_isna(row.get(column)) else str(row.get(column)))
                        )
                        for metric, column in column_map.items()
                        if metric not in ("url_column",)
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            reason = _categorize_error(exc)
            failures.append(
                {
                    "row_key": key,
                    "url": url,
                    "reason": reason,
                    "error": str(exc)[:300],
                }
            )
            logger.warning("跳过 %s: %s", url, exc)

    failures_path = cfg.output_dir / f"{run_id}_failures.csv"
    if failures:
        pd.DataFrame(failures).to_csv(
            failures_path, index=False, encoding="utf-8-sig"
        )
        logger.info("失败清单: %s (%d 条)", failures_path, len(failures))

    if not video_records:
        raise RuntimeError(
            "没有可用的视频素材：前 %d 条里没有下载到带视频流的视频"
            "（可能是图文帖/被 TikTok 风控）。可尝试提供 --cookies 或增大 --top-videos。"
            % scan_budget
        )

    plan = plan_sequence(video_records, cfg)
    if not plan:
        raise RuntimeError("没有满足评分阈值的优质片段，请调低 --min-score 或检查数据。")

    manifest = assemble(plan, cfg, run_id, sources)
    summary_path = write_summary(cfg, run_id, manifest, video_records)
    scored_path = cfg.output_dir / f"{run_id}_scores.xlsx"
    scored.to_excel(scored_path, index=False)
    return {
        "run_id": run_id,
        "output": manifest["output"],
        "manifest": str(cfg.output_dir / f"{run_id}_manifest.json"),
        "summary": str(summary_path),
        "scores_table": str(scored_path),
        "videos_processed": len(video_records),
        "clips": manifest["clip_count"],
        "failures": str(failures_path) if failures else None,
        "failures_count": len(failures),
    }


def inspect_table(
    table_path: Path,
    url_column: str | None = None,
    ad_table: Path | None = None,
) -> dict[str, Any]:
    """Load a table and report detected columns, metrics, and link stats."""
    df, column_map = load_table(table_path, url_column)
    url_col = column_map["url_column"]
    ad_matched = None
    if ad_table:
        ad_df = load_ad_table(ad_table)
        df, _ = join_ad_metrics(df, ad_df, url_col)
        column_map = {"url_column": url_col, **detect_metric_columns(df)}
        ad_matched = int(df["ad_Gross revenue"].notna().sum())
    links = df[url_col].dropna().astype(str)
    tiktok_share = float(links.str.contains("tiktok.com", case=False).mean()) if len(links) else 0.0
    return {
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "column_map": column_map,
        "ad_matched_rows": ad_matched,
        "links": {
            "non_null": int(links.notna().sum()),
            "tiktok_share": round(tiktok_share, 4),
        },
    }


def media_now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def pd_isna(value: Any) -> bool:
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except Exception:  # noqa: BLE001
        return value is None


def write_summary(
    cfg: VideoMixerConfig,
    run_id: str,
    manifest: dict[str, Any],
    video_records: list[dict[str, Any]],
) -> Path:
    lines = [
        f"# 混剪报告 {run_id}",
        "",
        f"- 输出视频: `{manifest['output']}`",
        f"- 片段数: {manifest['clip_count']}，总时长: {manifest['duration']}s",
        "",
        "## 使用素材",
        "",
        "| 素材 | 评分 | 等级 | 片段数 |",
        "| --- | --- | --- | --- |",
    ]
    for record in sorted(video_records, key=lambda r: r["quality_score"], reverse=True):
        lines.append(
            f"| {record['row_key']} | {record['quality_score']:.1f} | {record['tier']} | "
            f"{len(record['segments'])} |"
        )
    lines += ["", "## 混剪顺序", "", "| # | 素材 | 时间段 | 标签 | 置信度 | 素材评分 |", "| --- | --- | --- | --- | --- | --- |"]
    for index, item in enumerate(manifest["sequence"], start=1):
        lines.append(
            f"| {index} | {item['video_key']} | {item['start']:.1f}-{item['end']:.1f}s | "
            f"{item.get('label_cn', item.get('label', ''))} | {item.get('confidence', 0):.2f} | "
            f"{item['video_score']:.1f} |"
        )
    path = cfg.output_dir / f"{run_id}_summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
