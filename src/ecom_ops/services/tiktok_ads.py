from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from ecom_ops.core.database import connect, init_db
from ecom_ops.core.settings import Settings, get_settings
from ecom_ops.integrations.tiktok_business import TikTokBusinessClient


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _number(value: Any) -> float:
    if value in (None, "", "-"):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class AdsSyncSummary:
    run_id: str
    advertiser_id: str
    rows_synced: int
    start_date: str
    end_date: str


class TikTokAdsRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        init_db(db_path)

    def begin_sync(self, advertiser_id: str) -> str:
        run_id = uuid4().hex
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tiktok_ad_sync_runs (id, advertiser_id, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (run_id, advertiser_id, _iso()),
            )
        return run_id

    def finish_sync(self, run_id: str, status: str, rows_synced: int, error: str = "") -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE tiktok_ad_sync_runs
                SET status = ?, ended_at = ?, rows_synced = ?, error_message = ?
                WHERE id = ?
                """,
                (status, _iso(), rows_synced, error[:1000], run_id),
            )

    def save_row(
        self,
        advertiser_id: str,
        data_level: str,
        row: dict[str, Any],
        collected_at: str,
    ) -> None:
        dimensions = row.get("dimensions", {}) or {}
        metrics = row.get("metrics", {}) or {}
        stat_date = str(dimensions.get("stat_time_day") or date.today().isoformat())[:10]
        entity_id = str(
            dimensions.get("campaign_id")
            or dimensions.get("advertiser_id")
            or advertiser_id
        )
        entity_name = str(metrics.get("campaign_name") or metrics.get("advertiser_name") or "")
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tiktok_ad_reports (
                    advertiser_id, stat_date, data_level, entity_id, entity_name,
                    spend, impressions, clicks, ctr, cpc, conversions,
                    cost_per_conversion, video_play_actions, video_watched_2s,
                    video_watched_6s, video_views_p100, purchases, purchase_roas,
                    raw_metrics, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(advertiser_id, stat_date, data_level, entity_id) DO UPDATE SET
                    entity_name = excluded.entity_name,
                    spend = excluded.spend,
                    impressions = excluded.impressions,
                    clicks = excluded.clicks,
                    ctr = excluded.ctr,
                    cpc = excluded.cpc,
                    conversions = excluded.conversions,
                    cost_per_conversion = excluded.cost_per_conversion,
                    video_play_actions = excluded.video_play_actions,
                    video_watched_2s = excluded.video_watched_2s,
                    video_watched_6s = excluded.video_watched_6s,
                    video_views_p100 = excluded.video_views_p100,
                    purchases = excluded.purchases,
                    purchase_roas = excluded.purchase_roas,
                    raw_metrics = excluded.raw_metrics,
                    collected_at = excluded.collected_at
                """,
                (
                    advertiser_id,
                    stat_date,
                    data_level,
                    entity_id,
                    entity_name,
                    _number(metrics.get("spend")),
                    int(_number(metrics.get("impressions"))),
                    int(_number(metrics.get("clicks"))),
                    _number(metrics.get("ctr")),
                    _number(metrics.get("cpc")),
                    _number(metrics.get("conversion")),
                    _number(metrics.get("cost_per_conversion")),
                    int(_number(metrics.get("video_play_actions"))),
                    int(_number(metrics.get("video_watched_2s"))),
                    int(_number(metrics.get("video_watched_6s"))),
                    int(_number(metrics.get("video_views_p100"))),
                    _number(metrics.get("onsite_total_purchase")),
                    _number(metrics.get("onsite_purchases_roas")),
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                    collected_at,
                ),
            )

    def overview(self, advertiser_id: str, days: int = 30) -> dict[str, Any]:
        since = (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(spend), 0) AS spend,
                       COALESCE(SUM(impressions), 0) AS impressions,
                       COALESCE(SUM(clicks), 0) AS clicks,
                       COALESCE(SUM(conversions), 0) AS conversions,
                       COALESCE(SUM(purchases), 0) AS purchases,
                       COALESCE(SUM(purchase_roas * spend), 0) AS roas_value,
                       MAX(collected_at) AS last_synced_at
                FROM tiktok_ad_reports
                WHERE advertiser_id = ? AND data_level = 'AUCTION_ADVERTISER'
                  AND stat_date >= ?
                """,
                (advertiser_id, since),
            ).fetchone()
        result = dict(row)
        spend = float(result["spend"] or 0)
        impressions = int(result["impressions"] or 0)
        clicks = int(result["clicks"] or 0)
        conversions = float(result["conversions"] or 0)
        result["ctr"] = 100 * clicks / impressions if impressions else 0
        result["cpc"] = spend / clicks if clicks else 0
        result["cost_per_conversion"] = spend / conversions if conversions else 0
        result["purchase_roas"] = float(result.pop("roas_value") or 0) / spend if spend else 0
        return result

    def trend(self, advertiser_id: str, days: int = 30) -> list[dict[str, Any]]:
        since = (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT stat_date, spend, impressions, clicks, conversions, purchases,
                       purchase_roas
                FROM tiktok_ad_reports
                WHERE advertiser_id = ? AND data_level = 'AUCTION_ADVERTISER'
                  AND stat_date >= ?
                ORDER BY stat_date
                """,
                (advertiser_id, since),
            ).fetchall()
        return [dict(row) for row in rows]

    def campaigns(self, advertiser_id: str, days: int = 30) -> list[dict[str, Any]]:
        since = (date.today() - timedelta(days=max(days - 1, 0))).isoformat()
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT entity_id AS campaign_id, MAX(entity_name) AS campaign_name,
                       SUM(spend) AS spend, SUM(impressions) AS impressions,
                       SUM(clicks) AS clicks, SUM(conversions) AS conversions,
                       SUM(purchases) AS purchases,
                       CASE WHEN SUM(spend) > 0
                            THEN SUM(purchase_roas * spend) / SUM(spend) ELSE 0 END AS purchase_roas,
                       CASE WHEN SUM(impressions) > 0
                            THEN 100.0 * SUM(clicks) / SUM(impressions) ELSE 0 END AS ctr,
                       CASE WHEN SUM(clicks) > 0
                            THEN SUM(spend) / SUM(clicks) ELSE 0 END AS cpc
                FROM tiktok_ad_reports
                WHERE advertiser_id = ? AND data_level = 'AUCTION_CAMPAIGN'
                  AND stat_date >= ?
                GROUP BY entity_id ORDER BY spend DESC
                """,
                (advertiser_id, since),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_sync(self, advertiser_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, status, started_at, ended_at, rows_synced, error_message
                FROM tiktok_ad_sync_runs WHERE advertiser_id = ?
                ORDER BY started_at DESC LIMIT 1
                """,
                (advertiser_id,),
            ).fetchone()
        return dict(row) if row else None


