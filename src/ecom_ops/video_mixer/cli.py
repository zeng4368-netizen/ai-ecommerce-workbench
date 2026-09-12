"""CLI for the video mashup pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ecom_ops.video_mixer.config import VideoMixerConfig
from ecom_ops.video_mixer.pipeline import run_mashup_pipeline
from ecom_ops.core.logging import configure_logging
from ecom_ops.core.settings import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-mixer", description="自动混剪流水线")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="从指标表格生成混剪视频")
    run.add_argument("--table", required=True, help="指标表格路径 (.xlsx/.csv)")
    run.add_argument("--ad-table", help="广告数据表路径，按 Video ID 合并补充指标")
    run.add_argument("--product-id", help="只混剪指定商品ID的素材（默认取素材最多的商品）")
    run.add_argument("--url-column", help="视频链接列名（默认自动识别）")
    run.add_argument("--min-score", type=float, default=60.0, help="优质素材评分阈值 (0-100)")
    run.add_argument("--top-videos", type=int, default=10, help="最多处理多少条视频")
    run.add_argument("--target-duration", type=float, default=30.0, help="混剪目标时长(秒)")
    run.add_argument("--top-segments", type=int, default=8, help="最多保留片段数")
    run.add_argument("--use-creatok", action="store_true", help="对 TikTok 链接启用 creatok AI 分析")
    run.add_argument("--overwrite", action="store_true", help="重新下载/重新生成")
    run.add_argument("--cookies", help="TikTok 登录 cookie 文件路径 (Netscape 格式)")
    run.add_argument(
        "--cookies-from-browser",
        choices=["edge", "chrome", "firefox"],
        help="直接从浏览器读取已登录的 TikTok cookie（无需导出文件）",
    )
    run.add_argument("--crop-watermark", action="store_true", help="最后手段: 裁剪右下角去除水印")

    inspect = subparsers.add_parser("inspect", help="检查指标表格的列映射与数据概况")
    inspect.add_argument("--table", required=True, help="指标表格路径 (.xlsx/.csv)")
    inspect.add_argument("--url-column", help="视频链接列名（默认自动识别）")
    inspect.add_argument("--ad-table", help="广告数据表路径，按 Video ID 合并补充指标")

    subparsers.add_parser("sample", help="生成本地测试表格与测试视频")
    cookies = subparsers.add_parser(
        "cookies-convert",
        help="把浏览器导出的 cookie JSON（如 Cookie-Editor）转换为 yt-dlp 可用的 Netscape 格式",
    )
    cookies.add_argument("--input", required=True, help="cookie JSON 文件路径")
    cookies.add_argument("--output", default="data/raw/tiktok_cookies.txt", help="输出 Netscape cookie 文件路径")
    return parser


def _sample(cfg: VideoMixerConfig) -> None:
    from ecom_ops.video_mixer import media
    from ecom_ops.video_mixer.sample import make_sample

    media.run_ffmpeg(["-version"])
    paths = make_sample(Path("data/raw/sample_videos"), cfg.download_dir)
    print(json.dumps({"sample_videos": [str(p) for p in paths]}, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings())
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "sample":
        cfg = VideoMixerConfig(table_path=Path("data/raw/sample_videos/mashup_sample.xlsx"))
        _sample(cfg)
        return 0
    if args.command == "cookies-convert":
        from ecom_ops.video_mixer.cookie_tools import convert_cookie_file

        count = convert_cookie_file(Path(args.input), Path(args.output))
        print(json.dumps({"converted": count, "output": args.output}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "inspect":
        from ecom_ops.video_mixer.pipeline import inspect_table

        print(
            json.dumps(
                inspect_table(
                    Path(args.table),
                    args.url_column,
                    Path(args.ad_table) if args.ad_table else None,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    cfg = VideoMixerConfig(
        table_path=Path(args.table),
        ad_table=Path(args.ad_table) if args.ad_table else None,
        product_id=args.product_id,
        url_column=args.url_column,
        min_score=args.min_score,
        top_videos=args.top_videos,
        target_duration=args.target_duration,
        top_segments=args.top_segments,
        use_creatok_analysis=args.use_creatok,
        overwrite=args.overwrite,
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
        crop_watermark=args.crop_watermark,
    )
    summary = run_mashup_pipeline(cfg)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
