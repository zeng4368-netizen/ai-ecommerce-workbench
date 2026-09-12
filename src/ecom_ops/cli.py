from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from ecom_ops.agents.complaints import ComplaintAgent
from ecom_ops.agents.sales import SalesAgent
from ecom_ops.core.logging import configure_logging
from ecom_ops.core.settings import get_settings
from ecom_ops.services.tiktok_ads import TikTokAdsService
from ecom_ops.services.tiktok_monitor import TikTokMonitorService
from ecom_ops.video_mixer.ingestion import MixerImporter
from ecom_ops.video_mixer.evaluation import evaluate_gold_set, load_jsonl
from ecom_ops.video_mixer.workflow import MixerWorkflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local e-commerce operation agents.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sales = subparsers.add_parser("sales", help="Analyze daily sales Excel.")
    sales.add_argument("file", help="Path to sales Excel file.")

    complaints = subparsers.add_parser("complaints", help="Classify complaint Excel.")
    complaints.add_argument("file", help="Path to complaint Excel file.")

    subparsers.add_parser("tiktok-auth-url", help="Create a TikTok account authorization URL.")

    tiktok_sync = subparsers.add_parser("tiktok-sync", help="Sync connected TikTok metrics once.")
    tiktok_sync.add_argument("--open-id", help="Specific connected TikTok open_id.")

    tiktok_worker = subparsers.add_parser(
        "tiktok-worker", help="Continuously sync all connected TikTok accounts."
    )
    tiktok_worker.add_argument("--interval", type=int, help="Polling interval in seconds (min 60).")

    tiktok_ads_sync = subparsers.add_parser(
        "tiktok-ads-sync", help="Sync read-only TikTok Ads reporting data."
    )
    tiktok_ads_sync.add_argument("--days", type=int, default=30, help="Report window (1-90 days).")

    mixer_import = subparsers.add_parser(
        "mixer-import", help="Import video and optional advertising metric snapshots."
    )
    mixer_import.add_argument("file", help="Video metric Excel/CSV.")
    mixer_import.add_argument("--ad-file", help="Advertising metric Excel/CSV.")

    mixer_worker = subparsers.add_parser(
        "mixer-worker", help="Run persistent mixer jobs with lease recovery."
    )
    mixer_worker.add_argument("--once", action="store_true", help="Process at most one job.")
    mixer_worker.add_argument("--interval", type=int, default=5, help="Idle polling seconds.")

    mixer_evaluate = subparsers.add_parser(
        "mixer-evaluate", help="Evaluate predictions against a human gold JSONL set."
    )
    mixer_evaluate.add_argument("gold", help="Human-labelled gold JSONL.")
    mixer_evaluate.add_argument("predictions", help="Predicted segment JSONL.")

    args = parser.parse_args()
    if args.command == "sales":
        sales_result = SalesAgent().run(args.file)
        print(f"Run: {sales_result.run_id}")
        print(f"Excel: {sales_result.report_path}")
        print(f"Markdown: {sales_result.markdown_path}")
    elif args.command == "complaints":
        complaint_result = ComplaintAgent().run(args.file)
        print(f"Run: {complaint_result.run_id}")
        print(f"Excel: {complaint_result.report_path}")
    elif args.command == "tiktok-auth-url":
        print(TikTokMonitorService().create_authorization_url())
    elif args.command == "tiktok-sync":
        tiktok_summary = TikTokMonitorService().sync(args.open_id)
        print(f"Run: {tiktok_summary.run_id}")
        print(f"Account: {tiktok_summary.open_id}")
        print(f"Videos synced: {tiktok_summary.videos_synced}")
    elif args.command == "tiktok-worker":
        settings = get_settings()
        configure_logging(settings, "tiktok-worker")
        interval = max(60, args.interval or settings.tiktok_sync_interval_seconds)
        service = TikTokMonitorService(settings)
        logging.info("TikTok worker started with %s-second interval", interval)
        try:
            while True:
                try:
                    service.sync_all()
                except Exception:
                    logging.exception("TikTok polling cycle failed")
                time.sleep(interval)
        except KeyboardInterrupt:
            logging.info("TikTok worker stopped")
    elif args.command == "tiktok-ads-sync":
        ads_summary = TikTokAdsService().sync(max(1, min(90, args.days)))
        print(f"Run: {ads_summary.run_id}")
        print(f"Advertiser: {ads_summary.advertiser_id}")
        print(f"Rows synced: {ads_summary.rows_synced}")
        print(f"Range: {ads_summary.start_date} to {ads_summary.end_date}")
    elif args.command == "mixer-import":
        result = MixerImporter().import_file(
            Path(args.file),
            ad_source_path=Path(args.ad_file) if args.ad_file else None,
        )
        print(f"Import: {result['import_id']}")
        print(f"Rows: {result['rows']}")
        print(f"Products: {result['products']}")
    elif args.command == "mixer-worker":
        settings = get_settings()
        configure_logging(settings, "mixer-worker")
        workflow = MixerWorkflow(settings=settings)
        while True:
            try:
                result = workflow.run_next_job()
                if result:
                    logging.info("Mixer job completed: %s", result)
                elif args.once:
                    break
                else:
                    time.sleep(max(1, args.interval))
            except Exception:
                logging.exception("Mixer job failed or paused")
                if args.once:
                    raise
    elif args.command == "mixer-evaluate":
        metrics = evaluate_gold_set(
            load_jsonl(Path(args.gold)),
            load_jsonl(Path(args.predictions)),
        )
        for key, value in metrics.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