class TikTokAdsService:
    def __init__(
        self,
        settings: Settings | None = None,
        client: TikTokBusinessClient | None = None,
        repository: TikTokAdsRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or TikTokAdsRepository(self.settings.sqlite_path)
        self.client = client or TikTokBusinessClient(
            self.settings.tiktok_business_access_token,
            self.settings.tiktok_business_advertiser_id,
            self.settings.tiktok_business_base_url,
            self.settings.tiktok_request_timeout_seconds,
        )

    @property
    def metrics(self) -> list[str]:
        return [value.strip() for value in self.settings.tiktok_ads_metrics.split(",") if value.strip()]

    def sync(self, days: int | None = None) -> AdsSyncSummary:
        self._require_config()
        report_days = max(1, min(90, days or self.settings.tiktok_ads_report_days))
        end_date = date.today()
        start_date = end_date - timedelta(days=report_days - 1)
        run_id = self.repository.begin_sync(self.settings.tiktok_business_advertiser_id)
        rows_synced = 0
        collected_at = _iso()
        try:
            specs = [
                ("AUCTION_ADVERTISER", ["advertiser_id", "stat_time_day"], self.metrics),
                (
                    "AUCTION_CAMPAIGN",
                    ["campaign_id", "stat_time_day"],
                    list(dict.fromkeys([*self.metrics, "campaign_name"])),
                ),
            ]
            for data_level, dimensions, metrics in specs:
                page = 1
                while True:
                    data = self.client.report(
                        data_level=data_level,
                        dimensions=dimensions,
                        metrics=metrics,
                        start_date=start_date,
                        end_date=end_date,
                        page=page,
                    )
                    rows = data.get("list", []) or []
                    for row in rows:
                        self.repository.save_row(
                            self.settings.tiktok_business_advertiser_id,
                            data_level,
                            row,
                            collected_at,
                        )
                        rows_synced += 1
                    page_info = data.get("page_info", {}) or {}
                    total_pages = int(page_info.get("total_page") or page)
                    if not rows or page >= total_pages:
                        break
                    page += 1
            self.repository.finish_sync(run_id, "completed", rows_synced)
            return AdsSyncSummary(
                run_id,
                self.settings.tiktok_business_advertiser_id,
                rows_synced,
                start_date.isoformat(),
                end_date.isoformat(),
            )
        except Exception as exc:
            self.repository.finish_sync(run_id, "failed", rows_synced, str(exc))
            raise

    def _require_config(self) -> None:
        if not self.settings.tiktok_ads_configured:
            raise ValueError(
                "TikTok Ads is not configured. Set TIKTOK_BUSINESS_ACCESS_TOKEN and "
                "TIKTOK_BUSINESS_ADVERTISER_ID in .env."
            )
