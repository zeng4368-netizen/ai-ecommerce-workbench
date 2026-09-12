from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ecom_ops.core.settings import Settings
from ecom_ops.integrations.tiktok_business import REPORT_PATH, TikTokBusinessClient
from ecom_ops.services.tiktok_ads import TikTokAdsRepository, TikTokAdsService


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        base_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        output_dir=tmp_path / "output",
        screenshot_dir=tmp_path / "screenshots",
        log_dir=tmp_path / "logs",
        sqlite_path=tmp_path / "processed" / "ads.sqlite3",
        selectors_path=tmp_path / "selectors.yaml",
        tiktok_business_access_token="ads-token",
        tiktok_business_advertiser_id="adv-1",
        tiktok_ads_report_days=7,
        tiktok_ads_metrics="spend,impressions,clicks,conversion,onsite_total_purchase,onsite_purchases_roas",
    )


def test_business_client_builds_read_only_report_request() -> None:
    captured: dict = {}

    def transport(url: str, headers: dict[str, str], timeout: int) -> dict:
        captured.update(url=url, headers=headers, timeout=timeout)
        return {"code": 0, "data": {"list": []}}

    client = TikTokBusinessClient("secret-token", "adv-1", transport=transport)
    client.report(
        data_level="AUCTION_ADVERTISER",
        dimensions=["advertiser_id", "stat_time_day"],
        metrics=["spend", "impressions"],
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 4),
    )

    parsed = urlparse(captured["url"])
    query = parse_qs(parsed.query)
    assert parsed.path.endswith(REPORT_PATH)
    assert captured["headers"]["Access-Token"] == "secret-token"
    assert query["advertiser_id"] == ["adv-1"]
    assert query["data_level"] == ["AUCTION_ADVERTISER"]
    assert query["dimensions"] == ['["advertiser_id","stat_time_day"]']
    assert query["metrics"] == ['["spend","impressions"]']


def test_ads_repository_aggregates_kpis(tmp_path: Path) -> None:
    repository = TikTokAdsRepository(tmp_path / "ads.sqlite3")
    collected_at = "2026-08-04T04:00:00+00:00"
    repository.save_row(
        "adv-1",
        "AUCTION_ADVERTISER",
        {
            "dimensions": {"advertiser_id": "adv-1", "stat_time_day": date.today().isoformat()},
            "metrics": {
                "spend": "100",
                "impressions": "50000",
                "clicks": "1000",
                "conversion": "25",
                "onsite_total_purchase": "20",
                "onsite_purchases_roas": "10",
            },
        },
        collected_at,
    )
    repository.save_row(
        "adv-1",
        "AUCTION_CAMPAIGN",
        {
            "dimensions": {"campaign_id": "campaign-1", "stat_time_day": date.today().isoformat()},
            "metrics": {
                "campaign_name": "Hero SKU",
                "spend": "100",
                "impressions": "50000",
                "clicks": "1000",
                "conversion": "25",
                "onsite_total_purchase": "20",
                "onsite_purchases_roas": "10",
            },
        },
        collected_at,
    )

    overview = repository.overview("adv-1", 7)
    campaigns = repository.campaigns("adv-1", 7)
    assert overview["ctr"] == 2
    assert overview["cpc"] == 0.1
    assert overview["cost_per_conversion"] == 4
    assert overview["purchase_roas"] == 10
    assert campaigns[0]["campaign_name"] == "Hero SKU"


class FakeBusinessClient:
    def report(self, **kwargs) -> dict:
        level = kwargs["data_level"]
        dimension_key = "advertiser_id" if level == "AUCTION_ADVERTISER" else "campaign_id"
        dimension_value = "adv-1" if level == "AUCTION_ADVERTISER" else "campaign-1"
        return {
            "list": [
                {
                    "dimensions": {
                        dimension_key: dimension_value,
                        "stat_time_day": date.today().isoformat(),
                    },
                    "metrics": {"spend": "12.5", "impressions": "2500", "clicks": "50"},
                }
            ],
            "page_info": {"total_page": 1},
        }


def test_ads_service_syncs_advertiser_and_campaign_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = TikTokAdsRepository(settings.sqlite_path)
    service = TikTokAdsService(settings, client=FakeBusinessClient(), repository=repository)  # type: ignore[arg-type]

    summary = service.sync(7)

    assert summary.rows_synced == 2
    assert repository.overview("adv-1", 7)["spend"] == 12.5
    assert repository.campaigns("adv-1", 7)[0]["campaign_id"] == "campaign-1"
    assert repository.latest_sync("adv-1")["status"] == "completed"
